"""Official HTTPS APIs and feeds; keys come only from environment variables."""

import json
import os

import feedparser

from ..http import fetch
from .normalize import clean, employment, make_job, period, restrictions, scope


async def himalayas(query: str):
    data = json.loads(
        await fetch(
            "https://himalayas.app/jobs/api/search",
            {"q": query, "country": "GB", "sort": "recent", "page": 1},
        )
    )
    jobs = []
    for row in data.get("jobs", []):
        countries = restrictions(row.get("locationRestrictions"))
        location = ", ".join(countries) or "Worldwide"
        link = row.get("guid", "")
        jobs.append(
            make_job(
                "himalayas",
                dict(
                    title=row["title"],
                    company=row.get("companyName", ""),
                    location=location,
                    remote_scope=scope(location, known_remote=True),
                    country_restrictions=countries,
                    salary_min=row.get("minSalary"),
                    salary_max=row.get("maxSalary"),
                    currency=row.get("currency"),
                    salary_period=period(row.get("salaryPeriod")),
                    employment_type=employment(row.get("employmentType")),
                    posted_at=row.get("pubDate"),
                    source_url=link,
                    application_url=row.get("applicationLink", ""),
                    source_id=link,
                    description=row.get("description", ""),
                    skills=row.get("categories", []),
                ),
            )
        )
    return jobs


async def adzuna(query: str):
    app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not app_id or not key:
        raise RuntimeError("Adzuna credentials not configured")
    data = json.loads(
        await fetch(
            "https://api.adzuna.com/v1/api/jobs/gb/search/1",
            {
                "app_id": app_id,
                "app_key": key,
                "what": query + " remote",
                "results_per_page": 50,
                "sort_by": "date",
                "max_days_old": 30,
                "content-type": "application/json",
            },
        )
    )
    jobs = []
    for row in data.get("results", []):
        location = row.get("location", {}).get("display_name", "")
        description = row.get("description", "")
        jobs.append(
            make_job(
                "adzuna",
                dict(
                    title=row["title"],
                    company=row.get("company", {}).get("display_name", ""),
                    location=location,
                    remote_scope=scope(location, description),
                    salary_min=row.get("salary_min"),
                    salary_max=row.get("salary_max"),
                    currency="GBP",
                    salary_period="year",
                    salary_is_predicted=str(row.get("salary_is_predicted", "1")) != "0",
                    employment_type=employment(
                        row.get("contract_type") or row.get("contract_time")
                    ),
                    posted_at=row.get("created"),
                    source_url=row["redirect_url"],
                    source_id=str(row["id"]),
                    description=description,
                ),
            )
        )
    return jobs


async def remotive(query: str):
    data = json.loads(
        await fetch("https://remotive.com/api/remote-jobs", {"search": query, "limit": 50})
    )
    return [
        make_job(
            "remotive",
            dict(
                title=r["title"],
                company=r.get("company_name", ""),
                location=r.get("candidate_required_location", ""),
                remote_scope=scope(r.get("candidate_required_location", ""), known_remote=True),
                employment_type=employment(r.get("job_type")),
                salary_text=r.get("salary", ""),
                posted_at=r.get("publication_date"),
                source_url=r["url"],
                source_id=str(r["id"]),
                description=r.get("description", ""),
                skills=r.get("tags", []),
            ),
        )
        for r in data.get("jobs", [])
    ]


async def jobicy(query: str):
    data = json.loads(
        await fetch(
            "https://jobicy.com/api/v2/remote-jobs",
            {"count": 50, **({"tag": query} if query else {})},
        )
    )
    return [
        make_job(
            "jobicy",
            dict(
                title=r["jobTitle"],
                company=r.get("companyName", ""),
                location=r.get("jobGeo", ""),
                remote_scope=scope(r.get("jobGeo", ""), known_remote=True),
                employment_type=employment(
                    " ".join(r.get("jobType", []))
                    if isinstance(r.get("jobType"), list)
                    else r.get("jobType")
                ),
                salary_min=r.get("annualSalaryMin"),
                salary_max=r.get("annualSalaryMax"),
                currency=r.get("salaryCurrency"),
                salary_period="year",
                posted_at=r.get("pubDate"),
                source_url=r["url"],
                source_id=str(r["id"]),
                description=r.get("jobDescription") or r.get("jobExcerpt", ""),
            ),
        )
        for r in data.get("jobs", [])
    ]


async def weworkremotely(query: str):
    data = feedparser.parse(
        await fetch("https://weworkremotely.com/categories/remote-customer-support-jobs.rss")
    )
    if data.bozo and not data.entries:
        raise ValueError("Invalid RSS response")
    jobs = []
    words = query.casefold().split()
    for r in data.entries:
        title = clean(r.get("title", ""))
        description = clean(r.get("summary", ""))
        if not all(word in (title + " " + description).casefold() for word in words):
            continue
        company, sep, role = title.partition(": ")
        jobs.append(
            make_job(
                "weworkremotely",
                dict(
                    title=role if sep else title,
                    company=company if sep else r.get("author", ""),
                    location="Remote",
                    remote_scope="remote_unspecified",
                    source_url=r["link"],
                    source_id=r.get("id", r["link"]),
                    posted_at=r.get("published"),
                    description=description,
                ),
            )
        )
    return jobs[:50]
