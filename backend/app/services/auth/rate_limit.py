"""In-memory sliding-window limiter for sign-in attempts (Module 5).

Kept per server process: it slows password guessing from one client address
or against one username without any extra infrastructure. The account
lockout stored on the user row (app.services.auth.sessions) is the durable,
cross-process protection.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.attempts = attempts
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        return hits

    def blocked(self, *keys: str) -> bool:
        now = self.clock()
        with self._lock:
            return any(len(self._prune(key, now)) >= self.attempts for key in keys)

    def hit(self, *keys: str) -> None:
        now = self.clock()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_KEYS:
                # Drop keys with no recent attempts so memory stays bounded.
                stale = [
                    key
                    for key, hits in self._hits.items()
                    if not hits or now - hits[-1] >= self.window
                ]
                for key in stale:
                    del self._hits[key]
            for key in keys:
                self._prune(key, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)