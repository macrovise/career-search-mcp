"""Scheduled discovery and follow-up transitions; no mail, messages or applications."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime

from dotenv import load_dotenv

from .service import CareerService
from .store import Store


async def run_once(service):
    results = []
    observed = {}
    health_by_source = {}
    for role in service.store.get_profile().preferences.target_roles:
        result = await service.discover(role, track_watch=True)
        # The same vacancy can match several focused role searches. Report it
        # once, retaining the most review-worthy state from this run.
        priority = {"unchanged": 0, "applied_seen": 1, "changed": 2, "new": 3}
        for state, job_ids in result["discovery_change_ids"].items():
            for job_id in job_ids:
                if job_id not in observed or priority[state] > priority[observed[job_id]]:
                    observed[job_id] = state
        execution_priority = {"cached": 0, "zero_results": 1, "success": 2, "failure": 3}
        for source, status in result["source_status"].items():
            current = health_by_source.get(source)
            if current is None:
                health_by_source[source] = {
                    **status,
                    "validation_rejections": dict(status["validation_rejections"]),
                    "http": list(status["http"]),
                }
                continue
            current["count"] += status["count"]
            current["retrieved_count"] += status["retrieved_count"]
            current["query_filtered_count"] += status["query_filtered_count"]
            current["cached"] = current["cached"] and status["cached"]
            if execution_priority[status["execution"]] > execution_priority[current["execution"]]:
                current["execution"] = status["execution"]
                current["error_type"] = status["error_type"]
            if status["fetched_at"] and (
                not current["fetched_at"] or status["fetched_at"] > current["fetched_at"]
            ):
                current["fetched_at"] = status["fetched_at"]
            for reason, count in status["validation_rejections"].items():
                current["validation_rejections"][reason] = (
                    current["validation_rejections"].get(reason, 0) + count
                )
            current["http"].extend(status["http"])
        results.append(
            {
                "query": role,
                "accepted": len(result["jobs"]),
                "excluded": len(result["excluded_jobs"]),
                "sources": result["source_status"],
                "changes": result["discovery_changes"],
            }
        )
    due = service.store.advance_followups(datetime.now(UTC))
    health = service.store.record_source_health(datetime.now(UTC), health_by_source)
    change_totals = {
        state: sum(value == state for value in observed.values())
        for state in ("new", "changed", "unchanged", "applied_seen")
    }
    return {
        "searches": results,
        "reviewable_changes": {
            "new": change_totals["new"],
            "materially_changed": change_totals["changed"],
            "seen_unchanged": change_totals["unchanged"],
            "applied_seen": change_totals["applied_seen"],
            "note": (
                "Only new or materially changed listings need review; "
                "unchanged listings were still seen."
            ),
        },
        "source_health": health,
        "followups_due": due,
        "messages_sent": 0,
        "applications_submitted": 0,
    }


async def run(once: bool):
    store = Store(os.getenv("CAREER_DB_PATH", "data/career.sqlite3"))
    service = CareerService(store)
    while True:
        print(json.dumps(await run_once(service)), flush=True)
        if once:
            return
        await asyncio.sleep(max(21600, int(os.getenv("WATCH_INTERVAL_SECONDS", "21600"))))


def main():
    load_dotenv()
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
