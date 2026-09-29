from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from jobsearch_mcp import live as live_module
from jobsearch_mcp.live import JobBatch, LiveResults
from jobsearch_mcp.sources.normalize import make_job


def sample(source_id):
    return make_job(
        "remotive",
        {
            "title": "Support Engineer",
            "company": "Acme",
            "location": "United Kingdom",
            "employment_type": "permanent",
            "posted_at": datetime(2026, 9, 19, tzinfo=UTC),
            "source_url": f"https://example.com/{source_id}",
            "source_id": source_id,
        },
    )


def test_batch_does_not_collapse_distinct_requisitions_with_identical_titles():
    batch = JobBatch()
    batch.add(sample("first"))
    batch.add(sample("second"))
    assert len(batch.jobs) == 2


def test_batch_rejects_ambiguous_alias_without_changing_existing_jobs():
    batch = JobBatch()
    batch.add(sample("first"))
    batch.add(sample("second"))
    ambiguous = sample("second")
    ambiguous.source_url = "https://example.com/first"
    before = {key: job.model_dump_json() for key, job in batch.jobs.items()}
    with pytest.raises(ValueError, match="Ambiguous"):
        batch.add(ambiguous)
    assert {key: job.model_dump_json() for key, job in batch.jobs.items()} == before


def test_live_results_expire_evict_and_are_isolated_from_callers(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(live_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    results = LiveResults()
    results.MAX_JOBS = 2
    first = results.add(sample("first"))
    second = results.add(sample("second"), saved_job_id="stored-id")
    second.title = "Caller changed its copy"
    resolved, saved_id = results.resolve(second.id)
    assert resolved.title == "Support Engineer"
    assert saved_id == "stored-id"
    results.add(sample("third"))
    with pytest.raises(ValueError, match="run search_live_jobs again"):
        results.resolve(first.id)
    now[0] += results.TTL_SECONDS
    with pytest.raises(ValueError, match="run search_live_jobs again"):
        results.resolve(second.id)
    assert not results._jobs
