"""Discovery orchestration shared by MCP and watcher."""

import asyncio
import os
import time
from datetime import UTC, datetime

from .live import JobBatch, LiveResults
from .models import Job
from .reasoning import score_fit
from .sources import public, scout
from .store import Store

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

    async def discover(self, query: str, sources: list[str] | None = None) -> dict:
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
            found, report = {}, {}
            for name, jobs, cached, error, fetched_at in results:
                if name in {"remotive", "jobicy", "weworkremotely"}:
                    words = query.casefold().split()
                    jobs = [
                        j
                        for j in jobs
                        if all(word in (j.title + " " + j.description).casefold() for word in words)
                    ]
                report[name] = {
                    "status": "error" if error else "ok",
                    "count": len(jobs),
                    "cached": cached,
                    "error_type": error,
                    "fetched_at": fetched_at,
                }
                for job in jobs:
                    try:
                        record = self.store.upsert(job)
                    except ValueError:
                        report[name].setdefault("records_requiring_review", 0)
                        report[name]["records_requiring_review"] += 1
                        continue
                    found[record.id] = record
            items = []
            excluded = []
            for job_id in found:
                job = self.store.get(job_id)
                job.match_evidence = score_fit(job, profile)
                job.eligibility = job.match_evidence["location_eligibility"]
                self.store.save_evidence(job.id, job.match_evidence, job.eligibility)
                item = job.model_dump(mode="json")
                item["description"] = job.description[:1500]
                item["description_truncated"] = len(job.description) > 1500
                item["sources"] = [
                    s.model_dump(mode="json", exclude={"fields"}) for s in job.sources
                ]
                (excluded if job.match_evidence["exclusions"] else items).append(item)
            return {
                "jobs": items,
                "excluded_jobs": excluded,
                "source_status": report,
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
                return name, jobs, True, None, fetched.isoformat() if fetched else None
        try:
            jobs = await asyncio.wait_for(ADAPTERS[name](source_query), timeout=60)
            fetched_at = datetime.now(UTC).isoformat()
            if use_cache:
                self.store.cache_set(
                    key,
                    [j.model_dump(mode="json") for j in jobs],
                    time.time() + CACHE_SECONDS[name],
                )
            return name, jobs, False, None, fetched_at
        except Exception as exc:
            # Exception strings may contain credential-bearing URLs. Never return
            # them, and never replace a provider failure with stale saved results.
            return name, [], False, type(exc).__name__, None

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
            for name, jobs, cached, error, fetched_at in results:
                if name in {"remotive", "jobicy", "weworkremotely"}:
                    words = query.casefold().split()
                    jobs = [
                        job
                        for job in jobs
                        if all(
                            word in (job.title + " " + job.description).casefold() for word in words
                        )
                    ]
                report[name] = {
                    "status": "error" if error else "ok",
                    "count": len(jobs),
                    "cached": cached,
                    "error_type": error,
                    "fetched_at": fetched_at,
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
                    job.follow_up_at = saved.follow_up_at
                job = self.live_results.add(job, saved_job_id)
                job.match_evidence = score_fit(job, profile)
                job.eligibility = job.match_evidence["location_eligibility"]
                item = job.model_dump(mode="json")
                item["description"] = job.description[:1500]
                item["description_truncated"] = len(job.description) > 1500
                item["sources"] = [
                    source.model_dump(mode="json", exclude={"fields"}) for source in job.sources
                ]
                item["saved_job_id"] = saved_job_id
                if identity_warning:
                    item["identity_warning"] = identity_warning
                (excluded if job.match_evidence["exclusions"] else items).append(item)
            return {
                "jobs": items,
                "excluded_jobs": excluded,
                "source_status": report,
                "searched_at": searched_at,
                "completed_at": datetime.now(UTC).isoformat(),
                "total_count": len(candidates),
                "returned_count": len(items) + len(excluded),
                "limit": limit,
                "truncated": len(candidates) > limit,
                "coverage": (
                    "Fresh provider requests; no saved-listing or source-cache fallback. "
                    "Bounded first-page searches/feeds, not exhaustive market coverage. "
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
            if saved_job_id:
                saved = self.store.get(saved_job_id)
                job.status, job.follow_up_at = saved.status, saved.follow_up_at
            return job
        return self.store.get(job_id)

    def get_history(self, job_id: str) -> list[dict]:
        if job_id.startswith("live:"):
            _, saved_job_id = self.live_results.resolve(job_id)
            return self.store.history(saved_job_id) if saved_job_id else []
        return self.store.history(job_id)
