from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client

from jobsearch_mcp.application_packs import ApplicationPackDraft
from jobsearch_mcp.models import Profile, ResumeVariant, Status
from jobsearch_mcp.server import create_server
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


def configured_store(tmp_path):
    store = Store(str(tmp_path / "jobs.db"))
    job = store.upsert(
        make_job(
            "adzuna",
            {
                "source_id": "role-1",
                "title": "Support Engineer",
                "company": "Acme",
                "source_url": "https://example.test/role-1",
                "description": "Investigate customer API and SQL issues.",
            },
        )
    )
    resume = "Resolved API and SQL issues for customers."
    store.save_profile(
        Profile(
            resume_text=resume,
            resume_variants={
                "support": ResumeVariant(
                    label="Support CV", source_filename="support.pdf", resume_text=resume
                )
            },
        )
    )
    return store, job


def draft(summary="Customer support specialist"):
    return ApplicationPackDraft(
        author="chatgpt",
        cv_variant="support",
        summary=summary,
        resume_bullets=["Resolved API and SQL issues for customers."],
        cover_letter="I am applying for the Support Engineer role.",
        screening_answers=[
            {"question": "Can you work in the UK?", "answer": None, "unresolved": True}
        ],
        unresolved_questions=["Confirm work authorization"],
        evidence_references=[
            {
                "kind": "profile",
                "reference": "resume_variants.support.resume_text",
                "excerpt": "Resolved API and SQL issues for customers.",
            }
        ],
    )


def test_pack_versions_conflicts_and_preserves_lifecycle(tmp_path):
    store, job = configured_store(tmp_path)
    first = store.save_application_pack(job.id, 0, draft())
    second = store.save_application_pack(job.id, 1, draft("Revised authored summary"))

    assert (first.revision, second.revision) == (1, 2)
    assert store.get_application_pack(job.id, 1).summary == "Customer support specialist"
    assert store.get_application_pack(job.id).summary == "Revised authored summary"
    assert store.get(job.id).status == Status.DISCOVERED
    assert store.get(job.id).submission is None
    with pytest.raises(ValueError, match="revision conflict"):
        store.save_application_pack(job.id, 1, draft("stale overwrite"))


def test_concurrent_agent_save_allows_only_one_revision(tmp_path):
    store, job = configured_store(tmp_path)

    def save(text):
        try:
            return store.save_application_pack(job.id, 0, draft(text)).revision
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(save, ["Agent one", "Agent two"]))
    assert outcomes.count(1) == 1
    assert sum("revision conflict" in str(value) for value in outcomes) == 1


def test_pack_requires_persisted_job_and_known_cv_variant(tmp_path):
    store, job = configured_store(tmp_path)
    with pytest.raises(ValueError, match="Unknown job ID"):
        store.save_application_pack("live:temporary", 0, draft())
    invalid = draft().model_copy(update={"cv_variant": "missing"})
    with pytest.raises(ValueError, match="Unknown CV variant"):
        store.save_application_pack(job.id, 0, invalid)


def test_pack_reports_job_and_profile_evidence_staleness(tmp_path):
    store, job = configured_store(tmp_path)
    store.save_application_pack(job.id, 0, draft())
    store.upsert(
        make_job(
            "adzuna",
            {
                "source_id": "role-1",
                "title": "Support Engineer",
                "company": "Acme",
                "source_url": "https://example.test/role-1",
                "description": "Updated role evidence with Python.",
            },
        )
    )
    profile = store.get_profile()
    profile.unresolved_questions.append("Confirm notice period")
    store.save_profile(profile)
    loaded = store.get_application_pack(job.id)
    assert loaded.job_evidence_stale is True
    assert loaded.profile_evidence_stale is False


def test_pack_ignores_refetch_telemetry_and_unrelated_cv_variant(tmp_path):
    store, job = configured_store(tmp_path)
    stored = store.get(job.id)
    stored.skills = ["api", "sql"]
    with store.connection() as db:
        db.execute("UPDATE jobs SET data=? WHERE id=?", (stored.model_dump_json(), stored.id))
    store.save_application_pack(job.id, 0, draft())
    refreshed = make_job(
        "adzuna",
        {
            "source_id": "role-1",
            "title": "Support Engineer",
            "company": "Acme",
            "source_url": "https://example.test/role-1?utm_source=refetch",
            "description": "Investigate customer API and SQL issues.",
            "skills": ["SQL", "API"],
        },
    )
    store.upsert(refreshed)
    profile = store.get_profile()
    profile.resume_text += "\nUnrelated sales CV text."
    profile.resume_variants["sales"] = ResumeVariant(
        label="Sales CV", source_filename="sales.pdf", resume_text="Unrelated sales CV text."
    )
    store.save_profile(profile)
    loaded = store.get_application_pack(job.id)
    assert loaded.job_evidence_stale is False
    assert loaded.profile_evidence_stale is False
    profile.country = "United Kingdom"
    store.save_profile(profile)
    assert store.get_application_pack(job.id).profile_evidence_stale is True


