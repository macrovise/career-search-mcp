"""Validated canonical records. Unknown evidence is represented explicitly."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class HttpObservation(BaseModel):
    """A caller-reported page check, never inferred from provider API success."""

    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4000)
    code: int | None = Field(default=None, ge=100, le=599)
    checked_at: AwareDatetime | None = None
    outcome: Literal["observed", "not_checked", "unavailable"] = "not_checked"
    method: Literal["GET", "HEAD", "browser", "unknown"] = "unknown"
    reported_by: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def require_observation(self):
        if self.code is not None and (
            self.checked_at is None or self.outcome != "observed" or not self.reported_by
        ):
            raise ValueError("HTTP codes require a check time, observer and observed outcome")
        if self.outcome == "observed" and self.code is None:
            raise ValueError("An observed HTTP response requires a code")
        return self


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
    http_checks: list[HttpObservation] = Field(default_factory=list, max_length=10)
    retrieval_method: str = "provider_adapter"


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
    destination_countries: list[str] = Field(default_factory=lambda: ["Algeria", "Tunisia"])


class ResumeVariant(BaseModel):
    label: str
    source_filename: str
    resume_text: str = Field(min_length=1, max_length=100000)
    skill_evidence: dict[str, str] = Field(default_factory=dict)


class Profile(BaseModel):
    preferences: Preferences = Field(default_factory=Preferences)
    resume_text: str = Field(default="", max_length=100000)
    # Each fact must cite a literal excerpt; preferences are never candidate facts.
    verified_skills: list[str] = Field(default_factory=list)
    skill_evidence: dict[str, str] = Field(default_factory=dict)
    experience_evidence: list[str] = Field(default_factory=list)
    country: str | None = None
    work_authorization: str | None = None
    resume_variants: dict[str, ResumeVariant] = Field(default_factory=dict, max_length=5)
    unresolved_questions: list[str] = Field(default_factory=list)


class ExternalJobEvidence(BaseModel):
    """Portable plugin evidence; accepts neither lifecycle changes nor candidate data.

    No URL is fetched. The caller must supply the actual retrieval time and retain
    the original provider identity when using a connector or web search.
    """

    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=100)
    source_id: str = Field(default="", max_length=1000)
    source_url: str = Field(min_length=1, max_length=4000)
    application_url: str = Field(default="", max_length=4000)
    fetched_at: AwareDatetime
    retrieval_method: Literal[
        "DIRECT_CONNECTOR", "DIRECT_SITE_OR_ATS", "WEB_INDEXED", "PROVIDER_ADAPTER"
    ]
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(default="", max_length=500)
    location: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=100000)
    description_complete: bool = False
    remote_scope: str = "unknown"
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    currency: str | None = None
    salary_period: str | None = None
    salary_is_predicted: bool = False
    salary_text: str = ""
    employment_type: str = "unknown"
    posted_at: AwareDatetime | None = None
    skills: list[str] = Field(default_factory=list, max_length=100)
    country_restrictions: list[str] = Field(default_factory=list, max_length=250)
    http_checks: list[HttpObservation] = Field(default_factory=list, max_length=10)
