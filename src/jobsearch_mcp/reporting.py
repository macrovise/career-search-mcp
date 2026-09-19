"""One honest result contract for provider searches and other job plugins.

No network calls or writes occur here. HTTP observations supplied by an agent
remain attributed to that agent. Numeric scores describe keyword coverage only.
"""

import hashlib
import re

from .models import ExternalJobEvidence, Job, Profile
from .reasoning import excerpt, mentions, score_fit
from .sources.normalize import make_job
from .store import canonical_url

TERMS = {
    "API": ["API", "REST"],
    "HTTP": ["HTTP", "HTTPS"],
    "JSON": ["JSON"],
    "SQL": ["SQL", "PostgreSQL", "SQL Server", "MySQL"],
    "Python": ["Python"],
    "Postman": ["Postman"],
    "Datadog": ["Datadog"],
    "SaaS": ["SaaS"],
    "Linux": ["Linux"],
    "Windows": ["Windows"],
    "Azure": ["Azure"],
    "AWS": ["AWS", "Amazon Web Services"],
    "Kubernetes": ["Kubernetes"],
    "Docker": ["Docker"],
    "JavaScript": ["JavaScript"],
    ".NET": [".NET"],
    "OAuth": ["OAuth"],
    "webhooks": ["webhook"],
    "Git": ["Git", "GitHub"],
    "Metabase": ["Metabase"],
    "Jira": ["Jira"],
    "Linear": ["Linear"],
    "Intercom": ["Intercom"],
    "troubleshooting": ["troubleshoot", "troubleshooting"],
    "root cause analysis": ["root cause", "RCA"],
    "engineering escalation": ["engineering escalation", "engineering handoff"],
    "bug reproduction": ["bug reproduction", "reproduce", "reproducing"],
    "documentation": ["documentation"],
    "CSAT": ["CSAT"],
    "SLA": ["SLA"],
    "customer support": ["customer support"],
    "coaching": ["coaching", "coached"],
    "complaint resolution": ["complaint", "complaints"],
}


def ats_estimate(job: Job, profile: Profile, cv_variant: str | None = None) -> dict:
    """Reproducible coverage of a published, limited vocabulary; not a fit verdict."""
    if cv_variant is not None and cv_variant not in profile.resume_variants:
        raise ValueError("Unknown CV variant; inspect get_profile first")
    variant = profile.resume_variants.get(cv_variant) if cv_variant else None
    evidence = variant.skill_evidence if variant else profile.skill_evidence
    resume = variant.resume_text if variant else profile.resume_text
    terms = {key: list(values) for key, values in TERMS.items()}
    matched, missing = [], []
    for term, aliases in terms.items():
        job_alias = next((a for a in aliases if mentions(job.description, a)), None)
        if job_alias is None:
            continue
        quote = next(
            (
                value
                for key, value in evidence.items()
                if value
                and value in resume
                and (key.casefold() == term.casefold() or any(mentions(key, a) for a in aliases))
            ),
            None,
        )
        item = {"term": term, "job_excerpt": excerpt(job.description, job_alias)}
        if quote:
            matched.append({**item, "resume_excerpt": quote})
        else:
            missing.append(item)
    denominator = len(matched) + len(missing)
    available = bool(resume.strip() and evidence and denominator)
    return {
        "label": "ATS Score — estimated CV keyword coverage",
        "status": "estimated" if available else "unavailable",
        "value": round(100 * len(matched) / denominator, 1) if available else None,
        "scale": 100,
        "method": "career-keyword-coverage-v1",
        "formula": "100 * evidenced matched terms / detected vocabulary terms in job description",
        "cv_variant": cv_variant or "canonical",
        "description_completeness": (
            "caller_reports_complete"
            if any(source.fields.get("description_complete") for source in job.sources)
            else "not_verified_may_be_partial"
        ),
        "matched_count": len(matched),
        "detected_count": denominator,
        "matched": matched,
        "not_evidenced": missing,
        "reason": None if available else "CV evidence or detectable job terms unavailable",
        "limitations": (
            "Not an employer ATS score, hiring probability or complete fit assessment. "
            "Limited keyword vocabulary; does not interpret negation, seniority, years, "
            "required versus desirable skills, or PDF parsing/layout. ChatGPT reviews these. "
            "High coverage cannot override eligibility, salary or employment exclusions."
        ),
    }


