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
    for role in service.store.get_profile().preferences.target_roles:
        result = await service.discover(role)
        results.append(
            {
                "query": role,
                "accepted": len(result["jobs"]),
                "excluded": len(result["excluded_jobs"]),
                "sources": result["source_status"],
            }
        )
    due = service.store.advance_followups(datetime.now(UTC))
    return {
        "searches": results,
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
