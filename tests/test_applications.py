"""Regression coverage for explicit submissions and the shared application register."""

import json
from datetime import UTC, datetime

import pytest
from fastmcp import Client
from pydantic import ValidationError

from jobsearch_mcp import service as service_module
from jobsearch_mcp.applications import application_tracking
from jobsearch_mcp.models import Profile, Status, Submission
from jobsearch_mcp.reasoning import score_fit
from jobsearch_mcp.server import create_server
from jobsearch_mcp.service import CareerService
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store, canonical_url


def job(source="himalayas", source_id="req-123", **changes):
    fields = {
        "source_id": source_id,
        "title": "Support Engineer",
        "company": "Acme",
        "location": "United Kingdom",
        "remote_scope": "uk",
        "posted_at": "2026-09-19T00:00:00Z",
        "source_url": f"https://{source}.example/jobs/{source_id}",
        "application_url": "https://careers.example/jobs/req-123?utm_source=directory",
        "description": "Support customers with SQL and APIs.",
        "employment_type": "permanent",
    }
    fields.update(changes)
    return make_job(source, fields)


def submission(evidence="User confirmed submitting the application", *, minute=0):
    return Submission(
        confirmed=True,
        submitted_at=datetime(2026, 9, 19, 12, minute, tzinfo=UTC),
        recorded_at=datetime(2026, 9, 19, 12, minute, tzinfo=UTC),
        evidence=evidence,
        evidence_source="user_confirmation",
    )


