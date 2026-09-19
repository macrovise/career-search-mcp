from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from jobsearch_mcp.models import Profile, Status
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store, canonical_url


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "jobs.db"))


def job(source="himalayas", source_id="a", **changes):
    fields = dict(
        source_id=source_id,
        title="Support Engineer",
        company="Acme",
        location="United Kingdom",
        remote_scope="uk",
        posted_at="2026-09-19T00:00:00Z",
        source_url=f"https://{source}.example/{source_id}",
        application_url="https://careers.example/job/123?utm_source=test",
        description="SQL API support",
        employment_type="permanent",
    )
    fields.update(changes)
    return make_job(source, fields)


def test_cross_source_dedup_provenance_and_preserved_lifecycle(store):
    first = store.upsert(job())
    store.update_status(first.id, Status.APPLIED, "user confirmed actual application")
    second = store.upsert(job("scout", "b", application_url="https://careers.example/job/123"))
    assert first.id == second.id
    assert second.status == Status.APPLIED
    assert {s.source for s in second.sources} == {"himalayas", "scout"}
    assert len(store.list_jobs()) == 1


def test_concurrent_ingestion_is_atomic(store):
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: store.upsert(job()).id, range(20)))
    assert len(set(ids)) == 1
    assert len(store.list_jobs()) == 1


def test_distinct_requisitions_same_source_never_merge_by_title(store):
    a = store.upsert(job(application_url=""))
    b = store.upsert(job(source_id="b", application_url=""))
    assert a.id != b.id


def test_exact_contextual_fingerprint_merges_cross_source(store):
    a = store.upsert(job(application_url=""))
    b = store.upsert(job("scout", "b", application_url=""))
    assert a.id == b.id


def test_source_precedence_salary_bundle_and_conflicts(store):
    store.upsert(
        job("adzuna", "1", salary_min=45000, salary_max=55000, currency="GBP", salary_period="year")
    )
    merged = store.upsert(
        job(
            "himalayas",
            "2",
            salary_min=60000,
            salary_max=80000,
            currency="USD",
            salary_period="year",
        )
    )
    assert merged.currency == "USD" and merged.salary_min == 60000
    assert any(c["field"] == "currency" for c in merged.conflicts)


def test_unknown_salary_does_not_erase_disclosed_salary(store):
    store.upsert(job("adzuna", "1", salary_min=45000, currency="GBP", salary_period="year"))
    merged = store.upsert(job("himalayas", "2"))
    assert merged.salary_min == 45000 and merged.currency == "GBP"


def test_followups_do_not_send_or_modify_terminal_states(store):
    a = store.upsert(job())
    due = datetime.now(UTC) - timedelta(days=1)
    store.update_status(a.id, Status.AWAITING_RESPONSE, "waiting", due)
    assert store.advance_followups(datetime.now(UTC)) == 1
    assert store.get(a.id).status == Status.FOLLOW_UP_DUE
    store.update_status(a.id, Status.REJECTED, "received rejection", due)
    assert store.advance_followups(datetime.now(UTC)) == 0
    assert len(store.history(a.id)) == 4


def test_profile_requires_evidence_and_persists(store):
    with pytest.raises(ValueError):
        store.save_profile(Profile(verified_skills=["SQL"]))
    profile = Profile(
        resume_text="Used SQL to investigate tickets",
        verified_skills=["SQL"],
        skill_evidence={"SQL": "Used SQL"},
    )
    store.save_profile(profile)
    assert Store(store.path).get_profile() == profile


def test_pagination_status_and_identity_url(store):
    store.upsert(job())
    assert store.list_jobs(Status.APPLIED) == []
    assert store.list_jobs(offset=1) == []
    assert (
        canonical_url("https://EXAMPLE.com/jobs/1?utm_source=x&gh_jid=23")
        == "https://example.com/jobs/1?gh_jid=23"
    )


def test_naive_followup_rejected(store):
    a = store.upsert(job())
    with pytest.raises(ValueError):
        store.update_status(a.id, Status.APPLIED, "test", datetime(2026, 9, 19))


def test_saved_search_filters_before_pagination_and_treats_sql_as_text(store):
    first = store.upsert(job(application_url=""))
    second = store.upsert(job(source_id="b", application_url=""))
    store.upsert(
        job(source_id="c", title="Designer", description="Visual design", application_url="")
    )
    store.update_status(first.id, Status.INTERESTING, "selected")
    matches = store.search_jobs("SUPPORT api", limit=1)
    assert len(matches) == 1
    next_page = store.search_jobs("support API", limit=1, offset=1)
    assert {matches[0].id, next_page[0].id} == {first.id, second.id}
    assert store.search_jobs("support", Status.INTERESTING)[0].id == first.id
    assert store.search_jobs("%") == []
    assert store.search_jobs("' OR 1=1 --") == []
