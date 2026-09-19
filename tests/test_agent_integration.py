"""Regression coverage for external job evidence, assessment, and handoff."""

from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client
from pydantic import ValidationError

from jobsearch_mcp.models import (
    ExternalJobEvidence,
    HttpObservation,
    Profile,
    ResumeVariant,
    Status,
)
from jobsearch_mcp.reporting import ats_estimate, portable_job, role_fields
from jobsearch_mcp.server import create_server
from jobsearch_mcp.store import Store

FETCHED_AT = datetime(2026, 9, 19, 8, 15, tzinfo=UTC)
CHECKED_AT = datetime(2026, 9, 19, 8, 20, tzinfo=UTC)


def evidence(**changes) -> ExternalJobEvidence:
    """Build portable evidence with a real, explicit retrieval timestamp."""
    row = {
        "source": "worldwide_support_role_scan_agent",
        "source_id": "role-42",
        "source_url": "https://jobs.example.test/roles/42",
        "application_url": "https://careers.example.test/apply/42",
        "fetched_at": FETCHED_AT,
        "retrieval_method": "DIRECT_SITE_OR_ATS",
        "title": "Support Engineer",
        "company": "Example Co",
        "location": "Remote, worldwide",
        "remote_scope": "worldwide",
        "employment_type": "full_time",
        "description": "Use API and SQL.",
        "description_complete": True,
    }
    row.update(changes)
    return ExternalJobEvidence.model_validate(row)


def database_dump(store: Store) -> list[str]:
    with store.connection() as db:
        return list(db.iterdump())