def role_fields(job: Job, profile: Profile, cv_variant: str | None = None) -> dict:
    fit = score_fit(job, profile)
    sources = [source.model_dump(mode="json", exclude={"fields"}) for source in job.sources]
    checks = [
        check.model_dump(mode="json") for source in job.sources for check in source.http_checks
    ]
    if not checks:
        checks = [
            {
                "url": job.application_url or job.source_url,
                "code": None,
                "checked_at": None,
                "outcome": "not_checked",
                "reported_by": None,
                "method": None,
            }
        ]
    fetched = max((source.fetched_at for source in job.sources), default=None)
    compatibility = {
        "recommendation": fit["recommendation"],
        "location_eligibility": fit["location_eligibility"],
        "salary_evidence": fit["salary_evidence"],
        "employment_type": job.employment_type,
        "exclusions": fit["exclusions"],
        "concerns": fit["concerns"],
        "matched_requirements": fit["matched_requirements"],
        "missing_skills": fit["missing_skills"],
        "destination_checks": [
            {
                "country": country,
                "status": "needs_confirmation",
                "reason": "Verify employer hiring/residence policy separately from remote scope",
            }
            for country in profile.preferences.destination_countries
        ],
    }
    return {
        "http_status": {
            "checks": checks,
            "evidence_origin": "caller_reported_or_not_checked",
            "note": "HTTP 200 alone does not prove vacancy/application liveness",
        },
        "eligibility_compatibility": compatibility,
        "ats_score": ats_estimate(job, profile, cv_variant),
        "fetched_at": fetched.isoformat() if fetched else None,
        "source": sources,
    }


def portable_job(evidence: ExternalJobEvidence) -> Job:
    """Validate link shape without fetching it, and preserve original fetch times."""
    for url in [evidence.source_url, evidence.application_url]:
        if url and not canonical_url(url):
            raise ValueError("Evidence links must be HTTP(S) URLs")
    row = evidence.model_dump(
        exclude={"source", "fetched_at", "retrieval_method", "http_checks", "description_complete"}
    )
    job = make_job(evidence.source, row)
    source = job.sources[0]
    source.fetched_at = evidence.fetched_at
    source.retrieval_method = evidence.retrieval_method
    source.http_checks = evidence.http_checks
    source.fields["description_complete"] = evidence.description_complete
    return job


def handoff(job: Job) -> dict:
    """A portable snapshot can be re-assessed after a temporary live ID expires."""
    url = canonical_url(job.application_url or job.source_url)
    source_key = ":".join((job.sources[0].source, job.sources[0].source_id)) if job.sources else ""
    reference = hashlib.sha256((url or source_key).encode()).hexdigest()[:24]
    records = []
    for source in job.sources:
        row = {
            key: value
            for key, value in source.fields.items()
            if key in ExternalJobEvidence.model_fields
        }
        row.update(
            title=row.get("title") or job.title,
            source=source.source,
            source_id=source.source_id,
            source_url=source.source_url,
            application_url=source.application_url,
            fetched_at=source.fetched_at.isoformat(),
            retrieval_method=(
                source.retrieval_method
                if re.fullmatch(
                    "DIRECT_CONNECTOR|DIRECT_SITE_OR_ATS|WEB_INDEXED|PROVIDER_ADAPTER",
                    source.retrieval_method,
                )
                else "PROVIDER_ADAPTER"
            ),
            http_checks=[check.model_dump(mode="json") for check in source.http_checks],
        )
        records.append(ExternalJobEvidence.model_validate(row).model_dump(mode="json"))
    return {
        "schema_version": 1,
        "handoff_key": reference,
        "canonical_application_url": url,
        "saved_job_id": job.id if job.id and not job.id.startswith("live:") else None,
        "records": records,
        "persisted": False,
        "instructions": (
            "Save this snapshot only through an available authorised write route. "
            "It is portable evidence, not proof of persistence or newness. Re-assess each "
            "record after live IDs expire; check both the shared seen registry and MCP store. "
            "Never overwrite an existing application state from this snapshot."
        ),
    }


def job_result(job: Job, profile: Profile, *, compact: bool = False) -> dict:
    job.match_evidence = score_fit(job, profile)
    job.eligibility = job.match_evidence["location_eligibility"]
    result = job.model_dump(mode="json")
    result.update(role_fields(job, profile))
    if compact:
        result["description"] = job.description[:1500]
        result["description_truncated"] = len(job.description) > 1500
        result["sources"] = result["source"]
    return result
