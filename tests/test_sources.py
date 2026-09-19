"""Mocked tests for public source adapters and conservative normalization."""

import json
from datetime import UTC, datetime

import pytest

from jobsearch_mcp.service import CareerService
from jobsearch_mcp.sources import public
from jobsearch_mcp.sources.normalize import clean, date_value, number, scope
from jobsearch_mcp.store import Store


def _stub_json_fetch(monkeypatch, payload):
    calls = []

    async def fake_fetch(url, params=None):
        calls.append((url, params))
        return json.dumps(payload).encode()

    monkeypatch.setattr(public, "fetch", fake_fetch)
    return calls


@pytest.mark.asyncio
async def test_himalayas_normalizes_timestamp_countries_and_unknown_salary(monkeypatch):
    calls = _stub_json_fetch(
        monkeypatch,
        {
            "jobs": [
                {
                    "title": "Technical Support Engineer",
                    "companyName": "Acme & Co",
                    "locationRestrictions": [
                        {"name": "United Kingdom"},
                        {"code": "IE"},
                    ],
                    "guid": "https://himalayas.app/jobs/42",
                    "applicationLink": "https://acme.example/careers/42",
                    "description": "<p>Support APIs &amp; integrations.</p>",
                    "pubDate": "2026-09-18T14:30:00Z",
                    "minSalary": "not disclosed",
                    "maxSalary": "competitive",
                    "currency": "GBP",
                    "salaryPeriod": "per project",
                    "employmentType": "Full-Time",
                    "categories": ["Support", "APIs"],
                }
            ]
        },
    )

    jobs = await public.himalayas("technical support")

    assert calls == [
        (
            "https://himalayas.app/jobs/api/search",
            {"q": "technical support", "country": "GB", "sort": "recent", "page": 1},
        )
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.posted_at == datetime(2026, 9, 18, 14, 30, tzinfo=UTC)
    assert job.country_restrictions == ["United Kingdom", "IE"]
    assert job.location == "United Kingdom, IE"
    assert job.remote_scope == "uk"
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.salary_period is None
    assert job.salary_text == ""
    assert job.employment_type == "full_time"
    assert job.description == "Support APIs & integrations."
    assert job.skills == ["Support", "APIs"]
    assert job.sources[0].source_id == "https://himalayas.app/jobs/42"
    assert job.sources[0].fields["posted_at"] == "2026-09-18T14:30:00Z"


@pytest.mark.asyncio
async def test_adzuna_uses_gb_endpoint_credentials_and_salary_prediction_flag(monkeypatch):
    app_id = "test-app-id"
    app_key = "test-app-key-secret"
    monkeypatch.setenv("ADZUNA_APP_ID", app_id)
    monkeypatch.setenv("ADZUNA_APP_KEY", app_key)
    calls = _stub_json_fetch(
        monkeypatch,
        {
            "results": [
                {
                    "id": 101,
                    "title": "Support Engineer",
                    "company": {"display_name": "Northwind"},
                    "location": {"display_name": "Remote - United Kingdom"},
                    "redirect_url": "https://adzuna.example/jobs/101",
                    "description": "Remote role supporting APIs.",
                    "salary_min": 42000,
                    "salary_max": 56000,
                    "salary_is_predicted": 0,
                    "contract_type": "full_time",
                    "created": "2026-09-18T08:00:00Z",
                },
                {
                    "id": 102,
                    "title": "Customer Support Engineer",
                    "company": {"display_name": "Contoso"},
                    "location": {"display_name": "Remote"},
                    "redirect_url": "https://adzuna.example/jobs/102",
                    "description": "Remote support role.",
                    "salary_min": 40000,
                    "salary_max": 50000,
                    "salary_is_predicted": "1",
                    "created": "2026-09-17T08:00:00Z",
                },
            ]
        },
    )

    jobs = await public.adzuna("support engineer")

    assert len(calls) == 1
    url, params = calls[0]
    assert url == "https://api.adzuna.com/v1/api/jobs/gb/search/1"
    assert params == {
        "app_id": app_id,
        "app_key": app_key,
        "what": "support engineer remote",
        "results_per_page": 50,
        "sort_by": "date",
        "max_days_old": 30,
        "content-type": "application/json",
    }
    assert [job.salary_is_predicted for job in jobs] == [False, True]
    assert [job.remote_scope for job in jobs] == ["uk", "unknown"]
    assert jobs[0].employment_type == "full_time"
    assert jobs[0].posted_at == datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    assert jobs[0].sources[0].source_id == "101"
    serialized_jobs = json.dumps([job.model_dump(mode="json") for job in jobs])
    assert app_id not in serialized_jobs
    assert app_key not in serialized_jobs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing_variable", "present_variable", "secret"),
    [
        ("ADZUNA_APP_KEY", "ADZUNA_APP_ID", "private-app-id"),
        ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "private-app-key"),
    ],
)
async def test_adzuna_missing_credentials_error_does_not_echo_secrets(
    monkeypatch, missing_variable, present_variable, secret
):
    monkeypatch.delenv(missing_variable, raising=False)
    monkeypatch.setenv(present_variable, secret)

    with pytest.raises(RuntimeError) as error:
        await public.adzuna("support")

    assert str(error.value) == "Adzuna credentials not configured"
    assert secret not in str(error.value)


@pytest.mark.asyncio
async def test_adzuna_request_error_does_not_echo_api_key_in_source_status(monkeypatch, tmp_path):
    app_key = "private-key-in-request-url"
    monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", app_key)

    async def fake_fetch(url, params=None):
        raise RuntimeError(f"HTTP error for {url}?app_key={params['app_key']}")

    monkeypatch.setattr(public, "fetch", fake_fetch)
    service = CareerService(Store(str(tmp_path / "jobs.sqlite")))

    result = await service.discover("support", sources=["adzuna"])

    assert result["source_status"]["adzuna"]["status"] == "error"
    assert result["source_status"]["adzuna"]["error_type"] == "RuntimeError"
    assert app_key not in json.dumps(result)


