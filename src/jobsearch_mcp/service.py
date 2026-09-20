"""Discovery orchestration shared by MCP and watcher."""

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime

from .applications import SUBMITTED_STAGES
from .http import capture_receipts
from .live import JobBatch, LiveResults
from .models import Job
from .reasoning import score_fit
from .relevance import discovery_validation, query_evidence
from .reporting import job_result
from .sources import public, scout
from .store import Store, canonical_url

ADAPTERS = {
    "himalayas": public.himalayas,
    "scout": scout.search,
    "adzuna": public.adzuna,
    "remotive": public.remotive,
    "jobicy": public.jobicy,
    "weworkremotely": public.weworkremotely,
}
CACHE_SECONDS = {
    "himalayas": 3600,
    "adzuna": 3600,
    "remotive": 21600,
    "jobicy": 21600,
    "weworkremotely": 21600,
    "scout": 3600,
}

MATERIAL_FIELDS = (
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
)


def materially_changed(previous: Job, current: Job) -> bool:
    """Ignore observation timestamps and lifecycle while detecting listing changes."""
    return any(getattr(previous, field) != getattr(current, field) for field in MATERIAL_FIELDS)


def material_hash(job: Job) -> str:
    payload = {}
    for field in MATERIAL_FIELDS:
        value = getattr(job, field)
        if field in {"source_url", "application_url"}:
            value = canonical_url(value) or value.strip()
        elif field in {"skills", "country_restrictions"}:
            value = sorted({re.sub(r"\s+", " ", str(item)).strip().casefold() for item in value})
        elif isinstance(value, str):
            value = re.sub(r"\s+", " ", value).strip()
        elif isinstance(value, datetime):
            value = value.astimezone(UTC).isoformat()
        payload[field] = value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def source_health(status: dict) -> dict:
    """Compact evidence of real adapter executions, including honest zero results."""
    executions = list(status.values())
    return {
        "successes": sum(item["execution"] == "success" for item in executions),
        "zero_results": sum(item["execution"] == "zero_results" for item in executions),
        "failures": sum(item["execution"] == "failure" for item in executions),
        "cached": sum(bool(item["cached"]) for item in executions),
        "latest_fetched_at": max(
            (item["fetched_at"] for item in executions if item["fetched_at"]), default=None
        ),
    }


def enabled_sources():
    names = os.getenv("CAREER_SOURCES", "himalayas,remotive,jobicy,weworkremotely").split(",")
    names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if unknown := set(names) - set(ADAPTERS):
        raise ValueError("Unknown sources: " + ",".join(sorted(unknown)))
    return names


