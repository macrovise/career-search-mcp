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