@pytest.mark.asyncio
async def test_remotive_parses_job_fields_and_known_remote_scope(monkeypatch):
    calls = _stub_json_fetch(
        monkeypatch,
        {
            "jobs": [
                {
                    "id": 202,
                    "title": "API Support Engineer",
                    "company_name": "Globex",
                    "candidate_required_location": "Worldwide",
                    "job_type": "full_time",
                    "salary": "£45,000-£55,000",
                    "publication_date": "2026-09-18T09:30:00Z",
                    "url": "https://remotive.example/jobs/202",
                    "description": "<p>Help customers with API integrations.</p>",
                    "tags": ["support", "API"],
                }
            ]
        },
    )

    jobs = await public.remotive("API support")

    assert calls == [
        (
            "https://remotive.com/api/remote-jobs",
            {"search": "API support", "limit": 50},
        )
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "API Support Engineer"
    assert job.company == "Globex"
    assert job.location == "Worldwide"
    assert job.remote_scope == "worldwide"
    assert job.employment_type == "full_time"
    assert job.salary_text == "£45,000-£55,000"
    assert job.posted_at == datetime(2026, 9, 18, 9, 30, tzinfo=UTC)
    assert job.description == "Help customers with API integrations."
    assert job.skills == ["support", "API"]
    assert job.sources[0].source_id == "202"


@pytest.mark.asyncio
async def test_jobicy_parses_salary_job_types_and_excerpt_fallback(monkeypatch):
    calls = _stub_json_fetch(
        monkeypatch,
        {
            "jobs": [
                {
                    "id": 303,
                    "jobTitle": "Customer Support Specialist",
                    "companyName": "Initech",
                    "jobGeo": "Europe",
                    "jobType": ["Full-time", "Permanent"],
                    "annualSalaryMin": "48000",
                    "annualSalaryMax": 62000,
                    "salaryCurrency": "EUR",
                    "pubDate": "2026-09-16T12:00:00Z",
                    "url": "https://jobicy.example/jobs/303",
                    "jobDescription": "",
                    "jobExcerpt": "<p>Resolve customer API issues.</p>",
                }
            ]
        },
    )

    jobs = await public.jobicy("customer support")

    assert calls == [
        ("https://jobicy.com/api/v2/remote-jobs", {"tag": "customer support", "count": 50})
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.remote_scope == "europe"
    assert job.employment_type == "full_time"
    assert job.salary_min == 48000
    assert job.salary_max == 62000
    assert job.currency == "EUR"
    assert job.salary_period == "year"
    assert job.posted_at == datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    assert job.description == "Resolve customer API issues."
    assert job.sources[0].source_id == "303"


@pytest.mark.asyncio
async def test_weworkremotely_parses_rss_filters_terms_and_cleans_markup(monkeypatch):
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Acme: Technical Support Engineer</title>
        <link>https://weworkremotely.example/jobs/401</link>
        <guid>wwr-401</guid>
        <pubDate>Fri, 18 Sep 2026 12:00:00 GMT</pubDate>
        <description><![CDATA[<p>Support API and JSON integrations.</p>]]></description>
      </item>
      <item>
        <title>Other Co: Support Analyst</title>
        <link>https://weworkremotely.example/jobs/402</link>
        <description><![CDATA[<p>Customer service role.</p>]]></description>
      </item>
    </channel></rss>"""
    calls = []

    async def fake_fetch(url, params=None):
        calls.append((url, params))
        return rss

    monkeypatch.setattr(public, "fetch", fake_fetch)

    jobs = await public.weworkremotely("support API")

    assert calls == [
        ("https://weworkremotely.com/categories/remote-customer-support-jobs.rss", None)
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Technical Support Engineer"
    assert job.company == "Acme"
    assert job.location == "Remote"
    assert job.remote_scope == "remote_unspecified"
    assert job.description == "Support API and JSON integrations."
    assert job.posted_at == datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert job.sources[0].source_id == "wwr-401"


@pytest.mark.asyncio
async def test_malformed_api_json_fails_instead_of_appearing_as_empty_results(monkeypatch):
    async def fake_fetch(url, params=None):
        return b'{"jobs":'

    monkeypatch.setattr(public, "fetch", fake_fetch)

    with pytest.raises(json.JSONDecodeError):
        await public.himalayas("support")


@pytest.mark.asyncio
async def test_malformed_weworkremotely_feed_is_reported(monkeypatch):
    async def fake_fetch(url, params=None):
        return b"not xml"

    monkeypatch.setattr(public, "fetch", fake_fetch)

    with pytest.raises(ValueError, match="Invalid RSS response"):
        await public.weworkremotely("support")


def test_normalization_preserves_remote_and_value_uncertainty():
    assert scope("Remote", known_remote=False) == "unknown"
    assert scope("", known_remote=False) == "unknown"
    assert scope("Remote", known_remote=True) == "remote_unspecified"
    assert scope("Remote role in the United Kingdom", known_remote=False) == "uk"
    assert scope("United States", known_remote=True) == "restricted"
    assert number("competitive") is None
    assert number(-1) is None
    assert date_value("not a date") is None
    assert date_value("2026-09-18T14:30:00Z") == datetime(2026, 9, 18, 14, 30, tzinfo=UTC)
    assert clean(" <p>Support &amp; APIs</p> ") == "Support & APIs"
