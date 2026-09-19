"""Trusted host-only writes for deployments whose ChatGPT connection is read-only.

Run as the service owner over authenticated SSH. Never expose this command as an
unauthenticated web endpoint or disguise it as a read-only MCP tool.
"""

import argparse
import json
import os
from pathlib import Path

from .models import ExternalJobEvidence, Profile, Status
from .reporting import portable_job
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("save-profile", "import-handoff"):
        command = commands.add_parser(name)
        command.add_argument("--file", required=True)
    status = commands.add_parser("update-status")
    status.add_argument("--job-id", required=True)
    status.add_argument("--status", choices=[s.value for s in Status], required=True)
    status.add_argument("--reason", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    store = Store(args.database)
    if args.command == "save-profile":
        profile = Profile.model_validate_json(Path(args.file).read_text())
        store.save_profile(profile)
        print(json.dumps({"saved": True, "variants": len(profile.resume_variants)}))
    elif args.command == "import-handoff":
        payload = json.loads(Path(args.file).read_text())
        if payload.get("schema_version") != 1 or not 1 <= len(payload.get("records", [])) <= 100:
            raise ValueError("Expected a version 1 handoff with 1-100 source records")
        # Validate every record before writing. Each upsert is independently atomic;
        # retries are safe and cannot reset an existing application's lifecycle.
        jobs = [portable_job(ExternalJobEvidence.model_validate(row)) for row in payload["records"]]
        ids = sorted({store.upsert(job).id for job in jobs})
        print(json.dumps({"persisted": True, "job_ids": ids, "application_submitted": False}))
    else:
        job = store.update_status(args.job_id, Status(args.status), args.reason)
        print(json.dumps({"updated": True, "job_id": job.id, "status": job.status.value}))


if __name__ == "__main__":
    main()
