"""Small in-memory sliding-window rate limiter (per client IP)."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

from starlette.requests import Request

WINDOW_S = 60.0
MAX_TRACKED_CLIENTS = 10_000


class RateLimiter:
    def __init__(
        self,
        limit: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_TRACKED_CLIENTS:
                self._evict(now)
            hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > WINDOW_S:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _evict(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] > WINDOW_S]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= MAX_TRACKED_CLIENTS:  # still full: drop oldest quarter
            for key in list(self._hits)[: MAX_TRACKED_CLIENTS // 4]:
                del self._hits[key]


def client_ip(request: Request) -> str:
    """Client address. Behind Cloud Run the trusted hop appends the real IP last."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last[:64]
    return request.client.host if request.client else "unknown"
