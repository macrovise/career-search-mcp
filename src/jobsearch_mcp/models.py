"""Validated canonical records. Unknown evidence is represented explicitly."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    DISCOVERED = "discovered"
    INTERESTING = "interesting"
    REVIEW = "review"
    DISMISSED = "dismissed"
    APPLICATION_PREPARED = "application_prepared"
    APPLIED = "applied"
    AWAITING_RESPONSE = "awaiting_response"
    FOLLOW_UP_DUE = "follow_up_due"
    RECRUITER_SCREEN = "recruiter_screen"
    INTERVIEW = "interview"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_STAGE = "final_stage"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    OFFER = "offer"
    CLOSED = "closed"


class SourceEvidence(BaseModel):
    source: str
    source_id: str
    source_url: str
    application_url: str = ""
    fetched_at: datetime
    fields: dict = Field(default_factory=dict)


class Job(BaseModel):
    id: str = ""
    title: str = Field(min_length=1, max_length=500)
    company: str = ""
    location: str = ""
    remote_scope: Literal[
        "worldwide",
        "uk",
        "emea",
        "europe",
        "restricted",
        "remote_unspecified",
        "onsite",
        "hybrid",
        "unknown",
    ] = "unknown"
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    currency: str | None = None
    salary_period: str | None = None
    salary_is_predicted: bool = False
    salary_text: str = ""
    employment_type: str = "unknown"
    posted_at: datetime | None = None
    sources: list[SourceEvidence] = Field(default_factory=list)
    source_url: str
    application_url: str = ""
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    country_restrictions: list[str] = Field(default_factory=list)
    eligibility: dict = Field(default_factory=lambda: {"status": "unknown"})
    match_evidence: dict = Field(default_factory=dict)
    status: Status = Status.DISCOVERED
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    follow_up_at: datetime | None = None
    conflicts: list[dict] = Field(default_factory=list)


TARGET_ROLES = [
    "Support Engineer",
    "Technical Support Engineer",
    "Customer Engineer",
    "Application Support",
    "Product Support",
    "Customer Support Engineer",
]
POSITIVE_SKILLS = [
    "technical troubleshooting",
    "API",
    "HTTP",
    "JSON",
    "SQL",
    "SaaS",
    "engineering escalation",
    "Python",
    "Postman",
    "Datadog",
]


class Preferences(BaseModel):
    target_roles: list[str] = Field(default_factory=lambda: TARGET_ROLES.copy())
    preferred_remote_scopes: list[str] = Field(
        default_factory=lambda: ["worldwide", "uk", "emea", "europe"]
    )
    salary_min_gbp: int = 40000
    allow_undisclosed_salary: bool = True
    exclude_employment_types: list[str] = Field(default_factory=lambda: ["contract", "temporary"])
    positive_skills: list[str] = Field(default_factory=lambda: POSITIVE_SKILLS.copy())
    prefer_no_inbound_phone: bool = True
    recent_days: int = Field(default=30, ge=1, le=365)


class Profile(BaseModel):
    preferences: Preferences = Field(default_factory=Preferences)
    resume_text: str = Field(default="", max_length=100000)
    # Each fact must cite a literal excerpt; preferences are never candidate facts.
    verified_skills: list[str] = Field(default_factory=list)
    skill_evidence: dict[str, str] = Field(default_factory=dict)
    experience_evidence: list[str] = Field(default_factory=list)
    country: str | None = None
    work_authorization: str | None = None
