"""Background jobs: renders run one at a time (one GPU) and report progress the UI can poll."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Status = Literal["queued", "running", "done", "failed"]
Report = Callable[[int, int, str], None]
log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    status: Status = "queued"
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": {"done": self.done, "total": self.total, "message": self.message},
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
        }


class JobManager:
    def __init__(self, max_jobs_kept: int = 50):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max = max_jobs_kept

    def submit(self, kind: str, work: Callable[[Report], dict[str, Any]]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            for old in list(self._jobs)[: max(0, len(self._jobs) - self._max)]:
                if self._jobs[old].status in ("done", "failed"):
                    del self._jobs[old]

        def report(done: int, total: int, message: str) -> None:
            job.done, job.total, job.message = done, total, message

        def run() -> None:
            job.status = "running"
            try:
                job.result = work(report)
                job.status = "done"
            except Exception as exc:  # the message is shown to the user; the traceback goes to the log
                log.exception("Job %s failed", job.id)
                job.error = str(exc) or exc.__class__.__name__
                job.status = "failed"

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def busy(self) -> bool:
        """True while a job is queued or running (the instance must not auto-stop)."""
        with self._lock:
            return any(job.status in ("queued", "running") for job in self._jobs.values())

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
