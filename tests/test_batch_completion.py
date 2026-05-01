"""Batch completion webhook checks."""

from algorithms.batch_completion import BatchCompletionDeps, check_batch_completion
from algorithms.job_state import JobStateStore


class _FakeDb:
    available = True

    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url
        self.queries = []

    def _exec(self, query, params=(), fetch=None):
        self.queries.append((query, params, fetch))
        if self.webhook_url:
            return {"webhook_url": self.webhook_url}
        return None


def test_batch_completion_waits_for_all_jobs():
    state = JobStateStore()
    state.set_status("job-a", {"batch_id": "batch-a", "status": "done"})
    state.set_status("job-b", {"batch_id": "batch-a", "status": "rendering"})

    payload = check_batch_completion(
        "batch-a",
        deps=BatchCompletionDeps(job_state=state),
    )

    assert payload is None
    print("[OK] batch completion — waits for unfinished jobs")


def test_batch_completion_delivers_webhook_when_complete():
    state = JobStateStore()
    state.set_status("job-a", {"batch_id": "batch-a", "status": "done"})
    state.set_status("job-b", {"batch_id": "batch-a", "status": "error"})
    db = _FakeDb(webhook_url="https://example.test/hook")
    delivered = []

    payload = check_batch_completion(
        "batch-a",
        deps=BatchCompletionDeps(
            job_state=state,
            db=db,
            deliver_webhook=lambda *args: delivered.append(args),
        ),
    )

    assert payload["status"] == "completed_with_errors"
    assert payload["completed"] == 1
    assert payload["failed"] == 1
    assert delivered[0][1] == "https://example.test/hook"
    print("[OK] batch completion — emits payload and webhook")


if __name__ == "__main__":
    test_batch_completion_waits_for_all_jobs()
    test_batch_completion_delivers_webhook_when_complete()
    print("\nALL BATCH COMPLETION CHECKS PASSED")
