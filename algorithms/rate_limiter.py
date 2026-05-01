from __future__ import annotations

import threading
import time
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        enabled: bool,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self.clock = clock or time.time
        self._storage: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds) for a client id."""
        if not self.enabled:
            return True, 0

        now = self.clock()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = [
                ts for ts in self._storage.get(client_id, []) if ts > window_start
            ]
            self._storage[client_id] = timestamps

            if len(timestamps) >= self.max_requests:
                oldest = min(timestamps)
                retry_after = max(1, int(oldest - window_start) + 1)
                return False, retry_after

            timestamps.append(now)
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._storage.clear()
