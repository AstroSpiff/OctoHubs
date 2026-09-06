"""Bounded in-process quota for authenticated API tokens."""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, deque


class ApiTokenRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[int, deque[float]] = {}

    def consume(self, token_id: int) -> tuple[bool, int]:
        try:
            limit = int(os.environ.get("API_TOKEN_RATE_LIMIT_PER_MINUTE", "600"))
        except ValueError:
            limit = 600
        limit = max(60, min(limit, 10_000))
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            events = self._events.setdefault(int(token_id), deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(60.0 - (now - events[0])))
                return False, retry_after
            events.append(now)
            if len(self._events) > 10_000:
                stale_ids = [key for key, values in self._events.items() if not values or values[-1] <= cutoff]
                for key in stale_ids:
                    self._events.pop(key, None)
                overflow = len(self._events) - 10_000
                if overflow > 0:
                    oldest_ids = sorted(
                        self._events,
                        key=lambda key: self._events[key][-1],
                    )[:overflow]
                    for key in oldest_ids:
                        self._events.pop(key, None)
            return True, 0


api_token_rate_limiter = ApiTokenRateLimiter()


class ApiTokenPreAuthRateLimiter:
    """Bound invalid Bearer verification attempts before any database lookup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: OrderedDict[str, deque[float]] = OrderedDict()

    def consume(self, client_address: str) -> tuple[bool, int]:
        try:
            limit = int(os.environ.get("API_TOKEN_PREAUTH_RATE_LIMIT_PER_MINUTE", "120"))
        except ValueError:
            limit = 120
        limit = max(10, min(limit, 2_000))
        now = time.monotonic()
        cutoff = now - 60.0
        key = str(client_address or "unknown")
        with self._lock:
            events = self._events.setdefault(key, deque())
            self._events.move_to_end(key)
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False, max(1, int(60.0 - (now - events[0])))
            events.append(now)
            if len(self._events) > 10_000:
                stale = [address for address, values in self._events.items() if not values or values[-1] <= cutoff]
                for address in stale:
                    self._events.pop(address, None)
                while len(self._events) > 10_000:
                    self._events.popitem(last=False)
            return True, 0


api_token_pre_auth_rate_limiter = ApiTokenPreAuthRateLimiter()
