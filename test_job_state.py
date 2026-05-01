"""Job state store persistence checks."""

import json
import tempfile
from pathlib import Path

from algorithms.job_state import JobStateStore, PersistentJobStateStore


def test_in_memory_job_state_returns_copies():
    state = JobStateStore()
    original = {"status": "done", "nested": {"x": 1}}
    state.set_status("job-1", original)
    original["nested"]["x"] = 99

    snapshot = state.get_status("job-1")
    snapshot["status"] = "mutated"
    snapshot["nested"]["x"] = 2

    assert state.get_status("job-1")["status"] == "done"
    assert state.get_status("job-1")["nested"]["x"] == 1
    assert state.get_field("job-1", "nested") == {"x": 1}
    print("[OK] job state - in-memory snapshots are isolated")


def test_persistent_job_state_survives_restart_and_marks_active_failed():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "job_state.json"
        state = PersistentJobStateStore(path)
        state.set_status("job-active", {"status": "rendering", "batch_id": "batch-1"})
        state.set_status("job-done", {"status": "done", "video_file": "done.mp4"})
        state.set_request("job-done", {"prompt": "Explain vectors"})

        reloaded = PersistentJobStateStore(path)

        assert reloaded.get_status("job-active")["status"] == "error"
        assert (
            reloaded.get_status("job-active")["message"]
            == "Interrupted by server restart"
        )
        assert reloaded.get_status("job-done")["video_file"] == "done.mp4"
        assert reloaded.get_request("job-done")["prompt"] == "Explain vectors"
        assert reloaded.batch_summary("batch-1").failed == 1
        print("[OK] job state - persistent restart handling works")


def test_persistent_job_state_ignores_malformed_payload():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "job_state.json"
        path.write_text(json.dumps({"statuses": [], "requests": {}}), encoding="utf-8")

        state = PersistentJobStateStore(path)

        assert state.list_statuses() == []
        print("[OK] job state - malformed persistent payload ignored")


if __name__ == "__main__":
    test_in_memory_job_state_returns_copies()
    test_persistent_job_state_survives_restart_and_marks_active_failed()
    test_persistent_job_state_ignores_malformed_payload()
    print("\nALL JOB STATE CHECKS PASSED")
