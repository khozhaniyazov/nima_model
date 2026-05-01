"""Smoke tests for the background job dispatcher."""

import threading
import time

from algorithms.job_dispatcher import BackgroundDispatcher


def test_dispatcher_runs_and_cleans_up():
    dispatcher = BackgroundDispatcher()
    observed = []

    thread = dispatcher.submit(lambda: observed.append("done"), name="unit-dispatch")
    thread.join(timeout=2)

    assert observed == ["done"]
    assert dispatcher.active_count() == 0
    assert dispatcher.active_names() == []
    print("[OK] background dispatcher — ran job and cleaned up")


def test_dispatcher_limits_concurrent_running_jobs():
    dispatcher = BackgroundDispatcher(max_concurrent=1)
    first_started = threading.Event()
    release_first = threading.Event()
    observed = []

    def first_job():
        observed.append("first-start")
        first_started.set()
        release_first.wait(timeout=2)
        observed.append("first-end")

    def second_job():
        observed.append("second-start")

    first = dispatcher.submit(first_job, name="first")
    second = dispatcher.submit(second_job, name="second")

    assert first_started.wait(timeout=2)
    time.sleep(0.1)
    assert dispatcher.running_count() == 1
    assert dispatcher.queued_count() == 1
    assert observed == ["first-start"]

    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert observed == ["first-start", "first-end", "second-start"]
    assert dispatcher.active_count() == 0
    assert dispatcher.running_count() == 0
    assert dispatcher.queued_count() == 0
    print("[OK] background dispatcher — concurrency limit queues jobs")


def test_dispatcher_survives_failed_task():
    dispatcher = BackgroundDispatcher(max_concurrent=1)
    observed = []

    def fail():
        raise RuntimeError("boom")

    failed = dispatcher.submit(fail, name="fail")
    failed.join(timeout=2)
    second = dispatcher.submit(lambda: observed.append("after"), name="after")
    second.join(timeout=2)

    assert isinstance(failed.exception, RuntimeError)
    assert observed == ["after"]
    assert dispatcher.active_count() == 0
    print("[OK] background dispatcher — failed task does not kill worker")


if __name__ == "__main__":
    test_dispatcher_runs_and_cleans_up()
    test_dispatcher_limits_concurrent_running_jobs()
    test_dispatcher_survives_failed_task()
    print("\nALL DISPATCHER CHECKS PASSED")
