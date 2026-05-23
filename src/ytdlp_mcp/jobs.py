from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .errors import JobCancelledError, JobNotFoundError
from .job_repository import SQLiteJobRepository
from .policy import Policy

JobCallable = Callable[["JobContext"], dict[str, Any]]


@dataclass(slots=True)
class JobContext:
    job_id: str
    cancel_event: threading.Event
    store: JobStore

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelledError()

    def update_progress(self, progress: dict[str, Any]) -> None:
        self.store.update_progress(self.job_id, progress)

    def append_log(self, level: str, message: str) -> None:
        self.store.append_log(self.job_id, level, message)


@dataclass(slots=True)
class JobRecord:
    job_id: str
    kind: str
    status: str
    created_at: float
    updated_at: float
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    info: dict[str, Any] | None = None
    future: Future[dict[str, Any]] | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public_dict(self, *, include_logs: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "files": self.files,
            "result": self.result,
            "error": self.error,
        }
        if include_logs:
            payload["logs"] = self.logs
        return payload


class JobStore:
    def __init__(self, policy: Policy):
        self._policy = policy
        self._lock = threading.RLock()
        self._records: dict[str, JobRecord] = {}
        self._executor = ThreadPoolExecutor(max_workers=policy.max_concurrent_jobs)
        self._repository = (
            SQLiteJobRepository(policy.resolved_job_db_path)
            if policy.resolved_job_db_path is not None
            else None
        )
        self._restore()

    def submit(self, kind: str, fn: JobCallable) -> JobRecord:
        job_id = uuid.uuid4().hex
        now = time.time()
        record = JobRecord(
            job_id=job_id,
            kind=kind,
            status="queued",
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._records[job_id] = record
            self._persist(record)

        future = self._executor.submit(self._run, job_id, fn)
        with self._lock:
            record.future = future
        return record

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise JobNotFoundError(f"No job exists for job_id={job_id}.")
            return record

    def list(self, *, include_logs: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            records = sorted(self._records.values(), key=lambda item: item.created_at)
            return [record.public_dict(include_logs=include_logs) for record in records]

    def cancel(self, job_id: str) -> JobRecord:
        with self._lock:
            record = self.get(job_id)
            record.cancel_event.set()
            if record.future and record.future.cancel():
                record.status = "cancelled"
                record.updated_at = time.time()
                self._persist(record)
            return record

    def update_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._lock:
            record = self.get(job_id)
            record.progress = _compact_progress(progress)
            record.updated_at = time.time()
            self._persist(record)

    def append_log(self, job_id: str, level: str, message: str) -> None:
        line = {
            "time": time.time(),
            "level": level,
            "message": _redact(message),
        }
        with self._lock:
            record = self.get(job_id)
            record.logs.append(line)
            if len(record.logs) > self._policy.max_log_lines:
                record.logs = record.logs[-self._policy.max_log_lines :]
            record.updated_at = time.time()
            self._persist(record)

    def set_files(self, job_id: str, files: list[str]) -> None:
        with self._lock:
            record = self.get(job_id)
            record.files = files
            record.updated_at = time.time()
            self._persist(record)

    def set_info(self, job_id: str, info: dict[str, Any]) -> None:
        with self._lock:
            record = self.get(job_id)
            record.info = info
            record.updated_at = time.time()
            self._persist(record)

    def _run(self, job_id: str, fn: JobCallable) -> dict[str, Any]:
        context = JobContext(job_id=job_id, cancel_event=self.get(job_id).cancel_event, store=self)
        with self._lock:
            record = self.get(job_id)
            record.status = "running"
            record.updated_at = time.time()
            self._persist(record)

        try:
            result = fn(context)
        except JobCancelledError:
            with self._lock:
                record = self.get(job_id)
                record.status = "cancelled"
                record.error = {"code": "JOB_CANCELLED", "message": "The job was cancelled."}
                record.updated_at = time.time()
                self._persist(record)
            raise
        except Exception as exc:
            with self._lock:
                record = self.get(job_id)
                record.status = "failed"
                record.error = {"code": exc.__class__.__name__, "message": str(exc)}
                record.updated_at = time.time()
                self._persist(record)
            raise

        with self._lock:
            record = self.get(job_id)
            record.status = "succeeded"
            record.result = result
            record.files = list(result.get("files", []))
            if isinstance(result.get("info"), dict):
                record.info = result["info"]
            record.updated_at = time.time()
            self._persist(record)
        return result

    def _restore(self) -> None:
        if self._repository is None:
            return

        now = time.time()
        with self._lock:
            for payload in self._repository.load_all():
                record = _record_from_payload(payload)
                if record.status in {"queued", "running"}:
                    record.status = "failed"
                    record.error = {
                        "code": "JOB_INTERRUPTED",
                        "message": "The server restarted before this job finished.",
                    }
                    record.updated_at = now
                    record.logs.append(
                        {
                            "time": now,
                            "level": "warning",
                            "message": "Job marked failed because the server restarted.",
                        }
                    )
                    self._persist(record)
                self._records[record.job_id] = record

    def _persist(self, record: JobRecord) -> None:
        if self._repository is not None:
            self._repository.save(_record_payload(record))


def _compact_progress(progress: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "status",
        "filename",
        "downloaded_bytes",
        "total_bytes",
        "total_bytes_estimate",
        "speed",
        "eta",
        "elapsed",
        "tmpfilename",
    }
    return {key: _json_safe(progress.get(key)) for key in keys if key in progress}


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _redact(message: str) -> str:
    redacted = str(message)
    sensitive_markers = ("cookie", "authorization", "x-youtube-identity-token", "netrc")
    for marker in sensitive_markers:
        lower = redacted.lower()
        index = lower.find(marker)
        if index >= 0:
            redacted = redacted[:index] + marker + "=<redacted>"
            break
    return redacted


def _record_payload(record: JobRecord) -> dict[str, Any]:
    return {
        "job_id": record.job_id,
        "kind": record.kind,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "progress": record.progress,
        "result": record.result,
        "error": record.error,
        "logs": record.logs,
        "files": record.files,
        "info": record.info,
    }


def _record_from_payload(payload: dict[str, Any]) -> JobRecord:
    return JobRecord(
        job_id=str(payload["job_id"]),
        kind=str(payload["kind"]),
        status=str(payload["status"]),
        created_at=float(payload["created_at"]),
        updated_at=float(payload["updated_at"]),
        progress=dict(payload.get("progress") or {}),
        result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
        error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
        logs=list(payload.get("logs") or []),
        files=list(payload.get("files") or []),
        info=payload.get("info") if isinstance(payload.get("info"), dict) else None,
    )
