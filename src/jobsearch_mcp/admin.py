"""Trusted host-only writes for deployments whose ChatGPT connection is read-only.

Run as the service owner over authenticated SSH. Never expose this command as an
unauthenticated web endpoint or disguise it as a read-only MCP tool.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .models import ExternalJobEvidence, Profile, Status, Submission
from .reporting import portable_job
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "save-profile",
        "import-handoff",
        "import-applications",
        "import-application-review",
    ):
        command = commands.add_parser(name)
        command.add_argument("--file", required=True)
    status = commands.add_parser("update-status")
    status.add_argument("--job-id", required=True)
    status.add_argument("--status", choices=[s.value for s in Status], required=True)
    status.add_argument("--reason", required=True)
    applied = commands.add_parser("mark-as-applied")
    applied.add_argument("--job-id", required=True)
    applied.add_argument("--evidence", required=True)
    applied.add_argument("--submitted-at", help="ISO timestamp with timezone; omit if unknown")
    applied.add_argument("--confirmed", action="store_true", required=True)
    applied.add_argument(
        "--evidence-source",
        choices=["user_confirmation", "confirmation_record"],
        default="user_confirmation",
    )
    commands.add_parser("migrate-submissions")
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
    elif args.command == "mark-as-applied":
        confirmation = Submission(
            confirmed=args.confirmed,
            recorded_at=datetime.now(UTC),
            submitted_at=args.submitted_at,
            evidence=args.evidence,
            evidence_source=args.evidence_source,
        )
        job = store.mark_as_applied(args.job_id, confirmation)
        print(
            json.dumps(
                {
                    "persisted": True,
                    "job_id": job.id,
                    "status": job.status.value,
                    "submission": job.submission.model_dump(mode="json"),
                }
            )
        )
    elif args.command == "migrate-submissions":
        print(json.dumps({"migrated": store.migrate_submissions()}))
    elif args.command == "import-application-review":
        records = json.loads(Path(args.file).read_text())
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError("Expected at most 100 unlinked application records")
        print(
            json.dumps({"retained_for_identity_review": store.import_application_review(records)})
        )
    elif args.command == "import-applications":
        payload = json.loads(Path(args.file).read_text())
        records = payload.get("records", [])
        if (
            payload.get("schema_version") != 1
            or not isinstance(records, list)
            or len(records) > 100
        ):
            raise ValueError("Expected version 1 application records, at most 100")
        # Validate the complete batch before any write. Each imported vacancy is
        # idempotent; a failed later record can be retried without resetting stages.
        validated = []
        for record in records:
            if set(record) != {"evidence", "submission"}:
                raise ValueError("Each record requires exactly evidence and submission")
            evidence = ExternalJobEvidence.model_validate(record["evidence"])
            submission = Submission.model_validate(record["submission"])
            submission.recorded_at = datetime.now(UTC)
            validated.append((portable_job(evidence), submission))
        ids = []
        for vacancy, submission in validated:
            job = store.upsert(vacancy)
            ids.append(store.mark_as_applied(job.id, submission).id)
        print(json.dumps({"imported": len(set(ids)), "job_ids": sorted(set(ids))}))
    else:
        job = store.update_status(args.job_id, Status(args.status), args.reason)
        print(json.dumps({"updated": True, "job_id": job.id, "status": job.status.value}))


if __name__ == "__main__":
    main()
