"""Thread-safe job/request state helpers."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


TERMINAL_STATUSES = {"done", "error"}
ACTIVE_STATUSES = {"generating", "rendering", "queued"}


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    total: int
    completed: int
    failed: int
    in_progress: int
    progress_percent: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "in_progress": self.in_progress,
            "progress_percent": self.progress_percent,
            "status": self.status,
        }


class JobStateStore:
    """Small synchronized store for render status and original request metadata."""

    def __init__(self) -> None:
        self._statuses: dict[str, dict] = {}
        self._requests: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get_status(self, job_id: str) -> Optional[dict]:
        with self._lock:
            status = self._statuses.get(job_id)
            return deepcopy(status) if status is not None else None

    def set_status(self, job_id: str, status: dict) -> None:
        with self._lock:
            self._statuses[job_id] = deepcopy(status)

    def update_status(self, job_id: str, **updates: Any) -> dict:
        with self._lock:
            current = self._statuses.setdefault(job_id, {})
            current.update(deepcopy(updates))
            return deepcopy(current)

    def get_field(self, job_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._statuses.get(job_id, {}).get(key, default))

    def list_statuses(self) -> list[tuple[str, dict]]:
        with self._lock:
            return [
                (job_id, deepcopy(status)) for job_id, status in self._statuses.items()
            ]

    def get_request(self, job_id: str) -> Optional[dict]:
        with self._lock:
            req = self._requests.get(job_id)
            return deepcopy(req) if req is not None else None

    def set_request(self, job_id: str, request: dict) -> None:
        with self._lock:
            self._requests[job_id] = deepcopy(request)

    def batch_jobs(self, batch_id: str) -> list[tuple[str, dict]]:
        return [
            (job_id, status)
            for job_id, status in self.list_statuses()
            if status.get("batch_id") == batch_id
        ]

    def batch_summary(self, batch_id: str) -> BatchSummary:
        jobs = self.batch_jobs(batch_id)
        total = len(jobs)
        completed = sum(1 for _, status in jobs if status.get("status") == "done")
        failed = sum(1 for _, status in jobs if status.get("status") == "error")
        in_progress = sum(
            1 for _, status in jobs if status.get("status") in ACTIVE_STATUSES
        )
        progress_percent = int((completed + failed) / total * 100) if total else 0
        status = "completed" if total and completed + failed >= total else "in_progress"
        if failed > 0 and total and completed + failed >= total:
            status = "completed_with_errors"
        return BatchSummary(
            batch_id=batch_id,
            total=total,
            completed=completed,
            failed=failed,
            in_progress=in_progress,
            progress_percent=progress_percent,
            status=status,
        )


class PersistentJobStateStore(JobStateStore):
    """JSON-backed job store with the same API as the in-memory store.

    This is deliberately small: it keeps the runtime semantics of JobStateStore
    but survives Flask restarts and marks any previously active jobs as failed,
    because in-process background work cannot resume after process death.
    """

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[JOB_STATE] [WARN] Could not load state: {exc}")
            return

        statuses = payload.get("statuses", {})
        requests = payload.get("requests", {})
        if not isinstance(statuses, dict) or not isinstance(requests, dict):
            print("[JOB_STATE] [WARN] Ignoring malformed state payload")
            return

        with self._lock:
            self._statuses = {
                str(job_id): deepcopy(status)
                for job_id, status in statuses.items()
                if isinstance(status, dict)
            }
            self._requests = {
                str(job_id): deepcopy(request)
                for job_id, request in requests.items()
                if isinstance(request, dict)
            }
            for status in self._statuses.values():
                if status.get("status") in ACTIVE_STATUSES:
                    status["status"] = "error"
                    status.setdefault("video_file", "")
                    status["message"] = "Interrupted by server restart"

        self._persist_unlocked_snapshot()

    def _snapshot_unlocked(self) -> dict[str, dict]:
        return {
            "statuses": {
                job_id: deepcopy(status) for job_id, status in self._statuses.items()
            },
            "requests": {
                job_id: deepcopy(request) for job_id, request in self._requests.items()
            },
        }

    def _persist_unlocked_snapshot(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
            tmp_path.write_text(
                json.dumps(self._snapshot_unlocked(), indent=2, default=str),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        except OSError as exc:
            print(f"[JOB_STATE] [WARN] Could not persist state: {exc}")

    def set_status(self, job_id: str, status: dict) -> None:
        with self._lock:
            self._statuses[job_id] = deepcopy(status)
            self._persist_unlocked_snapshot()

    def update_status(self, job_id: str, **updates: Any) -> dict:
        with self._lock:
            current = self._statuses.setdefault(job_id, {})
            current.update(deepcopy(updates))
            snapshot = deepcopy(current)
            self._persist_unlocked_snapshot()
            return snapshot

    def set_request(self, job_id: str, request: dict) -> None:
        with self._lock:
            self._requests[job_id] = deepcopy(request)
            self._persist_unlocked_snapshot()
