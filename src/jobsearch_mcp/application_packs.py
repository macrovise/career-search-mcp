"""Validated, authored application drafts shared by career agents.

The service stores text supplied by a user or ChatGPT. It does not generate,
complete, or infer application content.
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EvidenceReference(BaseModel):
    """A caller-supplied pointer to evidence used in the draft."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["job", "profile", "user", "other"]
    reference: str = Field(min_length=1, max_length=2000)
    excerpt: str = Field(default="", max_length=5000)


class ScreeningAnswer(BaseModel):
    """A screening question and an optional authored answer."""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    answer: str | None = Field(default=None, max_length=10000)
    unresolved: bool = False

    @model_validator(mode="after")
    def unresolved_has_no_answer(self):
        if self.unresolved and self.answer:
            raise ValueError("An unresolved screening question cannot have an answer")
        if not self.unresolved and not self.answer:
            raise ValueError("A screening question without an answer must be unresolved")
        return self


class ApplicationPackDraft(BaseModel):
    """Application text authored outside this evidence-only service."""

    model_config = ConfigDict(extra="forbid")
    author: Literal["user", "chatgpt"]
    cv_variant: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=20000)
    resume_bullets: list[str] = Field(default_factory=list, max_length=100)
    cover_letter: str = Field(default="", max_length=50000)
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list, max_length=100)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=100)
    evidence_references: list[EvidenceReference] = Field(default_factory=list, max_length=250)


class ApplicationPack(ApplicationPackDraft):
    """One immutable saved revision with its evidence basis."""

    job_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    saved_at: AwareDatetime
    job_evidence_fingerprint: str = Field(min_length=64, max_length=64)
    profile_evidence_fingerprint: str = Field(min_length=64, max_length=64)
    job_evidence_stale: bool = False
    profile_evidence_stale: bool = False

    @classmethod
    def saved(
        cls,
        *,
        draft: ApplicationPackDraft,
        job_id: str,
        revision: int,
        saved_at: datetime,
        job_fingerprint: str,
        profile_fingerprint: str,
    ) -> "ApplicationPack":
        return cls(
            **draft.model_dump(),
            job_id=job_id,
            revision=revision,
            saved_at=saved_at,
            job_evidence_fingerprint=job_fingerprint,
            profile_evidence_fingerprint=profile_fingerprint,
        )