class CareerService:
    def __init__(self, store: Store):
        self.store = store
        self.lock = asyncio.Lock()
        self.live_results = LiveResults()

    async def discover(
        self,
        query: str,
        sources: list[str] | None = None,
        *,
        track_watch: bool = False,
    ) -> dict:
        sources = sources or enabled_sources()
        if set(sources) - set(ADAPTERS):
            raise ValueError("Unknown source")
        query = query.strip()
        if not query or len(query) > 200:
            raise ValueError("Query must be 1\u2013200 characters")
        profile = self.store.get_profile()
        async with self.lock:
            results = await asyncio.gather(
                *(self._collect(name, query, use_cache=True) for name in sources)
            )
            found, report, changes = (
                {},
                {},
                {
                    "new": set(),
                    "changed": set(),
                    "unchanged": set(),
                    "applied_seen": set(),
                },
            )
            for name, jobs, cached, error, fetched_at, receipts in results:
                retrieved_count = len(jobs)
                validations = [
                    discovery_validation(job, query, profile.preferences, name) for job in jobs
                ]
                accepted = [
                    job
                    for job, validation in zip(jobs, validations, strict=True)
                    if validation["accepted"]
                ]
                rejected = [v for v in validations if not v["accepted"]]
                jobs = accepted
                report[name] = {
                    "status": "error" if error else "ok",
                    "execution": (
                        "cached"
                        if cached
                        else (
                            "failure"
                            if error
                            else ("success" if retrieved_count else "zero_results")
                        )
                    ),
                    "count": len(jobs),
                    "retrieved_count": retrieved_count,
                    "query_filtered_count": retrieved_count - len(jobs),
                    "validation_rejections": {
                        reason: sum(reason in item["rejection_reasons"] for item in rejected)
                        for reason in sorted(
                            {r for item in rejected for r in item["rejection_reasons"]}
                        )
                    },
                    "cached": cached,
                    "error_type": error,
                    "fetched_at": fetched_at,
                    "http": receipts,
                }
                for job in jobs:
                    try:
                        previous = self.store.find_match(job)
                        record = self.store.upsert(job)
                    except ValueError:
                        report[name].setdefault("records_requiring_review", 0)
                        report[name]["records_requiring_review"] += 1
                        continue
                    if track_watch:
                        observation = self.store.record_watch_observation(
                            record.id, material_hash(record), datetime.now(UTC)
                        )
                        state = observation["state"]
                    else:
                        state = (
                            "new"
                            if previous is None
                            else (
                                "changed" if materially_changed(previous, record) else "unchanged"
                            )
                        )
                    if previous is not None and (
                        previous.submission is not None or previous.status in SUBMITTED_STAGES
                    ):
                        state = "applied_seen"
                    changes[state].add(record.id)
                    found[record.id] = record
            items = []
            excluded = []
            for job_id in found:
                job = self.store.get(job_id)
                job.match_evidence = score_fit(job, profile)
                job.eligibility = job.match_evidence["location_eligibility"]
                self.store.save_evidence(job.id, job.match_evidence, job.eligibility)
                item = job_result(job, profile, compact=True)
                item["query_evidence"] = query_evidence(job, query)
                item["discovery_state"] = next(
                    state for state, job_ids in changes.items() if job.id in job_ids
                )
                (excluded if job.match_evidence["exclusions"] else items).append(item)
            return {
                "jobs": items,
                "excluded_jobs": excluded,
                "source_status": report,
                "source_health": source_health(report),
                "discovery_changes": {name: len(ids) for name, ids in changes.items()},
                "discovery_change_ids": {name: sorted(ids) for name, ids in changes.items()},
                "searched_at": datetime.now(UTC).isoformat(),
                "coverage": (
                    "Bounded first-page searches; source failures are not empty "
                    "successful searches."
                ),
                "persisted": True,
                "application_submitted": False,
            }

    async def _collect(self, name: str, query: str, *, use_cache: bool):
        # The watcher shares broad feeds across target queries. Live requests use
        # the same provider adapters, but never read or write this durable cache.
        broad_feed = name in {"remotive", "jobicy", "weworkremotely"}
        source_query = "" if broad_feed else query
        key = name + ":" + source_query.casefold()
        if use_cache:
            cached = self.store.cache_get(key, time.time())
            if cached is not None:
                jobs = [Job.model_validate(j) for j in cached]
                fetched = max((e.fetched_at for j in jobs for e in j.sources), default=None)
                return name, jobs, True, None, fetched.isoformat() if fetched else None, []
        try:
            with capture_receipts() as receipts:
                jobs = await asyncio.wait_for(ADAPTERS[name](source_query), timeout=60)
            fetched_at = datetime.now(UTC).isoformat()
            if use_cache:
                self.store.cache_set(
                    key,
                    [j.model_dump(mode="json") for j in jobs],
                    time.time() + CACHE_SECONDS[name],
                )
            return name, jobs, False, None, fetched_at, receipts
        except Exception as exc:
            # Exception strings may contain credential-bearing URLs. Never return
            # them, and never replace a provider failure with stale saved results.
            return name, [], False, type(exc).__name__, None, receipts

    async def search_live(
        self, query: str, sources: list[str] | None = None, limit: int = 25
    ) -> dict:
        """Fetch now, combine evidence in memory, and leave persistent state alone."""
        query = query.strip()
        if not query or len(query) > 200:
            raise ValueError("Query must be 1-200 characters")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be 1-100")
        enabled = enabled_sources()
        sources = enabled if sources is None else list(dict.fromkeys(sources))
        if not sources or set(sources) - set(enabled):
            raise ValueError("Choose one or more configured enabled sources")
        searched_at = datetime.now(UTC).isoformat()
        profile = self.store.get_profile()
        async with self.lock:
            results = await asyncio.gather(
                *(self._collect(name, query, use_cache=False) for name in sources)
            )
            batch, report = JobBatch(), {}
            for name, jobs, cached, error, fetched_at, receipts in results:
                retrieved_count = len(jobs)
                validations = [
                    discovery_validation(job, query, profile.preferences, name) for job in jobs
                ]
                accepted = [
                    job
                    for job, validation in zip(jobs, validations, strict=True)
                    if validation["accepted"]
                ]
                rejected = [v for v in validations if not v["accepted"]]
                jobs = accepted
                report[name] = {
                    "status": "error" if error else "ok",
                    "execution": (
                        "cached"
                        if cached
                        else (
                            "failure"
                            if error
                            else ("success" if retrieved_count else "zero_results")
                        )
                    ),
                    "count": len(jobs),
                    "retrieved_count": retrieved_count,
                    "query_filtered_count": retrieved_count - len(jobs),
                    "validation_rejections": {
                        reason: sum(reason in item["rejection_reasons"] for item in rejected)
                        for reason in sorted(
                            {r for item in rejected for r in item["rejection_reasons"]}
                        )
                    },
                    "cached": cached,
                    "error_type": error,
                    "fetched_at": fetched_at,
                    "http": receipts,
                }
                for job in jobs:
                    try:
                        batch.add(job)
                    except ValueError:
                        report[name]["records_requiring_review"] = (
                            report[name].get("records_requiring_review", 0) + 1
                        )
            candidates = sorted(
                batch.jobs.values(),
                key=lambda job: (
                    not query_evidence(job, query)["all_terms_in_title"],
                    -(job.posted_at.timestamp() if job.posted_at else 0),
                    job.title.casefold(),
                    job.id,
                ),
            )
            items, excluded = [], []
            for job in candidates[:limit]:
                saved_job_id = None
                identity_warning = None
                try:
                    saved = self.store.find_match(job)
                except ValueError:
                    saved = None
                    identity_warning = "Saved identities conflict; review before linking"
                if saved is not None:
                    saved_job_id = saved.id
                    # Preserve the user's lifecycle in the response without mixing
                    # older saved source content into a fresh provider snapshot.
                    job.status = saved.status
                    job.submission = saved.submission
                    job.follow_up_at = saved.follow_up_at
                job.unresolved_applications = self.store.application_review(job.company)
                job = self.live_results.add(job, saved_job_id)
                job.match_evidence = score_fit(job, profile)
                job.eligibility = job.match_evidence["location_eligibility"]
                item = job_result(job, profile, compact=True)
                item["query_evidence"] = query_evidence(job, query)
                item["saved_job_id"] = saved_job_id
                if identity_warning:
                    item["identity_warning"] = identity_warning
                (excluded if job.match_evidence["exclusions"] else items).append(item)
            return {
                "jobs": items,
                "excluded_jobs": excluded,
                "source_status": report,
                "source_health": source_health(report),
                "searched_at": searched_at,
                "completed_at": datetime.now(UTC).isoformat(),
                "total_count": len(candidates),
                "returned_count": len(items) + len(excluded),
                "limit": limit,
                "truncated": len(candidates) > limit,
                "coverage": (
                    "Fresh provider requests; no saved-listing or source-cache fallback. "
                    "Bounded first-page searches/feeds, not exhaustive market coverage. "
                    "Whole-word query filtering requires role terms in the title; "
                    "all query terms in the title sort before description matches, "
                    "then by recency. "
                    "Fresh retrieval does not guarantee the provider's listings are current."
                ),
                "live_reference": (
                    "Use live: IDs with get_job_detail, score_fit, tailor_resume or "
                    "cover_letter_brief. References remain in memory up to 15 minutes "
                    "(500 newest records); after expiry, eviction or restart, search again."
                ),
                "persisted": False,
                "application_submitted": False,
            }

    def get_job(self, job_id: str) -> Job:
        if job_id.startswith("live:"):
            job, saved_job_id = self.live_results.resolve(job_id)
            saved = self.store.get(saved_job_id) if saved_job_id else self.store.find_match(job)
            if saved:
                job.status, job.follow_up_at = saved.status, saved.follow_up_at
                job.submission = saved.submission
            job.unresolved_applications = self.store.application_review(job.company)
            return job
        job = self.store.get(job_id)
        job.unresolved_applications = self.store.application_review(job.company)
        return job

    def get_history(self, job_id: str) -> list[dict]:
        if job_id.startswith("live:"):
            job, saved_job_id = self.live_results.resolve(job_id)
            saved = self.store.get(saved_job_id) if saved_job_id else self.store.find_match(job)
            return self.store.history(saved.id) if saved else []
        return self.store.history(job_id)
