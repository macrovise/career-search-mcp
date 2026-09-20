import json
from datetime import UTC, datetime

import httpx
import pytest
from fastmcp import Client

from jobsearch_mcp import employer
from jobsearch_mcp.server import create_server
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


def receipt():
    return {
        "http_code": 200,
        "fetched_at": "2026-09-20T12:00:00+00:00",
        "outcome": "SUCCESS",
        "timestamp_basis": "caller_observed_response_completion",
    }


def stub_fetch(monkeypatch, payload):
    calls = []

    async def fetch(url, params=None):
        calls.append((url, params))
        return json.dumps(payload).encode(), receipt()

    monkeypatch.setattr(employer, "fetch_with_receipt", fetch)
    monkeypatch.setattr(employer, "_validate_url", lambda _: None)
    return calls


async def test_unsupported_or_ssrf_style_url_never_fetches(monkeypatch):
    calls = stub_fetch(monkeypatch, {})
    for url in [
        "http://jobs.lever.co/acme/abc",
        "https://127.0.0.1/acme/abc",
        "https://jobs.lever.co/acme/abc?redirect=https://127.0.0.1",
        "https://jobs.lever.co@127.0.0.1/acme/abc",
        "https://example.com/acme/abc",
    ]:
        with pytest.raises(ValueError):
            await employer.verify_employer_evidence(url)
    assert calls == []


async def test_lever_exact_record_and_salary_bundle(monkeypatch):
    job_id = "12345678-1234-1234-1234-123456789abc"
    calls = stub_fetch(
        monkeypatch,
        {
            "id": job_id,
            "text": "Support Engineer",
            "categories": {"location": "Remote UK", "commitment": "Full-time"},
            "descriptionPlain": "Support customer APIs.",
            "lists": [{"content": "Use SQL to investigate issues."}],
            "additionalPlain": "No agency applications.",
            "workplaceType": "remote",
            "applyUrl": f"https://jobs.lever.co/acme/{job_id}/apply",
            "salaryRange": {"min": 50000, "max": 60000, "currency": "GBP", "interval": "year"},
        },
    )
    result = await employer.verify_employer_evidence(f"https://jobs.lever.co/acme/{job_id}")
    assert calls == [(f"https://api.lever.co/v0/postings/acme/{job_id}", None)]
    assert result["status"] == "SUCCESS"
    evidence = result["evidence"]
    assert evidence["retrieval_method"] == "DIRECT_SITE_OR_ATS"
    assert (evidence["salary_min"], evidence["salary_max"], evidence["currency"]) == (
        50000.0,
        60000.0,
        "GBP",
    )
    assert "Use SQL" in evidence["description"]


async def test_ashby_selects_exact_job_and_only_unambiguous_salary(monkeypatch):
    job_id = "12345678-1234-1234-1234-123456789abc"
    calls = stub_fetch(
        monkeypatch,
        {
            "jobs": [
                {
                    "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
                    "title": "Technical Support Engineer",
                    "location": "London",
                    "descriptionPlain": "Support APIs",
                    "isRemote": False,
                    "workplaceType": "Hybrid",
                    "employmentType": "Full-time",
                    "publishedAt": "2026-09-19T10:00:00Z",
                    "applyUrl": f"https://jobs.ashbyhq.com/acme/{job_id}/application",
                    "compensation": {
                        "summaryComponents": [
                            {
                                "compensationType": "Salary",
                                "minValue": 45000,
                                "maxValue": 55000,
                                "currencyCode": "GBP",
                                "interval": "year",
                                "summary": "£45k-£55k",
                            }
                        ]
                    },
                }
            ]
        },
    )
    result = await employer.verify_employer_evidence(
        f"https://jobs.ashbyhq.com/acme/{job_id}/application"
    )
    assert calls == [
        ("https://api.ashbyhq.com/posting-api/job-board/acme", {"includeCompensation": "true"})
    ]
    assert result["evidence"]["salary_min"] == 45000.0
    assert result["evidence"]["posted_at"] == "2026-09-19T10:00:00Z"


async def test_greenhouse_uses_exact_numeric_record_without_inventing_posted_date(monkeypatch):
    calls = stub_fetch(
        monkeypatch,
        {
            "id": 42,
            "title": "Customer Engineer",
            "content": "<p>Help customers with APIs.</p>",
            "location": {"name": "Remote"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/42",
            "updated_at": "2026-09-20T10:00:00Z",
        },
    )
    result = await employer.verify_employer_evidence(
        "https://job-boards.greenhouse.io/acme/jobs/42"
    )
    assert calls == [("https://boards-api.greenhouse.io/v1/boards/acme/jobs/42", None)]
    assert result["evidence"]["posted_at"] is None
    assert result["evidence"]["description"] == "Help customers with APIs."


async def test_not_found_is_not_reported_as_closed(monkeypatch):
    job_id = "12345678-1234-1234-1234-123456789abc"
    request = httpx.Request("GET", f"https://api.lever.co/v0/postings/acme/{job_id}")
    response = httpx.Response(404, request=request)

    async def missing(url, params=None):
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(employer, "fetch_with_receipt", missing)
    result = await employer.verify_employer_evidence(f"https://jobs.lever.co/acme/{job_id}")
    assert result["status"] == "NOT_FOUND"
    assert "closed" in result["note"]
    assert result["evidence"] is None


async def test_mcp_employer_verification_and_discovery_reads(tmp_path, monkeypatch):
    job_id = "12345678-1234-1234-1234-123456789abc"
    store = Store(str(tmp_path / "jobs.db"))
    saved = store.upsert(
        make_job(
            "adzuna",
            {
                "source_id": "a",
                "title": "Support Engineer",
                "source_url": f"https://jobs.lever.co/acme/{job_id}",
            },
        )
    )
    store.record_watch_observation(saved.id, "hash", datetime(2026, 9, 20, tzinfo=UTC))
    store.record_source_health(
        datetime(2026, 9, 20, tzinfo=UTC),
        {
            "adzuna": {
                "execution": "success",
                "count": 1,
                "retrieved_count": 1,
                "query_filtered_count": 0,
                "cached": False,
                "fetched_at": "2026-09-20T00:00:00Z",
                "http": [
                    {
                        "http_code": 200,
                        "outcome": "SUCCESS",
                        "fetched_at": "2026-09-20T00:00:01Z",
                        "url": "https://must-not-be-persisted.example/secret",
                    }
                ],
            }
        },
    )
    stub_fetch(monkeypatch, {"id": job_id, "text": "Support Engineer"})
    async with Client(create_server(store, local_test=True)) as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert {"verify_employer_job", "get_discovery_changes", "get_source_health"} <= tools
        verified = await client.call_tool("verify_employer_job", {"job_id": saved.id})
        assert verified.data["status"] == "SUCCESS"
        changes = await client.call_tool("get_discovery_changes", {"since": "2026-09-19T00:00:00Z"})
        assert changes.data["changes"][0]["job_id"] == saved.id
        health = await client.call_tool("get_source_health", {})
        assert health.data["summary"]["success"] == 1
        assert health.data["sources"][0]["http_codes"] == [200]
        assert "must-not-be-persisted" not in json.dumps(health.data)
