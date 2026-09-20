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


def test_structured_requirement_fit_uses_quotes_and_explicit_unknowns():
    listing = job(
        description=(
            "Requirements:\n"
            "- SQL troubleshooting experience\n"
            "- Must have hands-on Kubernetes administration\n"
            "Preferred:\n"
            "- Python scripting is a plus"
        )
    )
    profile = Profile(
        resume_text="Resolved SQL incidents for SaaS customers.",
        verified_skills=["SQL"],
        skill_evidence={"SQL": "Resolved SQL incidents for SaaS customers."},
    )

    result = score_fit(listing, profile)["requirement_fit"]

    assert result["classification_counts"] == {"essential": 2, "desirable": 1, "unknown": 0}
    assert result["requirements"][0]["evidence_status"] == "evidenced"
    assert result["requirements"][0]["resume_evidence"][0]["resume_quote"] in profile.resume_text
    assert result["requirements"][1]["evidence_status"] == "not_evidenced"
    assert "unknown" in result["requirements"][1]["gap_note"]
    assert result["requirements"][2]["classification"] == "desirable"


def test_transferable_evidence_is_not_overclaimed_as_direct():
    profile = Profile(
        resume_text="Investigated production incidents and documented root causes.",
        skill_evidence={
            "incident investigation": (
                "Investigated production incidents and documented root causes."
            )
        },
    )
    result = score_fit(
        job(description="Requirements:\n- Experience investigating Kubernetes incidents"), profile
    )["requirement_fit"]["requirements"][0]

    assert result["evidence_status"] == "transferable"
    assert result["resume_evidence"] == []
    assert result["transferable_evidence"][0]["resume_quote"] in profile.resume_text
    assert "do not" not in result["gap_note"].casefold()  # Contract explains, data stays concise.


def test_requirement_without_priority_marker_is_classified_unknown():
    result = score_fit(
        job(description="You will help customers. Experience with OAuth integrations."), Profile()
    )["requirement_fit"]

    assert result["classification_counts"]["unknown"] == 1
    assert result["requirements"][0]["classification"] == "unknown"


def test_benefits_are_not_extracted_as_requirements_and_later_heading_resets():
    description = (
        "What we offer:\n"
        "- Parental leave with the ability to extend time away\n"
        "- Meal stipends and home-office benefits\n"
        "Requirements:\n"
        "- Experience with customer-facing API troubleshooting"
    )

    result = score_fit(job(description=description), Profile())["requirement_fit"]

    assert [item["job_quote"] for item in result["requirements"]] == [
        "Experience with customer-facing API troubleshooting"
    ]
    assert result["requirements"][0]["classification"] == "essential"


def test_phone_on_call_and_location_constraints_are_quote_based():
    result = score_fit(
        job(
            description=(
                "You will provide inbound phone support. Join the weekend on-call rotation. "
                "Applicants must reside in the UK and work GMT hours."
            )
        ),
        Profile(),
    )

    constraints = result["operational_constraints"]
    assert constraints["phone_support"]["status"] == "mentioned"
    assert constraints["on_call_or_shift_work"]["status"] == "mentioned"
    assert constraints["location_or_hours"]["status"] == "mentioned"
    assert all(
        signal["job_quote"]
        for group in constraints.values()
        for signal in group.get("evidence", [])
    )
    assert any("On-call" in concern for concern in result["concerns"])


def test_writing_contract_prioritizes_requirements_over_keyword_coverage():
    result = writing_brief("tailor_resume", job(), Profile())

    assert "requirement_assessment" in result["output_requirements"]
    assert "secondary" in result["output_requirements"]["keyword_coverage"]
