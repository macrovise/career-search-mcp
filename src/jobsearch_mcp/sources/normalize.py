"""Translate source fields conservatively; retain evidence and uncertainty."""

import hashlib
import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ..models import Job, SourceEvidence


def date_value(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), UTC)
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            result = parsedate_to_datetime(str(value))
        return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def clean(value) -> str:
    return html.unescape(re.sub("<[^>]+>", " ", str(value or ""))).strip()


def restrictions(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v.get("name", v.get("code", ""))) if isinstance(v, dict) else str(v) for v in value]


def scope(location: str, description: str = "", known_remote: bool = False) -> str:
    loc = location.casefold()
    if re.search(r"\bhybrid\b", loc):
        return "hybrid"
    if re.search(r"\bon[ -]?site\b", loc):
        return "onsite"
    if re.search(r"\b(worldwide|anywhere|global|work from anywhere)\b", loc):
        return "worldwide"
    if not known_remote and not re.search(
        r"\b(fully remote|100% remote|remote position|remote role|remote -|remote,)\b",
        loc + " " + description.casefold(),
    ):
        return "unknown"
    if re.search(r"\b(uk|gb|united kingdom)\b", loc):
        return "uk"
    if "emea" in loc:
        return "emea"
    if "europe" in loc:
        return "europe"
    if loc in {"", "remote"}:
        return "remote_unspecified"
    return "restricted"


def employment(value) -> str:
    value = clean(value).casefold()
    if "contract" in value or "freelance" in value:
        return "contract"
    if "temp" in value:
        return "temporary"
    if "full" in value:
        return "full_time"
    if "part" in value:
        return "part_time"
    if "permanent" in value:
        return "permanent"
    if "intern" in value:
        return "internship"
    return "unknown"


def number(value):
    try:
        return float(value) if value is not None and float(value) >= 0 else None
    except (ValueError, TypeError):
        return None


def period(value):
    value = str(value or "").casefold()
    return {
        "annual": "year",
        "annually": "year",
        "yearly": "year",
        "year": "year",
        "per year": "year",
        "hourly": "hour",
        "hour": "hour",
        "monthly": "month",
        "month": "month",
    }.get(value)


def make_job(source: str, row: dict) -> Job:
    """row uses canonical field names plus source_id; no provider fields leak silently."""
    row = dict(row)
    source_id = str(row.pop("source_id", "") or row.get("source_url", ""))
    row["title"] = clean(row.get("title"))
    row["description"] = clean(row.get("description"))[:100000]
    row["company"] = clean(row.get("company"))
    row["posted_at"] = date_value(row.get("posted_at"))
    for key in ["salary_min", "salary_max"]:
        row[key] = number(row.get(key))
    job = Job.model_validate(row)
    job.sources = [
        SourceEvidence(
            source=source,
            source_id=source_id or hashlib.sha256(job.model_dump_json().encode()).hexdigest(),
            source_url=job.source_url,
            application_url=job.application_url,
            fetched_at=datetime.now(UTC),
            fields=job.model_dump(
                mode="json", exclude={"sources", "match_evidence", "status", "id"}
            ),
        )
    ]
    return job
