"""Discovery orchestration shared by MCP and watcher."""

import asyncio
import os
import time
from datetime import UTC, datetime

from .models import Job
from .reasoning import score_fit
from .sources import public
from .store import Store

ADAPTERS = {
    "himalayas": public.himalayas,
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

    async def discover(self, query: str, sources: list[str] | None = None) -> dict:
        sources = sources or enabled_sources()
        if set(sources) - set(ADAPTERS):
            raise ValueError("Unknown source")
        query = query.strip()
        if not query or len(query) > 200:
            raise ValueError("Query must be 1\u2013200 characters")
        profile = self.store.get_profile()
        async with self.lock:

            async def collect(name):
                # Broad public feeds are shared across all six target-role queries.
                broad_feed = name in {"remotive", "jobicy", "weworkremotely"}
                source_query = "" if broad_feed else query
                key = name + ":" + source_query.casefold()
                cached = self.store.cache_get(key, time.time())
                if cached is not None:
                    return name, [Job.model_validate(j) for j in cached], True, None
                try:
                    jobs = await asyncio.wait_for(ADAPTERS[name](source_query), timeout=60)
                    self.store.cache_set(
                        key,
                        [j.model_dump(mode="json") for j in jobs],
                        time.time() + CACHE_SECONDS[name],
                    )
                    return name, jobs, False, None
                except Exception as exc:
                    # Exception strings often contain full request URLs/API keys.
                    return name, [], False, type(exc).__name__

            results = await asyncio.gather(*(collect(name) for name in sources))
            found, report = {}, {}
            for name, jobs, cached, error in results:
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
