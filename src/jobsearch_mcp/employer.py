"""Read exact public ATS records through documented APIs, never arbitrary pages."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from .http import fetch_with_receipt
from .models import ExternalJobEvidence
from .security import _validate_url
from .sources.normalize import clean, employment, number, period, scope

BOARD = r"([A-Za-z0-9_-]+)"
UUID = r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
ATS_URLS = (
    (re.compile(rf"^jobs\.lever\.co/{BOARD}/{UUID}(?:/apply)?$"), "lever", "us"),
    (re.compile(rf"^jobs\.eu\.lever\.co/{BOARD}/{UUID}(?:/apply)?$"), "lever", "eu"),
    (re.compile(rf"^jobs\.ashbyhq\.com/{BOARD}/{UUID}(?:/application)?$"), "ashby", ""),
    (
        re.compile(rf"^(?:boards|job-boards)\.greenhouse\.io/{BOARD}/jobs/(\d+)$"),
        "greenhouse",
        "",
    ),
)


def _parse_job_url(url: str) -> tuple[str, str, str, str]:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
    ):
        raise ValueError("Employer URL must be an exact supported HTTPS ATS job URL")
    target = (parsed.hostname or "").lower() + parsed.path.rstrip("/")
    for pattern, provider, region in ATS_URLS:
        if match := pattern.fullmatch(target):
            return provider, region, match.group(1), match.group(2)
    raise ValueError("Unsupported employer URL; use an exact Lever, Ashby or Greenhouse job URL")


def _returned_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("ATS returned an unsafe application URL")
    _validate_url(url)
    return url


def _salary_component(component: dict) -> tuple[float | None, float | None, str | None, str | None]:
    return (
        number(component.get("min") or component.get("minValue")),
        number(component.get("max") or component.get("maxValue")),
        component.get("currency") or component.get("currencyCode"),
        period(component.get("interval") or component.get("period")),
    )


def _lever(payload: dict, board: str, job_id: str, source_url: str, fetched_at: str):
    if str(payload.get("id")) != job_id:
        return None
    categories = payload.get("categories") or {}
    description = "\n".join(
        value
        for value in [
            clean(payload.get("descriptionPlain")),
            *(clean(item.get("content")) for item in payload.get("lists") or []),
            clean(payload.get("additionalPlain")),
        ]
        if value
    )
    salary = payload.get("salaryRange") or {}
    salary_min, salary_max, currency, salary_period = _salary_component(salary)
    location = clean(categories.get("location"))
    workplace = clean(payload.get("workplaceType"))
    return ExternalJobEvidence(
        source="employer_lever",
        source_id=job_id,
        source_url=source_url,
        application_url=_returned_url(payload.get("applyUrl")),
        fetched_at=fetched_at,
        retrieval_method="DIRECT_SITE_OR_ATS",
        title=clean(payload.get("text")),
        company=board,
        location=location,
        description=description,
        description_complete=True,
        remote_scope=scope(location, description, "remote" in workplace.casefold()),
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=salary_period,
        employment_type=employment(categories.get("commitment")),
    )


def _ashby(payload: dict, board: str, job_id: str, source_url: str, fetched_at: str):
    matches = []
    for item in payload.get("jobs") or []:
        try:
            parsed = _parse_job_url(str(item.get("jobUrl") or ""))
        except ValueError:
            continue
        if parsed[0] == "ashby" and parsed[2] == board and parsed[3] == job_id:
            matches.append(item)
    if len(matches) != 1:
        return None
    item = matches[0]
    components = [
        component
        for component in (item.get("compensation") or {}).get("summaryComponents") or []
        if str(component.get("compensationType") or component.get("type") or "").casefold()
        == "salary"
    ]
    salary_min = salary_max = salary_period = currency = None
    salary_text = ""
    if len(components) == 1:
        salary_min, salary_max, currency, salary_period = _salary_component(components[0])
        salary_text = clean(components[0].get("summary"))
    location = clean(item.get("location"))
    description = clean(item.get("descriptionPlain"))
    workplace = clean(item.get("workplaceType"))
    return ExternalJobEvidence(
        source="employer_ashby",
        source_id=job_id,
        source_url=source_url,
        application_url=_returned_url(item.get("applyUrl")),
        fetched_at=fetched_at,
        retrieval_method="DIRECT_SITE_OR_ATS",
        title=clean(item.get("title")),
        company=board,
        location=location,
        description=description,
        description_complete=True,
        remote_scope=scope(
            location,
            description,
            bool(item.get("isRemote")) or "remote" in workplace.casefold(),
        ),
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        salary_period=salary_period,
        salary_text=salary_text,
        employment_type=employment(item.get("employmentType")),
        posted_at=item.get("publishedAt"),
    )


def _greenhouse(payload: dict, board: str, job_id: str, source_url: str, fetched_at: str):
    if str(payload.get("id")) != job_id:
        return None
    location = clean((payload.get("location") or {}).get("name"))
    description = clean(payload.get("content"))
    return ExternalJobEvidence(
        source="employer_greenhouse",
        source_id=job_id,
        source_url=source_url,
        application_url=_returned_url(payload.get("absolute_url")),
        fetched_at=fetched_at,
        retrieval_method="DIRECT_SITE_OR_ATS",
        title=clean(payload.get("title")),
        company=board,
        location=location,
        description=description,
        description_complete=True,
        remote_scope=scope(location, description),
    )


async def verify_employer_evidence(url: str) -> dict:
    """Return import-ready evidence from one exact supported public ATS API record."""
    provider, region, board, job_id = _parse_job_url(url)
    if provider == "lever":
        host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
        endpoint = f"https://{host}/v0/postings/{board}/{job_id}"
    elif provider == "ashby":
        endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    else:
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    try:
        body, receipt = await fetch_with_receipt(
            endpoint, {"includeCompensation": "true"} if provider == "ashby" else None
        )
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("ATS API returned an invalid record")
        evidence = {
            "lever": _lever,
            "ashby": _ashby,
            "greenhouse": _greenhouse,
        }[provider](payload, board, job_id, url, receipt["fetched_at"])
        if evidence is None:
            return {"status": "NOT_FOUND", "http": receipt, "evidence": None}
        return {
            "status": "SUCCESS",
            "http": receipt,
            "evidence": evidence.model_dump(mode="json"),
            "limitations": [
                "The ATS API supplied this description; completeness is not semantic verification.",
                "The board identity comes from the caller-selected URL and is not "
                "independently verified.",
            ],
        }
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                "status": "NOT_FOUND",
                "http": {
                    "http_code": 404,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "outcome": "NOT_FOUND",
                    "timestamp_basis": "caller_observed_response_completion",
                },
                "evidence": None,
                "note": "Not found is not evidence that the vacancy is closed.",
            }
        return {"status": "ERROR", "error_type": type(exc).__name__, "evidence": None}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "ERROR", "error_type": type(exc).__name__, "evidence": None}