def parse_datetime(value: str) -> datetime:
    """Compare equivalent UTC spellings such as `Z` and `+00:00`."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_role_fields_include_truthful_source_time_and_unknown_http_status():
    item = evidence()
    job = portable_job(item)

    result = role_fields(job, Profile())

    assert {
        "http_status",
        "eligibility_compatibility",
        "ats_score",
        "fetched_at",
        "source",
    } <= result.keys()
    assert result["fetched_at"] == FETCHED_AT.isoformat()
    assert result["source"][0]["source"] == item.source
    assert result["source"][0]["source_id"] == item.source_id
    check = result["http_status"]["checks"][0]
    assert check == {
        "url": item.application_url,
        "code": None,
        "checked_at": None,
        "outcome": "not_checked",
        "reported_by": None,
        "method": None,
    }
    assert result["eligibility_compatibility"]["location_eligibility"]["status"] == (
        "needs_confirmation"
    )
    assert result["ats_score"]["value"] is None


def test_http_404_requires_and_preserves_the_observer_and_check_time():
    observation = HttpObservation(
        url="https://careers.example.test/apply/42",
        code=404,
        checked_at=CHECKED_AT,
        outcome="observed",
        method="GET",
        reported_by="URLTimeObserver",
    )
    result = role_fields(portable_job(evidence(http_checks=[observation])), Profile())

    check = result["http_status"]["checks"][0]
    assert check["code"] == 404
    assert check["outcome"] == "observed"
    assert parse_datetime(check["checked_at"]) == CHECKED_AT
    assert check["reported_by"] == "URLTimeObserver"
    # The source retrieval time and the separate page-check time remain distinct.
    assert result["fetched_at"] == FETCHED_AT.isoformat()


def test_http_code_without_an_observer_is_rejected():
    with pytest.raises(ValidationError, match="HTTP codes require a check time, observer"):
        HttpObservation(
            url="https://careers.example.test/apply/42",
            code=404,
            checked_at=CHECKED_AT,
            outcome="observed",
            method="GET",
        )


def test_ats_estimate_is_null_without_cv_or_detectable_job_terms():
    job = portable_job(evidence())

    missing_cv = ats_estimate(job, Profile())
    assert missing_cv["status"] == "unavailable"
    assert missing_cv["value"] is None
    assert missing_cv["detected_count"] == 2

    quote = "Used SQL to investigate customer issues."
    profile = Profile(resume_text=quote, skill_evidence={"SQL": quote})
    no_terms_job = portable_job(evidence(description="Help customers resolve open requests."))
    no_denominator = ats_estimate(no_terms_job, profile)
    assert no_denominator["status"] == "unavailable"
    assert no_denominator["value"] is None
    assert no_denominator["detected_count"] == 0
    assert "not an employer ats score" in no_denominator["limitations"].lower()


def test_ats_variants_have_separate_keyword_coverage_and_literal_citations():
    api_quote = "Supported API integrations for customers."
    sql_quote = "Used SQL to investigate customer issues."
    profile = Profile(
        resume_text=f"{api_quote}\n{sql_quote}",
        skill_evidence={"API": api_quote, "SQL": sql_quote},
        resume_variants={
            "support": ResumeVariant(
                label="Support",
                source_filename="support-cv.pdf",
                resume_text=f"{api_quote}\n{sql_quote}",
                skill_evidence={"API": api_quote, "SQL": sql_quote},
            ),
            "data": ResumeVariant(
                label="Data",
                source_filename="data-cv.pdf",
                resume_text=sql_quote,
                skill_evidence={"SQL": sql_quote},
            ),
        },
    )
    job = portable_job(evidence())

    support = ats_estimate(job, profile, "support")
    data = ats_estimate(job, profile, "data")

    assert support["value"] == 100
    assert support["detected_count"] == 2
    assert {item["term"] for item in support["matched"]} == {"API", "SQL"}
    assert all(item["resume_excerpt"] in profile.resume_text for item in support["matched"])
    assert data["value"] == 50
    assert [item["term"] for item in data["matched"]] == ["SQL"]
    assert data["matched"][0]["resume_excerpt"] == sql_quote
    assert [item["term"] for item in data["not_evidenced"]] == ["API"]
    assert "not an employer ats score" in support["limitations"].lower()


def test_profile_rejects_a_variant_citation_from_a_different_cv(tmp_path):
    api_quote = "Supported API integrations for customers."
    sql_quote = "Used SQL to investigate customer issues."
    profile = Profile(
        resume_text=f"{api_quote}\n{sql_quote}",
        resume_variants={
            "data": ResumeVariant(
                label="Data",
                source_filename="data-cv.pdf",
                resume_text=sql_quote,
                skill_evidence={"SQL": api_quote},
            )
        },
    )
    store = Store(str(tmp_path / "profile.sqlite3"))

    with pytest.raises(ValueError, match="Variant skill evidence must quote that CV"):
        store.save_profile(profile)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "applied"),
        ("eligibility", {"status": "eligible"}),
        ("match_evidence", {"recommendation": "strong"}),
        ("ats_score", {"value": 100}),
    ],
)
def test_external_evidence_rejects_upstream_application_and_assessment_claims(field, value):
    payload = evidence().model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValidationError):
        ExternalJobEvidence.model_validate(payload)


async def test_assessment_is_read_only_does_not_fetch_and_import_is_absent_in_read_only_mode(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CAREER_READ_ONLY", "true")

    def outbound_call(*_args, **_kwargs):
        raise AssertionError("assessment must not make an outbound request")

    monkeypatch.setattr("jobsearch_mcp.http.fetch", outbound_call)
    monkeypatch.setattr("jobsearch_mcp.http._validate_url", outbound_call)

    store = Store(str(tmp_path / "evidence.sqlite3"))
    server = create_server(store, local_test=True)
    before = database_dump(store)

    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools["assess_job_evidence"].annotations.readOnlyHint is True
        assert tools["prepare_handoff"].annotations.readOnlyHint is True
        assert "import_job_evidence" not in tools

        assessment = await client.call_tool(
            "assess_job_evidence", {"evidence": evidence().model_dump(mode="json")}
        )
        assert not assessment.is_error
        assert assessment.data["persisted"] is False
        assert assessment.data["application_submitted"] is False
        assert {
            "http_status",
            "eligibility_compatibility",
            "ats_score",
            "fetched_at",
            "source",
        } <= assessment.data.keys()

        handoff = await client.call_tool("prepare_handoff", {"job_id": assessment.data["id"]})
        assert not handoff.is_error
        assert handoff.data["persisted"] is False
        assert handoff.data["records"][0]["source_id"] == "role-42"

        unavailable = await client.call_tool(
            "import_job_evidence",
            {"evidence": evidence().model_dump(mode="json")},
            raise_on_error=False,
        )
        assert unavailable.is_error

    assert database_dump(store) == before


async def test_import_is_idempotent_and_preserves_an_applied_job(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "false")
    store = Store(str(tmp_path / "evidence.sqlite3"))

    async with Client(create_server(store, local_test=True)) as client:
        first = await client.call_tool(
            "import_job_evidence", {"evidence": evidence().model_dump(mode="json")}
        )
        assert not first.is_error
        job_id = first.data["job"]["id"]
        assert first.data["job"]["status"] == Status.DISCOVERED.value
        assert first.data["persisted"] is True
        assert first.data["application_submitted"] is False

        follow_up = FETCHED_AT + timedelta(days=7)
        store.update_status(job_id, Status.APPLIED, "User confirmed application", follow_up)
        history_before = store.history(job_id)

        second = await client.call_tool(
            "import_job_evidence", {"evidence": evidence().model_dump(mode="json")}
        )
        third = await client.call_tool(
            "import_job_evidence", {"evidence": evidence().model_dump(mode="json")}
        )

    assert second.data["job"]["id"] == third.data["job"]["id"] == job_id
    assert second.data["job"]["status"] == Status.APPLIED.value
    assert parse_datetime(second.data["job"]["follow_up_at"]) == follow_up
    assert len(store.list_jobs()) == 1
    assert len(store.get(job_id).sources) == 1
    assert store.history(job_id) == history_before


async def test_older_snapshot_cannot_replace_newer_imported_source_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "false")
    store = Store(str(tmp_path / "evidence.sqlite3"))
    newer_time = FETCHED_AT + timedelta(hours=1)
    newer = evidence(
        fetched_at=newer_time,
        title="Senior Support Engineer",
        description="Newer source text using API and SQL.",
    )
    older = evidence(
        fetched_at=FETCHED_AT,
        title="Support Engineer",
        description="Stale source text without detail.",
    )

    async with Client(create_server(store, local_test=True)) as client:
        saved = await client.call_tool(
            "import_job_evidence", {"evidence": newer.model_dump(mode="json")}
        )
        replayed = await client.call_tool(
            "import_job_evidence", {"evidence": older.model_dump(mode="json")}
        )

    job_id = saved.data["job"]["id"]
    assert replayed.data["job"]["id"] == job_id
    assert replayed.data["job"]["title"] == newer.title
    assert replayed.data["job"]["description"] == newer.description
    assert store.get(job_id).sources[0].fetched_at == newer_time


async def test_portable_handoff_can_be_replayed_after_a_new_server_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_READ_ONLY", "false")
    database_path = tmp_path / "evidence.sqlite3"
    first_store = Store(str(database_path))
    original = first_store.upsert(portable_job(evidence()))

    async with Client(create_server(first_store, local_test=True)) as first_client:
        prepared = await first_client.call_tool("prepare_handoff", {"job_id": original.id})

    assert not prepared.is_error
    assert prepared.data["persisted"] is False
    portable_record = prepared.data["records"][0]

    # A fresh Store/server represents a restart while keeping the same durable DB.
    restarted_store = Store(str(database_path))
    async with Client(create_server(restarted_store, local_test=True)) as restarted_client:
        replayed = await restarted_client.call_tool(
            "import_job_evidence", {"evidence": portable_record}
        )

    assert not replayed.is_error
    assert replayed.data["job"]["id"] == original.id
    assert parse_datetime(replayed.data["job"]["fetched_at"]) == FETCHED_AT
    assert replayed.data["job"]["source"][0]["source_id"] == "role-42"
    assert len(restarted_store.list_jobs()) == 1
