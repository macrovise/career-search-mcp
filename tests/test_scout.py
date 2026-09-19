"""Mocked Scout MCP calls, schema validation, and canonical job mapping."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from jobsearch_mcp.sources import scout as scout_source


class FakeScoutSession:
    def __init__(self, schema, result):
        self.schema = schema
        self.result = result
        self.calls = []

    async def list_tools(self):
        tools = [
            SimpleNamespace(name="scout_discover", inputSchema=self.schema),
            SimpleNamespace(
                name="scout_score",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def _job_row():
    return {
        "id": "scout-42",
        "title": "Technical Support Engineer",
        "company_name": "Example Co",
        "location": "Remote - United Kingdom",
        "remote": True,
        "salary_min": 45000,
        "salary_max": 55000,
        "currency": "GBP",
        "employment_type": "Full-time",
        "posted_at": "2026-09-18T10:00:00Z",
        "url": "https://jobs.example/42",
        "application_url": "https://jobs.example/42/apply",
        "description": "Troubleshoot customer API integrations.",
        "skills": ["APIs", "SQL"],
        "country_restrictions": ["United Kingdom"],
        "status": "applied",
        "eligibility": {"status": "eligible"},
        "match_evidence": {"score": 100, "recommendation": "strong"},
    }


def _schema():
    return {
        "type": "object",
        "properties": {
            "search_term": {"type": "string"},
            "location": {"type": "string"},
        },
        "required": ["search_term", "location"],
        "additionalProperties": False,
    }


def _configure(monkeypatch, result, schema=None, arguments=None):
    session = FakeScoutSession(
        schema or _schema(),
        result,
    )
    tokens = []

    @asynccontextmanager
    async def fake_open_session(access_token):
        tokens.append(access_token)
        yield session

    monkeypatch.setenv("SCOUT_ACCESS_TOKEN", "provider-approved-test-token")
    monkeypatch.setenv(
        "SCOUT_DISCOVER_ARGUMENTS",
        arguments or '{"search_term": "{query}", "location": "United Kingdom"}',
    )
    monkeypatch.setattr(scout_source, "_open_session", fake_open_session)
    return session, tokens


@pytest.mark.asyncio
async def test_scout_requires_explicit_token_and_argument_template(monkeypatch):
    monkeypatch.delenv("SCOUT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SCOUT_DISCOVER_ARGUMENTS", raising=False)

    with pytest.raises(RuntimeError, match="SCOUT_ACCESS_TOKEN"):
        await scout_source.search("support engineer")

    monkeypatch.setenv("SCOUT_ACCESS_TOKEN", "provider-approved-test-token")
    with pytest.raises(RuntimeError, match="SCOUT_DISCOVER_ARGUMENTS"):
        await scout_source.search("support engineer")


@pytest.mark.asyncio
async def test_scout_validates_arguments_and_normalizes_structured_jobs(monkeypatch):
    result = SimpleNamespace(
        isError=False,
        structuredContent={"results": [_job_row()]},
        content=[],
    )
    session, tokens = _configure(monkeypatch, result)

    jobs = await scout_source.search("technical support engineer")

    assert tokens == ["provider-approved-test-token"]
    assert session.calls == [
        (
            "scout_discover",
            {"search_term": "technical support engineer", "location": "United Kingdom"},
        )
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Technical Support Engineer"
    assert job.company == "Example Co"
    assert job.location == "Remote - United Kingdom"
    assert job.remote_scope == "uk"
    assert job.salary_min == 45000
    assert job.salary_max == 55000
    assert job.currency == "GBP"
    assert job.employment_type == "full_time"
    assert job.posted_at == datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    assert job.source_url == "https://jobs.example/42"
    assert job.application_url == "https://jobs.example/42/apply"
    assert job.skills == ["APIs", "SQL"]
    assert job.country_restrictions == ["United Kingdom"]
    assert job.sources[0].source == "scout"
    assert job.sources[0].source_id == "scout-42"
    assert job.status == "discovered"
    assert job.eligibility == {"status": "unknown"}
    assert job.match_evidence == {}
    assert "provider-approved-test-token" not in json.dumps(job.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_scout_accepts_text_json_jobs_array(monkeypatch):
    result = SimpleNamespace(
        isError=False,
        structuredContent=None,
        content=[SimpleNamespace(type="text", text=json.dumps({"jobs": [_job_row()]}))],
    )
    session, _ = _configure(monkeypatch, result)

    jobs = await scout_source.search("support")

    assert [job.title for job in jobs] == ["Technical Support Engineer"]
    assert [name for name, _arguments in session.calls] == ["scout_discover"]


@pytest.mark.asyncio
async def test_scout_rejects_arguments_that_do_not_match_live_schema(monkeypatch):
    result = SimpleNamespace(isError=False, structuredContent={"jobs": []}, content=[])
    session, _ = _configure(
        monkeypatch,
        result,
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query", "region"],
        },
    )

    with pytest.raises(ValueError, match="do not match its input schema"):
        await scout_source.search("support")

    assert session.calls == []


@pytest.mark.asyncio
async def test_scout_rejects_invalid_published_schema_without_calling_tool(monkeypatch):
    result = SimpleNamespace(isError=False, structuredContent={"jobs": []}, content=[])
    session, _ = _configure(
        monkeypatch,
        result,
        schema={"type": "not-a-json-schema-type"},
    )

    with pytest.raises(ValueError, match="invalid JSON input schema"):
        await scout_source.search("support")

    assert session.calls == []


@pytest.mark.asyncio
async def test_scout_rejects_remote_schema_references(monkeypatch):
    result = SimpleNamespace(isError=False, structuredContent={"jobs": []}, content=[])
    session, _ = _configure(
        monkeypatch,
        result,
        schema={"type": "object", "properties": {"query": {"$ref": "https://example/schema"}}},
    )

    with pytest.raises(ValueError, match="remote references"):
        await scout_source.search("support")

    assert session.calls == []


@pytest.mark.asyncio
async def test_scout_fails_clearly_on_unrecognized_output_shape(monkeypatch):
    result = SimpleNamespace(isError=False, structuredContent={"records": []}, content=[])
    session, _ = _configure(monkeypatch, result)

    with pytest.raises(ValueError, match="jobs or results array"):
        await scout_source.search("support")

    assert [name for name, _arguments in session.calls] == ["scout_discover"]


@pytest.mark.asyncio
async def test_scout_sanitizes_mcp_errors_without_echoing_access_token(monkeypatch):
    class BrokenSession(FakeScoutSession):
        async def list_tools(self):
            raise RuntimeError("request headers contain provider-approved-test-token")

    session = BrokenSession(_schema(), SimpleNamespace())

    @asynccontextmanager
    async def fake_open_session(_access_token):
        yield session

    monkeypatch.setenv("SCOUT_ACCESS_TOKEN", "provider-approved-test-token")
    monkeypatch.setenv("SCOUT_DISCOVER_ARGUMENTS", '{"search_term": "{query}", "location": "UK"}')
    monkeypatch.setattr(scout_source, "_open_session", fake_open_session)

    with pytest.raises(RuntimeError, match="Scout tools/list request failed") as error:
        await scout_source.search("support")

    assert "provider-approved-test-token" not in str(error.value)


@pytest.mark.asyncio
async def test_open_session_validates_fixed_endpoint_and_disables_proxy_environment(monkeypatch):
    events = []

    class FakeHttpClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            events.append(("http", kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeClientSession:
        def __init__(self, read_stream, write_stream):
            self.streams = (read_stream, write_stream)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            events.append(("initialize", self.streams))

    @asynccontextmanager
    async def fake_streamable_http_client(endpoint, *, http_client):
        events.append(("mcp", endpoint, http_client))
        yield ("read", "write", None)

    def fake_validate_url(url):
        events.append(("validate", url))

    monkeypatch.setattr(scout_source, "_validate_url", fake_validate_url)
    monkeypatch.setattr(scout_source.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(scout_source, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(scout_source, "ClientSession", FakeClientSession)

    async with scout_source._open_session("provider-approved-test-token"):
        events.append(("ready",))

    assert events[0] == ("validate", scout_source.SCOUT_MCP_ENDPOINT)
    http_event = next(event for event in events if event[0] == "http")
    assert http_event[1]["headers"] == {"Authorization": "Bearer provider-approved-test-token"}
    assert http_event[1]["follow_redirects"] is False
    assert http_event[1]["trust_env"] is False
    assert (
        next(event for event in events if event[0] == "mcp")[1] == scout_source.SCOUT_MCP_ENDPOINT
    )
