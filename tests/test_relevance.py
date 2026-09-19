"""Keep incidental description keywords out of role-search results."""

import pytest

from jobsearch_mcp.relevance import query_evidence
from jobsearch_mcp.sources.normalize import make_job


def job(title, description=""):
    return make_job(
        "jobicy",
        dict(title=title, description=description, source_url="https://example.com/job"),
    )


@pytest.mark.parametrize(
    "query",
    [
        "Support Engineer",
        "Technical Support Engineer",
        "Customer Engineer",
        "Application Support",
        "Product Support",
        "Customer Support Engineer",
    ],
)
def test_incidental_role_keywords_do_not_make_an_unrelated_title_relevant(query):
    listing = job("SEO/ASO Manager", f"Work with our {query} team.")
    evidence = query_evidence(listing, query)
    assert evidence["matches"] is False
    assert evidence["required_title_terms"]
    assert query_evidence(job(query), query)["matches"] is True


def test_technical_qualifier_can_come_from_description_and_title_can_have_punctuation():
    evidence = query_evidence(
        job("Senior Support-Engineer (EMEA)", "Deliver technical troubleshooting."),
        "Technical Support Engineer",
    )
    assert evidence["matches"] is True
    assert evidence["required_title_terms"] == ["support", "engineer"]
    assert evidence["all_terms_in_title"] is False
    assert "technical" in evidence["matched_description_terms"]


def test_whole_word_matching_retains_plurals_but_rejects_substrings():
    assert query_evidence(job("Support Engineers"), "Support Engineer")["matches"]
    assert not query_evidence(job("Support Engineering Manager"), "Support Engineer")["matches"]
    assert not query_evidence(job("Support Engineer", "MySQL"), "SQL")["matches"]
    assert query_evidence(job("Support Engineer", "SQL and C++"), "SQL C++")["matches"]


def test_skill_queries_still_search_descriptions_without_inventing_role_constraints():
    evidence = query_evidence(job("Platform Specialist", "Debug HTTP APIs with SQL"), "HTTP SQL")
    assert evidence["matches"]
    assert evidence["required_title_terms"] == []
