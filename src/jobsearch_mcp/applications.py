"""Submission evidence is separate from discovery and later lifecycle changes."""

from .models import Job, Status

SUBMITTED_STAGES = {
    Status.APPLIED,
    Status.AWAITING_RESPONSE,
    Status.FOLLOW_UP_DUE,
    Status.RECRUITER_SCREEN,
    Status.INTERVIEW,
    Status.TECHNICAL_INTERVIEW,
    Status.FINAL_STAGE,
    Status.OFFER,
}


def application_tracking(job: Job) -> dict:
    recorded = job.submission is not None or job.status in SUBMITTED_STAGES
    return {
        "submission_status": "submitted" if recorded else "unknown",
        "exclude_from_discovery": recorded,
        "lifecycle_status": job.status.value,
        "submission": job.submission.model_dump(mode="json") if job.submission else None,
        "unresolved_same_company_records": job.unresolved_applications,
        "note": (
            "Recorded submission; retain for tracking, not new application preparation."
            if recorded
            else "No submission recorded; this does not prove no application was made elsewhere. "
            "Previously seen roles may still be prepared provisionally."
        ),
    }
