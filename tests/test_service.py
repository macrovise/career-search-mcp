import pytest

from jobsearch_mcp.models import Status
from jobsearch_mcp.service import CareerService
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


async def test_feed_cached_across_queries_and_evidence_persisted(tmp_path, monkeypatch):
    calls = []

    async def feed(query):
        calls.append(query)
        return [
            make_job(
                "remotive",
                dict(title="Technical Support Engineer", source_url="https://example.com/1"),
            )
        ]

    monkeypatch.setitem(
        __import__("jobsearch_mcp.service", fromlist=["ADAPTERS"]).ADAPTERS, "remotive", feed
    )
    service = CareerService(Store(str(tmp_path / "db")))
    a = await service.discover("Support Engineer", ["remotive"])
    b = await service.discover("Technical Support", ["remotive"])
    assert calls == [""]
    assert b["source_status"]["remotive"]["cached"]
    record = service.store.get(a["jobs"][0]["id"])
    assert record.match_evidence["reasoning_owner"] == "ChatGPT"
    assert record.status == Status.DISCOVERED


async def test_failure_is_explicit_not_empty_success(tmp_path, monkeypatch):
    async def failure(query):
        raise RuntimeError("app_key=do-not-leak")

    monkeypatch.setitem(
        __import__("jobsearch_mcp.service", fromlist=["ADAPTERS"]).ADAPTERS, "adzuna", failure
    )
    result = await CareerService(Store(str(tmp_path / "db"))).discover("support", ["adzuna"])
    assert result["source_status"]["adzuna"]["status"] == "error"
    assert "do-not-leak" not in str(result)


async def test_unknown_source_rejected_before_network(tmp_path):
    with pytest.raises(ValueError):
        await CareerService(Store(str(tmp_path / "db"))).discover("support", ["scraper"])
