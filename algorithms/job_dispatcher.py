from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackgroundTask:
    handle: str
    name: str
    target: Callable[..., Any]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    exception: BaseException | None = None

    def join(self, timeout: float | None = None) -> None:
        self.done.wait(timeout=timeout)

    def is_alive(self) -> bool:
        return not self.done.is_set()


class BackgroundDispatcher:
    """Fixed-size in-process worker queue for background jobs.

    This is still not a durable external queue, but it avoids unbounded thread
    creation and gives the Flask app one measurable boundary for queued vs.
    running work.
    """

    def __init__(self, max_concurrent: int | None = 4) -> None:
        worker_count = max(1, int(max_concurrent or 4))
        self._lock = threading.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._running: set[str] = set()
        self._queue: queue.Queue[BackgroundTask] = queue.Queue()
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"nima-bg-worker-{i + 1}",
                daemon=True,
            )
            for i in range(worker_count)
        ]
        for worker in self._workers:
            worker.start()

    def submit(
        self,
        target: Callable[..., Any],
        *,
        name: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        daemon: bool = True,
    ) -> BackgroundTask:
        del daemon  # Worker threads own daemon behavior.
        handle = uuid.uuid4().hex
        task = BackgroundTask(
            handle=handle,
            name=name or f"nima-bg-{handle[:8]}",
            target=target,
            args=args,
            kwargs=dict(kwargs or {}),
        )
        with self._lock:
            self._tasks[handle] = task
        self._queue.put(task)
        return task

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            with self._lock:
                self._running.add(task.handle)
            try:
                task.result = task.target(*task.args, **task.kwargs)
            except Exception as exc:
                task.exception = exc
                print(f"[DISPATCH] [ERR] Background job {task.name} failed: {exc}")
            finally:
                with self._lock:
                    self._running.discard(task.handle)
                    self._tasks.pop(task.handle, None)
                task.done.set()
                self._queue.task_done()

    def active_count(self) -> int:
        with self._lock:
            return len(self._tasks)

    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def queued_count(self) -> int:
        with self._lock:
            return max(0, len(self._tasks) - len(self._running))

    def active_names(self) -> list[str]:
        with self._lock:
            return [task.name for task in self._tasks.values() if task.is_alive()]
