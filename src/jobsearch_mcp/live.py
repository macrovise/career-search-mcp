"""Request-local deduplication and bounded, temporary live-result references."""

import hashlib
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from uuid import uuid4

from .models import Job
from .store import find_duplicate, identity_keys, merge_records


class JobBatch:
    """Combine this response's source records without touching the saved database."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.identities: dict[str, str] = {}

    def add(self, job: Job):
        def lookup(key):
            return self.jobs.get(self.identities.get(key, ""))

        existing = find_duplicate(job, lookup)
        keys = identity_keys(job)
        if existing is not None:
            result = merge_records(existing, job)
        else:
            now = datetime.now(UTC)
            result = job.model_copy(
                update={
                    "id": hashlib.sha256(keys[0].encode()).hexdigest()[:24],
                    "first_seen": now,
                    "last_seen": now,
                }
            )
        self.jobs[result.id] = result
        for key in keys:
            self.identities.setdefault(key, result.id)


class LiveResults:
    """Allow read-only follow-up tools to resolve live jobs for up to 15 minutes.

    These are response snapshots, not a source cache: every live search still
    fetches providers anew. Nothing survives a server restart or reaches disk.
    """

    TTL_SECONDS = 900
    MAX_JOBS = 500

    def __init__(self):
        self._jobs: OrderedDict[str, tuple[float, Job, str | None]] = OrderedDict()
        self._lock = threading.RLock()

    def _prune(self):
        now = time.monotonic()
        for key, (expires, _, _) in list(self._jobs.items()):
            if expires <= now:
                del self._jobs[key]
        while len(self._jobs) > self.MAX_JOBS:
            self._jobs.popitem(last=False)

    def add(self, job: Job, saved_job_id: str | None = None) -> Job:
        result = job.model_copy(deep=True, update={"id": "live:" + uuid4().hex})
        with self._lock:
            self._jobs[result.id] = (
                time.monotonic() + self.TTL_SECONDS,
                result,
                saved_job_id,
            )
            self._prune()
        return result.model_copy(deep=True)

    def resolve(self, job_id: str) -> tuple[Job, str | None]:
        with self._lock:
            self._prune()
            if job_id not in self._jobs:
                raise ValueError("Live result expired or unavailable; run search_live_jobs again")
            _, job, saved_job_id = self._jobs[job_id]
            return job.model_copy(deep=True), saved_job_id
