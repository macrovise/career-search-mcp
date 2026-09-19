"""Regression coverage for uncached, non-persisting live search."""

import time

import pytest
from fastmcp import Client

from jobsearch_mcp import service as service_module
from jobsearch_mcp.models import Job, Status
from jobsearch_mcp.server import create_server
from jobsearch_mcp.service import CareerService
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


def _job(
    source: str,
    source_id: str,
    *,
    application_url: str | None = None,
    employment_type: str = "permanent",
    salary_min: float | None = None,
    salary_max: float | None = None,
) -> Job:
    """Build consistent, fully remote support listings for adapter test doubles."""
    return make_job(
        source,
        {
            "source_id": source_id,
            "title": "Support Engineer",
            "company": "Example Co",
            "location": "UK remote",
            "remote_scope": "uk",
            "employment_type": employment_type,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": "GBP" if salary_min is not None or salary_max is not None else None,
            "salary_period": "year" if salary_min is not None or salary_max is not None else None,
            "source_url": f"https://{source}.example.test/jobs/{source_id}",
            "application_url": application_url
            or f"https://apply.example.test/{source}/{source_id}",
            "description": "Support Engineer helping customers with SQL and APIs.",
        },
    )


async def test_search_live_bypasses_cache_redacts_failures_and_does_not_write(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CAREER_SOURCES", "remotive,adzuna")
    store = Store(str(tmp_path / "career.sqlite3"))

    saved = store.upsert(_job("remotive", "already-saved", salary_min=50_000))
    store.update_status(saved.id, Status.APPLIED, "existing application")

    stale_remotive = _job("remotive", "stale-remotive")
    stale_adzuna = _job("adzuna", "stale-adzuna")
    store.cache_set("remotive:", [stale_remotive.model_dump(mode="json")], time.time() + 3600)
    store.cache_set(
        "adzuna:support engineer", [stale_adzuna.model_dump(mode="json")], time.time() + 3600
    )
    with store.connection() as db:
        before = list(db.iterdump())

    calls = []

    async def remotive(query):
        calls.append(("remotive", query))
        return [
            _job("remotive", "live-undisclosed"),
            _job("remotive", "live-contract", employment_type="contract", salary_min=60_000),
        ]

    async def adzuna(query):
        calls.append(("adzuna", query))
        raise RuntimeError("api_key=must-not-appear")

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    monkeypatch.setitem(service_module.ADAPTERS, "adzuna", adzuna)

    result = await CareerService(store).search_live("Support Engineer")

    assert {name for name, _ in calls} == {"remotive", "adzuna"}
    assert len(calls) == 2
    assert result["persisted"] is False
    assert result["application_submitted"] is False
    assert result["limit"] == 25
    assert result["returned_count"] == 2
    assert result["total_count"] == 2
    assert result["truncated"] is False

    source_status = result["source_status"]
    assert source_status["remotive"]["status"] == "ok"
    assert source_status["remotive"]["count"] == 2
    assert source_status["adzuna"]["status"] == "error"
    assert source_status["adzuna"]["count"] == 0
    for report in source_status.values():
        assert report["cached"] is False
        assert "fetched_at" in report
        assert "error_type" in report
    assert source_status["adzuna"]["error_type"] == "RuntimeError"
    assert source_status["adzuna"]["fetched_at"] is None
    assert source_status["remotive"]["fetched_at"]
    assert "must-not-appear" not in str(result)
    assert "stale-" not in str(result)

    undisclosed = result["jobs"][0]
    assert undisclosed["id"].startswith("live:")
    assert undisclosed["match_evidence"]["recommendation"] == "review"
    assert any(
        "Salary undisclosed" in concern for concern in undisclosed["match_evidence"]["concerns"]
    )
    contract = result["excluded_jobs"][0]
    assert contract["employment_type"] == "contract"
    assert any(
        "Excluded employment type" in reason for reason in contract["match_evidence"]["exclusions"]
    )

    with store.connection() as db:
        assert list(db.iterdump()) == before
    assert store.get(saved.id).status == Status.APPLIED
    assert len(store.history(saved.id)) == 2


async def test_search_live_deduplicates_application_url_and_keeps_source_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CAREER_SOURCES", "himalayas,remotive")
    application_url = "https://apply.example.test/support-role"
    calls = []

    async def himalayas(query):
        calls.append("himalayas")
        return [_job("himalayas", "himalayas-42", application_url=application_url)]

    async def remotive(query):
        calls.append("remotive")
        return [_job("remotive", "remotive-84", application_url=application_url)]

    monkeypatch.setitem(service_module.ADAPTERS, "himalayas", himalayas)
    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    store = Store(str(tmp_path / "career.sqlite3"))

    result = await CareerService(store).search_live("Support Engineer")

    assert sorted(calls) == ["himalayas", "remotive"]
    assert result["total_count"] == 1
    assert result["returned_count"] == 1
    assert len(result["jobs"]) == 1
    evidence = result["jobs"][0]["sources"]
    assert {source["source"] for source in evidence} == {"himalayas", "remotive"}
    assert {source["source_id"] for source in evidence} == {"himalayas-42", "remotive-84"}


async def test_search_live_applies_limit_and_reports_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SOURCES", "remotive")

    async def remotive(query):
        return [_job("remotive", f"support-{index}") for index in range(3)]

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    result = await CareerService(Store(str(tmp_path / "career.sqlite3"))).search_live(
        "Support Engineer", limit=2
    )

    assert result["limit"] == 2
    assert result["returned_count"] == 2
    assert result["total_count"] == 3
    assert result["truncated"] is True
    assert len(result["jobs"]) + len(result["excluded_jobs"]) == 2


async def test_search_live_rejects_sources_not_enabled_by_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    calls = []

    async def adzuna(query):
        calls.append(query)
        return []

    monkeypatch.setitem(service_module.ADAPTERS, "adzuna", adzuna)
    service = CareerService(Store(str(tmp_path / "career.sqlite3")))

    with pytest.raises(ValueError):
        await service.search_live("Support Engineer", ["adzuna"])
    assert calls == []


async def test_live_mcp_followups_work_in_read_only_mode_without_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "true")
    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    store = Store(str(tmp_path / "career.sqlite3"))
    saved = store.upsert(_job("remotive", "saved", salary_min=50_000))
    store.update_status(saved.id, Status.APPLIED, "existing application")
    with store.connection() as db:
        before = list(db.iterdump())

    async def remotive(query):
        return [_job("remotive", "live-followup")]

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)

    async with Client(create_server(store, local_test=True)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert len(tools) == 10
        assert "search_live_jobs" in tools
        assert tools["search_live_jobs"].annotations.readOnlyHint is True
        assert tools["search_live_jobs"].annotations.openWorldHint is True
        assert all(tool.annotations.readOnlyHint for tool in tools.values())
        assert not {"search_jobs", "save_profile", "update_status"} & tools.keys()

        search = await client.call_tool("search_live_jobs", {"query": "Support Engineer"})
        assert not search.is_error
        live_id = search.data["jobs"][0]["id"]
        assert live_id.startswith("live:")
        assert search.data["persisted"] is False
        assert search.data["application_submitted"] is False

        detail = await client.call_tool("get_job_detail", {"job_id": live_id})
        fit = await client.call_tool("score_fit", {"job_id": live_id})
        tailored = await client.call_tool("tailor_resume", {"job_id": live_id})
        letter = await client.call_tool("cover_letter_brief", {"job_id": live_id})
        assert all(not result.is_error for result in [detail, fit, tailored, letter])
        assert detail.data["id"] == live_id
        assert fit.data["job_id"] == live_id
        assert tailored.data["job"]["id"] == live_id
        assert letter.data["job"]["id"] == live_id

        for name, arguments in {
            "search_jobs": {"query": "Support Engineer"},
            "save_profile": {"profile": {}},
            "update_status": {"job_id": live_id, "status": "applied", "reason": "test"},
        }.items():
            unavailable = await client.call_tool(name, arguments, raise_on_error=False)
            assert unavailable.is_error

    with store.connection() as db:
        assert list(db.iterdump()) == before
    assert store.get(saved.id).status == Status.APPLIED
    assert len(store.history(saved.id)) == 2


async def test_live_match_preserves_saved_lifecycle_but_uses_fresh_content(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    store = Store(str(tmp_path / "db"))
    saved = store.upsert(_job("remotive", "same-job", salary_min=45000))
    store.update_status(saved.id, Status.INTERVIEW, "Invited to interview")
    with store.connection() as db:
        before = list(db.iterdump())

    async def remotive(query):
        return [_job("remotive", "same-job", salary_min=55000)]

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    service = CareerService(store)
    result = await service.search_live("Support Engineer")
    live = result["jobs"][0]
    assert live["saved_job_id"] == saved.id
    assert live["status"] == "interview"
    assert live["salary_min"] == 55000
    assert service.get_job(live["id"]).salary_min == 55000
    assert service.get_history(live["id"])[-1]["new_status"] == "interview"
    with store.connection() as db:
        assert list(db.iterdump()) == before
    assert store.get(saved.id).salary_min == 45000


async def test_every_live_request_fetches_again_and_old_references_keep_their_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    calls = []

    async def remotive(query):
        calls.append(query)
        return [_job("remotive", "changing-job", salary_min=45000 + 1000 * len(calls))]

    monkeypatch.setitem(service_module.ADAPTERS, "remotive", remotive)
    service = CareerService(Store(str(tmp_path / "db")))
    first = (await service.search_live("Support Engineer"))["jobs"][0]
    second = (await service.search_live("Support Engineer"))["jobs"][0]
    assert len(calls) == 2
    assert first["id"] != second["id"]
    assert service.get_job(first["id"]).salary_min == 46000
    assert service.get_job(second["id"]).salary_min == 47000
