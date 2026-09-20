"""Single-user persistence with atomic deduplication and auditable state changes.

SQLite WAL supports the MCP process and one watcher on the same local volume.
Every mutation holds a write transaction; no read/modify/write race is exposed.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .application_packs import ApplicationPack, ApplicationPackDraft
from .applications import SUBMITTED_STAGES
from .models import Job, Profile, Status, Submission

SOURCE_PRIORITY = {
    "himalayas": 0,
    "scout": 1,
    "adzuna": 2,
    "jobicy": 3,
    "remotive": 4,
    "weworkremotely": 5,
}
TRACKING_KEYS = {"ref", "source", "referrer", "trk", "trackingId"}


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    if p.scheme not in {"https", "http"} or not p.hostname:
        return ""
    path = p.path.rstrip("/")
    # Ashby's job and application pages identify the same exact requisition.
    # Do not strip generic '/application' paths on unrelated hosts.
    if p.hostname.lower() == "jobs.ashbyhq.com" and re.fullmatch(
        r"/[^/]+/[0-9a-fA-F-]{36}/application", path
    ):
        path = path.removesuffix("/application")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not k.lower().startswith("utm_") and k not in TRACKING_KEYS
    ]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(sorted(query)), ""))


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.casefold())).strip()


def identity_keys(job: Job) -> list[str]:
    keys = ["source:" + s.source + ":" + s.source_id for s in job.sources if s.source_id]
    keys += [
        "url:" + value
        for url in [job.source_url, job.application_url]
        if (value := canonical_url(url))
    ]
    # Only exact, contextual fallback matches. Distinct requisitions in one source
    # are protected below; vague title/company fuzzy matching is deliberately absent.
    if job.company and job.location and job.posted_at:
        fields = [
            normalized(job.company),
            normalized(job.title),
            normalized(job.location),
            job.employment_type,
            job.posted_at.date().isoformat(),
        ]
        keys.append("fingerprint:" + hashlib.sha256("|".join(fields).encode()).hexdigest())
    return list(dict.fromkeys(keys))


def find_duplicate(job: Job, lookup: Callable[[str], Job | None]) -> Job | None:
    """Use the same conservative identity rules for saved and request-local jobs."""
    keys = identity_keys(job)
    if not keys:
        raise ValueError("Job requires source identity or a valid URL")
    matches = {}
    for key in keys:
        candidate = lookup(key)
        if candidate is None:
            continue
        if key.startswith("fingerprint:"):
            old_ids = {(s.source, s.source_id) for s in candidate.sources}
            if any(
                s.source == old_source and s.source_id != old_id
                for s in job.sources
                for old_source, old_id in old_ids
            ):
                continue
        matches[candidate.id] = candidate
    if len(matches) > 1:
        raise ValueError("Ambiguous duplicate identities require review")
    return next(iter(matches.values()), None)


def merge_records(old: Job, new: Job) -> Job:
    evidence = {(s.source, s.source_id): s for s in old.sources}
    for source in new.sources:
        previous = evidence.get((source.source, source.source_id))
        if previous is None or source.fetched_at >= previous.fetched_at:
            evidence[(source.source, source.source_id)] = source
    ranked = sorted(
        evidence.values(),
        key=lambda s: (
            0 if s.retrieval_method.upper() == "DIRECT_SITE_OR_ATS" else 1,
            SOURCE_PRIORITY.get(s.source, 99),
            -s.fetched_at.timestamp(),
        ),
    )
    data = old.model_dump()
    # Rebuild selected fields from provenance, rather than depending on arrival order.
    fields = [
        "title",
        "company",
        "location",
        "remote_scope",
        "salary_min",
        "salary_max",
        "currency",
        "salary_period",
        "salary_is_predicted",
        "salary_text",
        "employment_type",
        "posted_at",
        "source_url",
        "application_url",
        "description",
        "skills",
        "country_restrictions",
    ]
    conflicts = []
    for field in fields:
        values = [
            s.fields[field] for s in ranked if s.fields.get(field) not in (None, "", [], "unknown")
        ]
        if values:
            data[field] = values[0]
            distinct = {json.dumps(v, sort_keys=True, default=str) for v in values}
            if len(distinct) > 1 and field in {
                "location",
                "salary_min",
                "salary_max",
                "currency",
                "remote_scope",
                "employment_type",
                "country_restrictions",
            }:
                conflicts.append({"field": field, "values": values})
    # Salary is a single unit of evidence; never combine one source's amount with
    # another source's currency, period or disclosure status.
    salary_source = next(
        (
            s
            for s in ranked
            if s.fields.get("salary_min") is not None or s.fields.get("salary_max") is not None
        ),
        None,
    )
    if salary_source:
        for field in [
            "salary_min",
            "salary_max",
            "currency",
            "salary_period",
            "salary_is_predicted",
            "salary_text",
        ]:
            data[field] = salary_source.fields.get(
                field, False if field == "salary_is_predicted" else None
            )
        data["salary_text"] = data["salary_text"] or ""
    data.update(sources=ranked, conflicts=conflicts, last_seen=datetime.now(UTC))
    return Job.model_validate(data)


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identities (
                    key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    old_status TEXT,
                    new_status TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_cache (
                    key TEXT PRIMARY KEY,
                    expires REAL NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS application_review (
                    id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS application_pack_versions (
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    revision INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY(job_id, revision)
                );
                CREATE TABLE IF NOT EXISTS watch_observations (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                    material_hash TEXT NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    last_observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watch_changes (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    state TEXT NOT NULL CHECK(state IN ('new', 'changed')),
                    previous_hash TEXT,
                    material_hash TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_health (
                    source TEXT PRIMARY KEY,
                    checked_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _fingerprint(value) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def _job_evidence_fingerprint(cls, job: Job) -> str:
        def text(value) -> str:
            return re.sub(r"\s+", " ", str(value or "")).strip()

        return cls._fingerprint(
            {
                "title": text(job.title),
                "company": text(job.company),
                "location": text(job.location),
                "remote_scope": job.remote_scope,
                "salary": [
                    job.salary_min,
                    job.salary_max,
                    job.currency,
                    job.salary_period,
                    job.salary_is_predicted,
                    text(job.salary_text),
                ],
                "employment_type": job.employment_type,
                "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                "source_url": canonical_url(job.source_url),
                "application_url": canonical_url(job.application_url),
                "description": text(job.description),
                "skills": sorted({text(value).casefold() for value in job.skills}),
                "country_restrictions": sorted(
                    {text(value).casefold() for value in job.country_restrictions}
                ),
                "provenance": sorted(
                    {
                        (
                            source.source,
                            source.source_id,
                            canonical_url(source.source_url),
                            canonical_url(source.application_url),
                            source.retrieval_method,
                        )
                        for source in job.sources
                    }
                ),
            }
        )

    @classmethod
    def _profile_evidence_fingerprint(cls, profile: Profile, cv_variant: str) -> str:
        variant = profile.resume_variants[cv_variant]
        return cls._fingerprint(
            {
                "cv_variant": variant.model_dump(mode="json"),
                "verified_skills": sorted(
                    skill
                    for skill in profile.verified_skills
                    if profile.skill_evidence.get(skill, "") in variant.resume_text
                ),
                "skill_evidence": {
                    skill: quote
                    for skill, quote in sorted(profile.skill_evidence.items())
                    if quote and quote in variant.resume_text
                },
                "experience_evidence": sorted(
                    quote for quote in profile.experience_evidence if quote in variant.resume_text
                ),
                "country": profile.country,
                "work_authorization": profile.work_authorization,
            }
        )

    def save_application_pack(
        self, job_id: str, expected_revision: int, draft: ApplicationPackDraft
    ) -> ApplicationPack:
        """Append a version if the caller still holds the latest revision."""
        if expected_revision < 0:
            raise ValueError("Expected revision must be zero or greater")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job ID; persist exact vacancy evidence first")
            job = Job.model_validate_json(row[0])
            profile_row = db.execute("SELECT data FROM profile WHERE id=1").fetchone()
            profile = Profile.model_validate_json(profile_row[0]) if profile_row else Profile()
            if draft.cv_variant not in profile.resume_variants:
                raise ValueError("Unknown CV variant; save it in the canonical profile first")
            current = db.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM application_pack_versions WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            if current != expected_revision:
                raise ValueError(
                    f"Application pack revision conflict: expected {expected_revision}, "
                    f"current revision is {current}"
                )
            revision = current + 1
            pack = ApplicationPack.saved(
                draft=draft,
                job_id=job_id,
                revision=revision,
                saved_at=datetime.now(UTC),
                job_fingerprint=self._job_evidence_fingerprint(job),
                profile_fingerprint=self._profile_evidence_fingerprint(profile, draft.cv_variant),
            )
            db.execute(
                "INSERT INTO application_pack_versions(job_id,revision,data) VALUES(?,?,?)",
                (job_id, revision, pack.model_dump_json()),
            )
        return pack

    def get_application_pack(
        self, job_id: str, revision: int | None = None
    ) -> ApplicationPack | None:
        """Read a pack revision and report drift from its saved evidence basis."""
        job = self.get(job_id)
        with self.connection() as db:
            if revision is None:
                row = db.execute(
                    """SELECT data FROM application_pack_versions
                    WHERE job_id=? ORDER BY revision DESC LIMIT 1""",
                    (job_id,),
                ).fetchone()
            else:
                if revision < 1:
                    raise ValueError("Revision must be one or greater")
                row = db.execute(
                    "SELECT data FROM application_pack_versions WHERE job_id=? AND revision=?",
                    (job_id, revision),
                ).fetchone()
        if not row:
            return None
        pack = ApplicationPack.model_validate_json(row[0])
        return pack.model_copy(
            update={
                "job_evidence_stale": (
                    pack.job_evidence_fingerprint != self._job_evidence_fingerprint(job)
                ),
                "profile_evidence_stale": (
                    pack.profile_evidence_fingerprint
                    != self._profile_evidence_fingerprint(self.get_profile(), pack.cv_variant)
                ),
            }
        )

    def record_watch_observation(
        self, job_id: str, material_hash: str, observed_at: datetime
    ) -> dict:
        """Persist watcher material state without altering application lifecycle."""
        material_hash = material_hash.strip()
        if not material_hash or len(material_hash) > 256:
            raise ValueError("Material hash must be 1-256 characters")
        if observed_at.tzinfo is None:
            raise ValueError("Observation time must include a timezone")
        timestamp = observed_at.astimezone(UTC).isoformat()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                raise ValueError("Unknown job ID")
            row = db.execute(
                "SELECT material_hash FROM watch_observations WHERE job_id=?", (job_id,)
            ).fetchone()
            previous_hash = row[0] if row else None
            state = (
                "new"
                if row is None
                else "unchanged"
                if previous_hash == material_hash
                else "changed"
            )
            if row is None:
                db.execute(
                    "INSERT INTO watch_observations VALUES(?,?,?,?)",
                    (job_id, material_hash, timestamp, timestamp),
                )
            else:
                db.execute(
                    """UPDATE watch_observations
                    SET material_hash=?, last_observed_at=? WHERE job_id=?""",
                    (material_hash, timestamp, job_id),
                )
            if state != "unchanged":
                db.execute(
                    """INSERT INTO watch_changes(
                    job_id,state,previous_hash,material_hash,observed_at) VALUES(?,?,?,?,?)""",
                    (job_id, state, previous_hash, material_hash, timestamp),
                )
        return {
            "job_id": job_id,
            "state": state,
            "previous_hash": previous_hash,
            "material_hash": material_hash,
            "observed_at": timestamp,
        }

    def list_watch_changes(self, since: datetime, limit: int = 100) -> list[dict]:
        """Return bounded, actionable saved-job changes after an aware timestamp."""
        if since.tzinfo is None:
            raise ValueError("Since time must include a timezone")
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT c.job_id,c.state,c.previous_hash,c.material_hash,c.observed_at,
                json_extract(j.data, '$.title') AS title,
                json_extract(j.data, '$.company') AS company
                FROM watch_changes c JOIN jobs j ON j.id=c.job_id
                WHERE c.observed_at>? ORDER BY c.observed_at,c.id LIMIT ?""",
                (since.astimezone(UTC).isoformat(), max(1, min(limit, 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_source_health(self, checked_at: datetime, source_status: dict) -> dict:
        """Retain sanitized latest watcher health; never persist raw errors or URLs."""
        if checked_at.tzinfo is None:
            raise ValueError("Health check time must include a timezone")
        timestamp = checked_at.astimezone(UTC).isoformat()
        records = []
        for source, item in source_status.items():
            if not re.fullmatch(r"[a-z0-9_-]{1,100}", source):
                raise ValueError("Invalid source name")
            execution = item.get("execution")
            if execution not in {"success", "zero_results", "failure", "cached"}:
                raise ValueError("Invalid source execution state")
            fetched_at = item.get("fetched_at")
            if fetched_at:
                parsed = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Source fetch time must include a timezone")
                fetched_at = parsed.astimezone(UTC).isoformat()
            error_type = item.get("error_type")
            if error_type and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]{0,199}", str(error_type)):
                error_type = "SourceError"
            rejections = item.get("validation_rejections") or {}
            sanitized_rejections = {
                str(reason)[:100]: max(0, int(count))
                for reason, count in rejections.items()
                if isinstance(count, int | float)
            }
            http_observations = []
            raw_http = item.get("http") or []
            if isinstance(raw_http, dict):
                raw_http = [raw_http]
            for observation in raw_http[:10]:
                code = observation.get("http_code")
                outcome = observation.get("outcome")
                observed_at = observation.get("fetched_at") or observation.get("checked_at")
                if not isinstance(code, int) or not 100 <= code <= 599:
                    continue
                if outcome not in {"SUCCESS", "HTTP_ERROR"} or not observed_at:
                    continue
                parsed_at = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
                if parsed_at.tzinfo is None:
                    continue
                http_observations.append(
                    {
                        "http_code": code,
                        "outcome": outcome,
                        "checked_at": parsed_at.astimezone(UTC).isoformat(),
                    }
                )
            record = {
                "source": source,
                "execution": execution,
                "count": max(0, int(item.get("count", 0))),
                "retrieved_count": max(0, int(item.get("retrieved_count", 0))),
                "query_filtered_count": max(0, int(item.get("query_filtered_count", 0))),
                "cached": bool(item.get("cached", execution == "cached")),
                "error_type": str(error_type) if error_type else None,
                "fetched_at": fetched_at,
                "validation_rejections": sanitized_rejections,
                "http_codes": sorted(
                    {observation["http_code"] for observation in http_observations}
                ),
                "http_checked_at": max(
                    (observation["checked_at"] for observation in http_observations),
                    default=None,
                ),
                "checked_at": timestamp,
            }
            records.append((source, timestamp, json.dumps(record, sort_keys=True)))
        with self.connection() as db:
            db.executemany(
                """INSERT INTO source_health VALUES(?,?,?)
                ON CONFLICT(source) DO UPDATE SET
                checked_at=excluded.checked_at,data=excluded.data""",
                records,
            )
        return self.get_source_health()

    def get_source_health(self) -> dict:
        with self.connection() as db:
            rows = db.execute("SELECT data FROM source_health ORDER BY source").fetchall()
        sources = [json.loads(row[0]) for row in rows]
        return {
            "sources": sources,
            "summary": {
                "success": sum(item["execution"] == "success" for item in sources),
                "zero_results": sum(item["execution"] == "zero_results" for item in sources),
                "failure": sum(item["execution"] == "failure" for item in sources),
                "cached": sum(item["execution"] == "cached" for item in sources),
            },
            "latest_checked_at": max((item["checked_at"] for item in sources), default=None),
        }

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def upsert(self, job: Job) -> Job:
        keys = identity_keys(job)
        if not keys:
            raise ValueError("Job requires source identity or a valid URL")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self._find_match(db, job)
            if existing is not None:
                result = merge_records(existing, job)
            else:
                now = datetime.now(UTC)
                result = job.model_copy(
                    update={
                        "id": hashlib.sha256(keys[0].encode()).hexdigest()[:24],
                        "first_seen": now,
                        "last_seen": now,
                    }
                )
                db.execute(
                    "INSERT INTO events(job_id,at,new_status,reason) VALUES(?,?,?,?)",
                    (result.id, now.isoformat(), result.status.value, "discovered"),
                )
            db.execute(
                "INSERT INTO jobs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (result.id, result.model_dump_json()),
            )
            for key in keys:
                db.execute("INSERT OR IGNORE INTO identities VALUES(?,?)", (key, result.id))
        return result

    @staticmethod
    def _find_match(db, job: Job) -> Job | None:
        def lookup(key):
            row = db.execute(
                "SELECT j.data FROM identities i JOIN jobs j ON j.id=i.job_id WHERE i.key=?",
                (key,),
            ).fetchone()
            return Job.model_validate_json(row[0]) if row else None

        return find_duplicate(job, lookup)

    def find_match(self, job: Job) -> Job | None:
        """Read existing identity/lifecycle evidence without updating discovery dates."""
        with self.connection() as db:
            return self._find_match(db, job)

    def get(self, job_id: str) -> Job:
        with self.connection() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown job ID")
        return Job.model_validate_json(row[0])

    def list_jobs(
        self, status: Status | None = None, limit: int = 100, offset: int = 0
    ) -> list[Job]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT data
                FROM jobs
                WHERE (? IS NULL OR json_extract(data, '$.status') = ?)
                ORDER BY json_extract(data, '$.last_seen') DESC
                LIMIT ? OFFSET ?
                """,
                (status, status, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def search_jobs(
        self, query: str, status: Status | None = None, limit: int = 50, offset: int = 0
    ) -> list[Job]:
        """Read saved jobs using literal, case-insensitive words before pagination."""
        words = query.strip().lower().split()
        if not words or len(query) > 200:
            raise ValueError("Query must be 1-200 characters")
        # Bound parameters make quotes and SQL wildcard characters ordinary text.
        text = (
            "lower(json_extract(data, '$.title') || ' ' || "
            "json_extract(data, '$.company') || ' ' || json_extract(data, '$.description'))"
        )
        conditions = " AND ".join(f"instr({text}, ?) > 0" for _ in words)
        with self.connection() as db:
            rows = db.execute(
                "SELECT data FROM jobs WHERE "
                + conditions
                + " AND (? IS NULL OR json_extract(data, '$.status') = ?)"
                + " ORDER BY json_extract(data, '$.last_seen') DESC, id LIMIT ? OFFSET ?",
                (*words, status, status, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def import_application_review(self, records: list[dict]) -> int:
        """Retain confirmed history lacking an exact requisition; never suppress a company."""
        validated = []
        for record in records:
            if not record.get("company") or not record.get("evidence_of_actual_submission"):
                raise ValueError("Unlinked history requires company and submission evidence")
            encoded = json.dumps(record, sort_keys=True)
            if len(encoded) > 10000:
                raise ValueError("Unlinked history record too large")
            validated.append(
                (
                    hashlib.sha256(encoded.encode()).hexdigest(),
                    normalized(record["company"]),
                    encoded,
                )
            )
        with self.connection() as db:
            db.executemany("INSERT OR IGNORE INTO application_review VALUES(?,?,?)", validated)
        return len(validated)

    def application_review(self, company: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT data FROM application_review WHERE company=?", (normalized(company),)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def mark_as_applied(self, job_id: str, submission: Submission) -> Job:
        """Record confirmation once, atomically; retries never regress later stages."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job ID; import exact vacancy evidence first")
            job = Job.model_validate_json(row[0])
            if job.submission:
                return job
            old_status = job.status
            job.submission = submission
            if job.status not in SUBMITTED_STAGES | {
                Status.REJECTED,
                Status.WITHDRAWN,
                Status.CLOSED,
            }:
                job.status = Status.APPLIED
            db.execute(
                "INSERT INTO events(job_id,at,old_status,new_status,reason) VALUES(?,?,?,?,?)",
                (
                    job.id,
                    submission.recorded_at.isoformat(),
                    old_status.value,
                    job.status.value,
                    "Submission confirmed: " + submission.evidence,
                ),
            )
            db.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job.id))
        return job

    def migrate_submissions(self) -> int:
        """Preserve recorded legacy submission history, without guessing submission dates."""
        count = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for job_id, data in db.execute("SELECT id,data FROM jobs").fetchall():
                job = Job.model_validate_json(data)
                if job.submission:
                    continue
                history = db.execute(
                    "SELECT at,new_status,reason FROM events WHERE job_id=? ORDER BY id", (job_id,)
                ).fetchall()
                evidence = next((r for r in history if r[1] in SUBMITTED_STAGES), None)
                if evidence is None:
                    continue
                job.submission = Submission(
                    confirmed=True,
                    recorded_at=datetime.now(UTC),
                    evidence=(
                        f"Existing lifecycle record {evidence[0]}: {evidence[1]}; {evidence[2]}"
                    )[:2000],
                    evidence_source="legacy_application_state",
                )
                db.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id))
                count += 1
        return count

    def update_status(
        self, job_id: str, status: Status, reason: str, follow_up_at: datetime | None = None
    ) -> Job:
        if follow_up_at and follow_up_at.tzinfo is None:
            raise ValueError("Follow-up date must include a timezone")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job ID")
            job = Job.model_validate_json(row[0])
            db.execute(
                "INSERT INTO events(job_id,at,old_status,new_status,reason) VALUES(?,?,?,?,?)",
                (job.id, datetime.now(UTC).isoformat(), job.status.value, status.value, reason),
            )
            job.status = status
            if status in SUBMITTED_STAGES and job.submission is None:
                job.submission = Submission(
                    confirmed=True,
                    recorded_at=datetime.now(UTC),
                    evidence=reason,
                    evidence_source="legacy_application_state",
                )
            job.follow_up_at = follow_up_at
            db.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job.id))
        return job

    def advance_followups(self, now: datetime) -> int:
        count = 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for job_id, data in db.execute("SELECT id,data FROM jobs").fetchall():
                job = Job.model_validate_json(data)
                if (
                    job.status in {Status.APPLIED, Status.AWAITING_RESPONSE}
                    and job.follow_up_at
                    and job.follow_up_at <= now
                ):
                    db.execute(
                        """
                        INSERT INTO events(job_id, at, old_status, new_status, reason)
                        VALUES(?,?,?,?,?)
                        """,
                        (
                            job.id,
                            now.isoformat(),
                            job.status.value,
                            Status.FOLLOW_UP_DUE.value,
                            "scheduled follow-up became due; no message sent",
                        ),
                    )
                    job.status = Status.FOLLOW_UP_DUE
                    db.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id))
                    count += 1
        return count

    def save_evidence(self, job_id: str, evidence: dict, eligibility: dict):
        """Update derived evidence without overwriting a concurrent lifecycle change."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Unknown job ID")
            job = Job.model_validate_json(row[0])
            job.match_evidence = evidence
            job.eligibility = eligibility
            db.execute("UPDATE jobs SET data=? WHERE id=?", (job.model_dump_json(), job_id))

    def history(self, job_id: str) -> list[dict]:
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,))
            ]

    def get_profile(self) -> Profile:
        with self.connection() as db:
            row = db.execute("SELECT data FROM profile WHERE id=1").fetchone()
        return Profile.model_validate_json(row[0]) if row else Profile()

    def save_profile(self, profile: Profile):
        for skill in profile.verified_skills:
            quote = profile.skill_evidence.get(skill, "")
            if not quote or quote not in profile.resume_text:
                raise ValueError("Every verified skill needs a literal resume excerpt")
        if any(quote not in profile.resume_text for quote in profile.experience_evidence):
            raise ValueError("Experience evidence must quote the resume")
        for variant in profile.resume_variants.values():
            if variant.resume_text not in profile.resume_text:
                raise ValueError("CV variants must be included in the canonical resume evidence")
            if any(
                not quote or quote not in variant.resume_text
                for quote in variant.skill_evidence.values()
            ):
                raise ValueError("Variant skill evidence must quote that CV")
        with self.connection() as db:
            db.execute(
                "INSERT INTO profile VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (profile.model_dump_json(),),
            )

    def cache_get(self, key: str, now: float):
        with self.connection() as db:
            row = db.execute(
                "SELECT data FROM source_cache WHERE key=? AND expires>?", (key, now)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def cache_set(self, key: str, data, expires: float):
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO source_cache VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE
                SET expires=excluded.expires, data=excluded.data
                """,
                (key, expires, json.dumps(data)),
            )
