from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class BatchCompletionDeps:
    job_state: Any
    db: Any = None
    deliver_webhook: Callable[..., Any] | None = None


def check_batch_completion(batch_id: str, *, deps: BatchCompletionDeps) -> dict | None:
    """Return a completion payload and deliver a batch webhook when all jobs finish."""
    if not batch_id:
        return None

    summary = deps.job_state.batch_summary(batch_id)
    if not summary.total:
        return None

    if summary.completed + summary.failed < summary.total:
        return None

    payload = {
        "event": "batch.complete",
        "batch_id": batch_id,
        "total": summary.total,
        "completed": summary.completed,
        "failed": summary.failed,
        "status": summary.status,
        "timestamp": datetime.now().isoformat(),
    }

    if deps.db and deps.db.available and deps.deliver_webhook:
        batch = deps.db._exec(
            "SELECT webhook_url FROM batches WHERE id=%s", (batch_id,), fetch="one"
        )
        if batch and batch.get("webhook_url"):
            deps.deliver_webhook(None, batch["webhook_url"], None, batch_id, payload)

    return payload
