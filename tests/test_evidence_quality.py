import pytest

from jobsearch_mcp.models import Profile
from jobsearch_mcp.reasoning import candidate_text, excerpt, score_fit, writing_brief
from jobsearch_mcp.relevance import query_evidence
from jobsearch_mcp.reporting import ats_estimate
from jobsearch_mcp.sources.normalize import make_job


def job(description):
    return make_job(
        "jobicy",
        {
            "title": "Technical Support Engineer",
            "company": "Example",
            "source_url": "https://example.com/jobs/1",
            "description": description,
            "remote_scope": "uk",
            "employment_type": "full_time",
        },
    )


@pytest.mark.parametrize(
    "heading",
    [
        "Required skills",
        "Essential skills",
        "What you bring",
        "Qualifications and experience",
        "What We Are Looking For",
    ],
)
def test_real_requirements_survive_benefits_and_discovery(heading):
    role = job(f"Benefits\nPython courses and coaching\n{heading}\nSQL required.")
    assert query_evidence(role, "SQL support engineer")["matches"]
    evidence = score_fit(role, Profile())
    assert [r["skill"] for r in evidence["target_keyword_evidence"]] == ["SQL"]
    assert [r["job_quote"] for r in evidence["requirement_fit"]["requirements"]] == [
        "SQL required."
    ]


def test_html_boundaries_filter_benefits_in_fit_and_coverage():
    role = job(
        "<h2>Requirements</h2><p>SQL required.</p>"
        "<h2>What We Offer</h2><p>Python courses and coaching</p>"
    )
    assert "\n" in role.description
    assert [r["skill"] for r in score_fit(role, Profile())["target_keyword_evidence"]] == ["SQL"]
    assert ats_estimate(role, Profile())["detected_count"] == 1


def test_url_does_not_swallow_adjacent_markdown_text():
    text = "[Our docs](https://example.com/docs).HTTP protocol knowledge required."
    role = job(text)
    assert "HTTP" in candidate_text(text)
    assert "HTTP protocol" in excerpt(text, "HTTP", candidate=True)
    assert [r["skill"] for r in score_fit(role, Profile())["target_keyword_evidence"]] == ["HTTP"]


def test_incidental_https_is_not_http_evidence():
    role = job("Read https://example.com/scam-awareness for details.")
    assert score_fit(role, Profile())["target_keyword_evidence"] == []
    assert ats_estimate(role, Profile())["detected_count"] == 0


def test_structured_quotes_are_literal_and_urls_do_not_create_capabilities():
    text = "Required knowledge: https://example.com/python docs."
    requirements = score_fit(job(text), Profile())["requirement_fit"]["requirements"]
    assert all(row["job_quote"] in text for row in requirements)
    assert all("Python" not in row["capabilities_not_evidenced"] for row in requirements)
    text = "[Our docs](https://example.com/docs).HTTP protocol knowledge required."
    requirements = score_fit(job(text), Profile())["requirement_fit"]["requirements"]
    assert requirements
    assert all(row["job_quote"] in text for row in requirements)


def test_alternative_platforms_do_not_create_a_false_linux_gap():
    profile = Profile(
        resume_text="I troubleshoot Windows.",
        verified_skills=["Windows"],
        skill_evidence={"Windows": "I troubleshoot Windows."},
    )
    result = score_fit(job("Requirements\nExperience with Windows or Linux."), profile)
    requirement = result["requirement_fit"]["requirements"][0]
    assert requirement["evidence_status"] == "transferable"
    assert requirement["capabilities_not_evidenced"] == []


def test_compound_requirement_does_not_infer_linux_from_windows():
    profile = Profile(
        resume_text="I troubleshoot Windows.",
        verified_skills=["Windows"],
        skill_evidence={"Windows": "I troubleshoot Windows."},
    )
    result = score_fit(job("Requirements\nProficiency in Windows and Linux."), profile)
    requirement = result["requirement_fit"]["requirements"][0]
    assert requirement["evidence_status"] == "partly_evidenced"
    assert requirement["capabilities_not_evidenced"] == ["Linux"]


def test_explicit_hybrid_preference_and_writing_guidance():
    role = job("Requirements\nSQL required.")
    role.remote_scope = "hybrid"
    profile = Profile()
    profile.preferences.preferred_remote_scopes.append("hybrid")
    assert "Not fully remote" not in score_fit(role, profile)["exclusions"]
    guidance = writing_brief("cover_letter_brief", role, profile)["writing_guidance"]
    assert guidance["locale"] == "en-GB"
    assert "150-220" in guidance["cover_letter"]