async def test_mcp_pack_round_trip_and_tracker_revision(tmp_path):
    store, job = configured_store(tmp_path)
    async with Client(create_server(store, local_test=True)) as client:
        saved = await client.call_tool(
            "save_application_pack",
            {"job_id": job.id, "expected_revision": 0, "pack": draft().model_dump()},
        )
        assert saved.data["pack"]["revision"] == 1
        assert saved.data["application_submitted"] is False
        read = await client.call_tool("get_application_pack", {"job_id": job.id})
        assert read.data["pack"]["summary"] == "Customer support specialist"
        tracker = await client.call_tool("show_application_tracker", {"job_ids": [job.id]})
        assert tracker.data["jobs"][0]["application_pack_revision"] == 1


async def test_read_only_removes_pack_write_but_keeps_read(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "true")
    store, job = configured_store(tmp_path)
    store.save_application_pack(job.id, 0, draft())
    async with Client(create_server(store, local_test=True)) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert "get_application_pack" in tools
        assert "save_application_pack" not in tools
        rejected = await client.call_tool(
            "save_application_pack",
            {"job_id": job.id, "expected_revision": 1, "pack": draft().model_dump()},
            raise_on_error=False,
        )
        assert rejected.is_error


def test_watch_observations_persist_only_material_changes(tmp_path):
    store, job = configured_store(tmp_path)
    at = datetime(2026, 9, 20, 10, tzinfo=UTC)
    assert store.record_watch_observation(job.id, "hash-1", at)["state"] == "new"
    assert store.record_watch_observation(job.id, "hash-1", at + timedelta(hours=1))["state"] == (
        "unchanged"
    )
    changed = store.record_watch_observation(job.id, "hash-2", at + timedelta(hours=2))
    assert changed["state"] == "changed"
    assert changed["previous_hash"] == "hash-1"
    events = Store(store.path).list_watch_changes(at - timedelta(seconds=1), 10)
    assert [event["state"] for event in events] == ["new", "changed"]
    assert all(event["job_id"] == job.id for event in events)
    assert events[-1]["title"] == "Support Engineer"


def test_direct_employer_evidence_precedes_newer_aggregator_salary(tmp_path):
    store = Store(str(tmp_path / "jobs.db"))
    employer = make_job(
        "employer_ats",
        {
            "source_id": "ats-1",
            "title": "Support Engineer",
            "company": "Acme",
            "location": "UK",
            "posted_at": "2026-09-20T00:00:00Z",
            "employment_type": "permanent",
            "source_url": "https://jobs.ashbyhq.com/acme/role",
            "salary_min": 50000,
            "salary_max": 60000,
            "currency": "GBP",
            "salary_period": "year",
        },
    )
    employer.sources[0].retrieval_method = "DIRECT_SITE_OR_ATS"
    employer.sources[0].fetched_at = datetime(2026, 9, 20, 9, tzinfo=UTC)
    store.upsert(employer)
    aggregator = make_job(
        "adzuna",
        {
            "source_id": "aggregate-1",
            "title": "Support Engineer",
            "company": "Acme",
            "location": "UK",
            "posted_at": "2026-09-20T00:00:00Z",
            "employment_type": "permanent",
            "source_url": "https://adzuna.example/aggregate-1",
            "application_url": "https://jobs.ashbyhq.com/acme/role",
            "salary_min": 90000,
            "salary_max": 100000,
            "currency": "USD",
            "salary_period": "year",
        },
    )
    aggregator.sources[0].fetched_at = datetime(2026, 9, 20, 12, tzinfo=UTC)
    merged = store.upsert(aggregator)
    assert (merged.salary_min, merged.salary_max, merged.currency) == (50000, 60000, "GBP")


def test_older_same_source_snapshot_cannot_replace_newer_evidence(tmp_path):
    store = Store(str(tmp_path / "jobs.db"))
    newer = make_job(
        "employer_ats",
        {
            "source_id": "ats-1",
            "title": "Support Engineer",
            "source_url": "https://jobs.ashbyhq.com/acme/role",
            "description": "Current employer description",
        },
    )
    newer.sources[0].retrieval_method = "DIRECT_SITE_OR_ATS"
    newer.sources[0].fetched_at = datetime(2026, 9, 20, 12, tzinfo=UTC)
    store.upsert(newer)
    older = make_job(
        "employer_ats",
        {
            "source_id": "ats-1",
            "title": "Support Engineer",
            "source_url": "https://jobs.ashbyhq.com/acme/role",
            "description": "Stale employer description",
        },
    )
    older.sources[0].retrieval_method = "DIRECT_SITE_OR_ATS"
    older.sources[0].fetched_at = datetime(2026, 9, 20, 8, tzinfo=UTC)
    assert store.upsert(older).description == "Current employer description"
