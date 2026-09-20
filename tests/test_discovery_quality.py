import ipaddress
from datetime import UTC, datetime

from jobsearch_mcp.http import fetch
from jobsearch_mcp.job_watcher import run_once
from jobsearch_mcp.models import Preferences
from jobsearch_mcp.relevance import discovery_validation
from jobsearch_mcp.service import CareerService, material_hash
from jobsearch_mcp.sources import public
from jobsearch_mcp.sources.normalize import make_job
from jobsearch_mcp.store import Store


def job(source="himalayas", source_id="1", **changes):
    row = {
        "title": "Technical Support Engineer",
        "company": "Example",
        "location": "Worldwide",
        "remote_scope": "worldwide",
        "employment_type": "full_time",
        "source_id": source_id,
        "source_url": f"https://example.com/jobs/{source_id}",
        "description": "Technical support for APIs.",
        **changes,
    }
    return make_job(source, row)


async def test_himalayas_merges_uk_and_worldwide_requests_by_native_id(monkeypatch):
    calls = []

    async def fetch(url, params=None):
        calls.append(params)
        suffix = "uk" if "country" in params else "world"
        shared = {
            "title": "Technical Support Engineer",
            "companyName": "Shared",
            "guid": "https://himalayas.app/jobs/shared",
            "description": "Technical support engineer",
        }
        unique = {
            "title": "Support Engineer",
            "companyName": suffix,
            "guid": f"https://himalayas.app/jobs/{suffix}",
            "description": "Support engineer",
        }
        return __import__("json").dumps({"jobs": [shared, unique]}).encode()

    monkeypatch.setattr(public, "fetch", fetch)
    jobs = await public.himalayas("Support Engineer")

    assert len(calls) == 2
    assert {item.sources[0].source_id for item in jobs} == {
        "https://himalayas.app/jobs/shared",
        "https://himalayas.app/jobs/uk",
        "https://himalayas.app/jobs/world",
    }


def test_himalayas_validation_does_not_trust_provider_filters():
    preferences = Preferences()
    cases = [
        (job(salary_max=39_999, currency="GBP", salary_period="year"), "salary_below_minimum"),
        (job(employment_type="contract"), "employment_type"),
        (job(location="United States", remote_scope="restricted"), "location_scope"),
        (job(title="Marketing Manager"), "query_relevance"),
    ]
    for listing, reason in cases:
        result = discovery_validation(
            listing, "Technical Support Engineer", preferences, "himalayas"
        )
        assert not result["accepted"]
        assert reason in result["rejection_reasons"]

    # Missing salary and unspecified remote scope remain reviewable rather than
    # being converted into evidence that the criteria failed.
    assert discovery_validation(
        job(location="Remote", remote_scope="remote_unspecified"),
        "Technical Support Engineer",
        preferences,
        "himalayas",
    )["accepted"]


def test_undisclosed_salary_preference_is_source_independent():
    preferences = Preferences(allow_undisclosed_salary=False)
    result = discovery_validation(
        job("remotive"), "Technical Support Engineer", preferences, "remotive"
    )
    assert not result["accepted"]
    assert result["rejection_reasons"] == ["salary_undisclosed"]


def test_material_hash_ignores_tracking_urls_and_unordered_sets():
    first = job(
        skills=["API", "SQL"],
        country_restrictions=["United Kingdom", "Ireland"],
        source_url="https://example.com/jobs/1?utm_source=watcher",
    )
    equivalent = job(
        skills=["sql", "API"],
        country_restrictions=["Ireland", "United  Kingdom"],
        source_url="https://example.com/jobs/1?utm_campaign=search",
    )
    changed = equivalent.model_copy(update={"description": "Technical support for webhooks."})

    assert material_hash(first) == material_hash(equivalent)
    assert material_hash(first) != material_hash(changed)


async def test_source_health_distinguishes_success_zero_and_failure(tmp_path, monkeypatch):
    import jobsearch_mcp.service as service_module

    async def success(query):
        return [job("remotive", "ok")]

    async def zero(query):
        return []

    async def failure(query):
        raise RuntimeError("secret=do-not-return")

    monkeypatch.setenv("CAREER_SOURCES", "remotive,jobicy,adzuna")
    monkeypatch.setitem(service_module.ADAPTERS, "remotive", success)
    monkeypatch.setitem(service_module.ADAPTERS, "jobicy", zero)
    monkeypatch.setitem(service_module.ADAPTERS, "adzuna", failure)
    result = await CareerService(Store(str(tmp_path / "db"))).search_live(
        "Technical Support Engineer"
    )

    assert result["source_health"]["successes"] == 1
    assert result["source_health"]["zero_results"] == 1
    assert result["source_health"]["failures"] == 1
    assert result["source_health"]["cached"] == 0
    assert result["source_health"]["latest_fetched_at"] == max(
        result["source_status"][source]["fetched_at"] for source in ("remotive", "jobicy")
    )
    assert result["source_status"]["jobicy"]["fetched_at"]
    assert result["source_status"]["adzuna"]["fetched_at"] is None
    assert "do-not-return" not in str(result)


async def test_source_health_includes_only_observed_http_codes(tmp_path, monkeypatch, respx_mock):
    import jobsearch_mcp.service as service_module
    from jobsearch_mcp import security

    monkeypatch.setattr(security, "_resolve_host", lambda _: [ipaddress.ip_address("8.8.8.8")])
    respx_mock.get("https://provider.example/jobs").respond(200, content=b"ok")

    async def provider(query):
        await fetch("https://provider.example/jobs")
        return [job("remotive", "receipt")]

    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    monkeypatch.setitem(service_module.ADAPTERS, "remotive", provider)
    result = await CareerService(Store(str(tmp_path / "db"))).search_live(
        "Technical Support Engineer"
    )

    receipt = result["source_status"]["remotive"]["http"][0]
    assert receipt["http_code"] == 200
    assert receipt["outcome"] == "SUCCESS"
    assert receipt["fetched_at"]
    assert "url" not in receipt


async def test_watcher_reports_unchanged_as_seen_not_reviewable(tmp_path, monkeypatch):
    import jobsearch_mcp.service as service_module

    db_path = str(tmp_path / "db")
    store = Store(db_path)
    profile = store.get_profile()
    profile.preferences.target_roles = ["Technical Support Engineer"]
    store.save_profile(profile)

    description = ["Technical support for APIs."]

    async def provider(query):
        listing = job(
            "remotive",
            "stable",
            posted_at=datetime(2026, 9, 20, tzinfo=UTC),
            description=description[0],
        )
        return [listing]

    monkeypatch.setenv("CAREER_SOURCES", "remotive")
    monkeypatch.setitem(service_module.ADAPTERS, "remotive", provider)
    service = CareerService(store)
    first = await run_once(service)
    persisted_health = Store(db_path).get_source_health()
    # A new service/store instance proves the baseline survives watcher restarts.
    second = await run_once(CareerService(Store(db_path)))
    description[0] = "Technical support for APIs and webhooks."
    with store.connection() as db:
        db.execute("DELETE FROM source_cache")
    third = await run_once(CareerService(Store(db_path)))

    assert first["reviewable_changes"]["new"] == 1
    assert first["source_health"]["summary"]["success"] == 1
    assert persisted_health["summary"]["success"] == 1
    assert second["reviewable_changes"]["new"] == 0
    assert second["reviewable_changes"]["materially_changed"] == 0
    assert second["reviewable_changes"]["seen_unchanged"] == 1
    assert third["reviewable_changes"]["materially_changed"] == 1