def test_submission_requires_explicit_confirmation_and_evidence():
    valid = submission().model_dump(mode="python")
    assert Submission.model_validate(valid).confirmed is True

    invalid_payloads = [
        {**valid, "confirmed": False},
        {**valid, "evidence": ""},
        {key: value for key, value in valid.items() if key != "confirmed"},
        {
            **valid,
            "recorded_at": datetime(2026, 9, 19, 12),
        },
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            Submission.model_validate(payload)


def test_marking_twice_preserves_first_confirmation_and_history(tmp_path):
    store = Store(str(tmp_path / "career.sqlite3"))
    saved = store.upsert(job())

    first = store.mark_as_applied(saved.id, submission())
    first_history = store.history(saved.id)
    repeated = store.mark_as_applied(saved.id, submission("Different retry evidence", minute=5))

    assert first.status == repeated.status == Status.APPLIED
    assert repeated.submission.evidence == "User confirmed submitting the application"
    assert store.history(saved.id) == first_history
    assert [event["new_status"] for event in first_history] == ["discovered", "applied"]


def test_cross_source_rediscovery_by_application_url_retains_submission(tmp_path):
    store = Store(str(tmp_path / "career.sqlite3"))
    saved = store.upsert(job())
    store.mark_as_applied(saved.id, submission())

    rediscovered = store.upsert(
        job(
            "scout",
            "external-456",
            application_url="https://careers.example/jobs/req-123",
        )
    )

    assert rediscovered.id == saved.id
    assert {source.source for source in rediscovered.sources} == {"himalayas", "scout"}
    assert rediscovered.submission.evidence == "User confirmed submitting the application"
    tracking = score_fit(rediscovered, Profile())["application_tracking"]
    assert tracking["submission_status"] == "submitted"
    assert tracking["exclude_from_discovery"] is True


def test_ashby_application_url_matches_listing_but_keeps_distinct_requisitions():
    listing = canonical_url("https://jobs.ashbyhq.com/acme/11111111-1111-4111-8111-111111111111")
    apply_page = canonical_url(
        "https://jobs.ashbyhq.com/acme/11111111-1111-4111-8111-111111111111/application"
    )
    other_requisition = canonical_url(
        "https://jobs.ashbyhq.com/acme/22222222-2222-4222-8222-222222222222/application"
    )

    assert apply_page == listing
    assert other_requisition != listing


async def test_unlinked_same_company_history_warns_without_excluding_role(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    store = Store(str(tmp_path / "unlinked-review.sqlite3"))
    unlinked_record = {
        "company": "Acme",
        "evidence_of_actual_submission": "Confirmed in the prior application library",
        "source": "application_library",
    }
    assert store.import_application_review([unlinked_record]) == 1

    async def remotive(query):
        return [
            job(
                "remotive",
                "new-requisition",
                source_url="https://remotive.example/jobs/new-requisition",
                application_url="https://careers.example/jobs/new-requisition",
            )
        ]

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    result = await CareerService(store).search_live("Support Engineer")

    assert len(result["jobs"]) == 1
    assert result["excluded_jobs"] == []
    tracking = result["jobs"][0]["application_tracking"]
    assert tracking["exclude_from_discovery"] is False
    assert tracking["unresolved_same_company_records"] == [unlinked_record]
    assert (
        "Prior application at this company needs exact requisition reconciliation"
        in result["jobs"][0]["match_evidence"]["concerns"]
    )


def test_different_requisition_for_same_employer_remains_unknown(tmp_path):
    store = Store(str(tmp_path / "career.sqlite3"))
    submitted = store.upsert(job())
    store.mark_as_applied(submitted.id, submission())

    separate = store.upsert(
        job(
            "himalayas",
            "req-456",
            source_url="https://himalayas.example/jobs/req-456",
            application_url="https://careers.example/jobs/req-456",
        )
    )

    assert separate.id != submitted.id
    assert separate.submission is None
    tracking = score_fit(separate, Profile())["application_tracking"]
    assert tracking["submission_status"] == "unknown"
    assert tracking["exclude_from_discovery"] is False


@pytest.mark.parametrize("later_status", [Status.REVIEW, Status.CLOSED])
def test_later_review_or_closed_status_keeps_submission_excluded(tmp_path, later_status):
    store = Store(str(tmp_path / f"{later_status.value}.sqlite3"))
    saved = store.upsert(job())
    store.mark_as_applied(saved.id, submission())

    updated = store.update_status(saved.id, later_status, "User reviewed the application")
    fit = score_fit(updated, Profile())

    assert updated.status == later_status
    assert updated.submission.confirmed is True
    assert fit["application_tracking"]["submission_status"] == "submitted"
    assert fit["application_tracking"]["exclude_from_discovery"] is True
    assert "Application already submitted; tracking only" in fit["exclusions"]


@pytest.mark.parametrize("status", [Status.DISCOVERED, Status.APPLICATION_PREPARED])
def test_seen_or_prepared_without_confirmation_stays_unknown(tmp_path, status):
    store = Store(str(tmp_path / f"{status.value}.sqlite3"))
    saved = store.upsert(job())
    if status != Status.DISCOVERED:
        saved = store.update_status(saved.id, status, "Prepared materials for review")

    tracking = application_tracking(saved)
    assert saved.submission is None
    assert tracking["submission_status"] == "unknown"
    assert tracking["exclude_from_discovery"] is False
    assert (
        "Application already submitted; tracking only"
        not in score_fit(saved, Profile())["exclusions"]
    )


def test_legacy_applied_then_rejected_migration_is_idempotent(tmp_path):
    store = Store(str(tmp_path / "legacy.sqlite3"))
    saved = store.upsert(job())
    applied_at = "2026-09-19T12:00:00+00:00"
    rejected_at = "2026-09-20T12:00:00+00:00"

    # Recreate the old shape: a rejected job with lifecycle events and no submission field.
    with store.connection() as db:
        row = db.execute("SELECT data FROM jobs WHERE id=?", (saved.id,)).fetchone()
        legacy_data = json.loads(row[0])
        legacy_data["status"] = Status.REJECTED.value
        legacy_data.pop("submission", None)
        db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(legacy_data), saved.id))
        db.executemany(
            """
            INSERT INTO events(job_id,at,old_status,new_status,reason)
            VALUES(?,?,?,?,?)
            """,
            [
                (saved.id, applied_at, "discovered", "applied", "User submitted application"),
                (saved.id, rejected_at, "applied", "rejected", "Employer sent rejection"),
            ],
        )

    history_before = store.history(saved.id)
    assert store.migrate_submissions() == 1
    migrated = store.get(saved.id)
    first_submission = migrated.submission.model_dump(mode="json")

    assert migrated.status == Status.REJECTED
    assert migrated.submission.confirmed is True
    assert migrated.submission.submitted_at is None
    assert migrated.submission.evidence_source == "legacy_application_state"
    assert "User submitted application" in migrated.submission.evidence
    assert store.history(saved.id) == history_before
    assert store.migrate_submissions() == 0
    assert store.get(saved.id).submission.model_dump(mode="json") == first_submission
    assert store.history(saved.id) == history_before


async def test_mcp_application_write_requires_confirmation(tmp_path):
    store = Store(str(tmp_path / "mcp.sqlite3"))
    saved = store.upsert(job())
    original_history = store.history(saved.id)
    confirmation = submission().model_dump(mode="json")

    async with Client(create_server(store, local_test=True)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "mark_as_applied" in tools
        assert tools["mark_as_applied"].annotations.readOnlyHint is False

        invalid = await client.call_tool(
            "mark_as_applied",
            {"job_id": saved.id, "confirmation": {**confirmation, "confirmed": False}},
            raise_on_error=False,
        )
        assert invalid.is_error
        assert store.get(saved.id).submission is None
        assert store.history(saved.id) == original_history

        accepted = await client.call_tool(
            "mark_as_applied",
            {"job_id": saved.id, "confirmation": confirmation},
        )

    assert accepted.data["submission"]["confirmed"] is True
    assert accepted.data["submission"]["evidence"] == confirmation["evidence"]
    assert store.get(saved.id).status == Status.APPLIED
