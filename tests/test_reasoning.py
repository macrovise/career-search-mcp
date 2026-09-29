from datetime import UTC, datetime

import pytest

from jobsearch_mcp.models import Profile
from jobsearch_mcp.reasoning import build_profile, score_fit, writing_brief
from jobsearch_mcp.sources.normalize import make_job


def job(**changes):
    row = dict(
        title="Technical Support Engineer",
        company="Acme",
        source_url="https://example.com/job",
        description="Troubleshoot SQL and APIs using Postman.",
        remote_scope="worldwide",
        employment_type="permanent",
        posted_at="2026-09-19",
    )
    row.update(changes)
    return make_job("himalayas", row)


def test_preferences_are_not_experience():
    evidence = score_fit(job(), Profile())
    assert evidence["matched_requirements"] == []
    assert any(s["skill"] == "SQL" for s in evidence["missing_skills"])
    assert evidence["recommendation"] == "review"


def test_literal_evidence_used_for_matching():
    profile = Profile(
        resume_text="I used SQL", verified_skills=["SQL"], skill_evidence={"SQL": "I used SQL"}
    )
    evidence = score_fit(job(), profile)
    assert evidence["matched_requirements"][0]["resume_excerpt"] == "I used SQL"


@pytest.mark.parametrize(
    "changes,excluded",
    [
        ({"salary_max": 39999, "currency": "GBP", "salary_period": "year"}, True),
        (
            {"salary_min": 30000, "salary_max": 50000, "currency": "GBP", "salary_period": "year"},
            False,
        ),
        ({"salary_max": 30000, "currency": "USD", "salary_period": "year"}, False),
        (
            {
                "salary_max": 30000,
                "currency": "GBP",
                "salary_period": "year",
                "salary_is_predicted": True,
            },
            False,
        ),
        ({"employment_type": "contract"}, True),
        ({"remote_scope": "hybrid"}, True),
        ({}, False),
    ],
)
def test_evidence_based_exclusions(changes, excluded):
    result = score_fit(job(**changes), Profile())
    assert bool(result["exclusions"]) == excluded


def test_eligibility_is_not_inferred_from_preferences():
    assert score_fit(job(), Profile())["location_eligibility"]["status"] == "needs_confirmation"


def test_profile_and_writing_tools_are_context_only():
    profile = build_profile("SQL support")
    assert profile["saved"] is False
    assert profile["draft"]["verified_skills"] == []
    for kind in ["tailor_resume", "cover_letter_brief"]:
        result = writing_brief(kind, job(), Profile())
        assert result["reasoning_owner"] == "ChatGPT"
        assert result["application_submitted"] is False
        assert "untrusted" in result["instructions"]


def test_recency_phone_and_unknown_salary_visible():
    result = score_fit(
        job(posted_at="2020-01-01", description="Inbound phone support required"),
        Profile(),
        datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert len(result["concerns"]) >= 3
