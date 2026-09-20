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
        key=lambda s: (SOURCE_PRIORITY.get(s.source, 99), -s.fetched_at.timestamp()),
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
                """
            )

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
