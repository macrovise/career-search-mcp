"""Explainable query filtering for provider searches and broad job feeds."""

import re

from .models import Job
from .reasoning import mentions


def query_evidence(job: Job, query: str) -> dict:
    """Require role words in the title, not incidental company-description text.

    Qualifiers such as "technical" and skills such as SQL may appear in the
    description. This is literal matching, not a claim of semantic understanding.
    """
    terms = list(dict.fromkeys(re.findall(r"\w+(?:\+\+|#)?", query.casefold())))
    title_terms = [term for term in terms if mentions(job.title, term)]
    description_terms = [term for term in terms if mentions(job.description, term)]
    anchors = next(
        (
            list(role)
            for role in (
                ("application", "support"),
                ("product", "support"),
                ("support", "engineer"),
                ("customer", "engineer"),
                ("support",),
                ("engineer",),
            )
            if set(role) <= set(terms)
        ),
        [],
    )
    missing = [term for term in terms if term not in title_terms + description_terms]
    return {
        "query": query,
        "matches": bool(terms) and not missing and set(anchors) <= set(title_terms),
        "matched_title_terms": title_terms,
        "matched_description_terms": description_terms,
        "required_title_terms": anchors,
        "missing_terms": missing,
        "all_terms_in_title": bool(terms) and len(title_terms) == len(terms),
        "method": "Whole-word matching (including plurals); role terms must occur in title",
    }


def discovery_validation(job: Job, query: str, preferences, source: str) -> dict:
    """Validate source output independently of provider-side search parameters."""
    relevance = query_evidence(job, query)
    reasons = []
    if not relevance["matches"]:
        reasons.append("query_relevance")

    # Unknown/unspecified location remains reviewable; a disclosed incompatible
    # scope does not. This avoids turning missing evidence into a false rejection.
    # Himalayas has historically returned records outside its request filters.
    # Keep this independent acceptance gate source-specific: other adapters retain
    # their established behavior of returning incompatible jobs under excluded_jobs.
    if source == "himalayas":
        if job.remote_scope not in {"unknown", "remote_unspecified"} and (
            job.remote_scope not in preferences.preferred_remote_scopes
        ):
            reasons.append("location_scope")
        if job.employment_type in preferences.exclude_employment_types:
            reasons.append("employment_type")
        disclosed_annual_gbp = (
            job.currency == "GBP"
            and job.salary_period == "year"
            and not job.salary_is_predicted
            and job.salary_max is not None
        )
        if disclosed_annual_gbp and job.salary_max < preferences.salary_min_gbp:
            reasons.append("salary_below_minimum")
    if (
        not preferences.allow_undisclosed_salary
        and job.salary_min is None
        and job.salary_max is None
    ):
        reasons.append("salary_undisclosed")
    return {
        "source": source,
        "accepted": not reasons,
        "rejection_reasons": reasons,
        "query_evidence": relevance,
        "salary_rule": "disclosed non-predicted annual GBP upper bound",
        "location_rule": "preferred scopes; unknown evidence remains reviewable",
    }
