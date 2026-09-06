"""Constant-work password checks and bounded login-attempt throttling."""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Callable

import bcrypt

from core.password_policy import PasswordTooLongError, bcrypt_password_bytes
from core.client_address import resolve_client_address


_DUMMY_PASSWORD = b"octohubs-login-dummy-password"
_DUMMY_PASSWORD_HASH = b"$2b$12$oyRhoXUPOLd3r40DAx0Tg.qTxruvtdsIv17rrsU/Ourr0MnoWBPX2"


@dataclass(frozen=True)
class LoginRateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class LoginAttemptLimiter:
    """Thread-safe sliding-window limiter with a bounded number of identities."""

    def __init__(
        self,
        *,
        window_seconds: int = 300,
        per_ip_attempts: int = 20,
        per_identity_attempts: int = 5,
        max_buckets: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.per_ip_attempts = max(1, int(per_ip_attempts))
        self.per_identity_attempts = max(1, int(per_identity_attempts))
        self.max_buckets = max(2, int(max_buckets))
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _identity_key(address: str, username: str) -> str:
        normalized = str(username or "").strip().casefold()[:80]
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"identity:{address}:{digest}"

    def _active_events(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        self._events.move_to_end(key)
        return events

    def _evict_expired(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events:
            key, events = next(iter(self._events.items()))
            if events and events[-1] > cutoff:
                break
            self._events.pop(key, None)

    def consume(self, address: str, username: str) -> LoginRateLimitDecision:
        """Consume one login attempt or return when the caller may retry."""
        now = self._clock()
        keys_and_limits = (
            (f"ip:{address}", self.per_ip_attempts),
            (self._identity_key(address, username), self.per_identity_attempts),
        )
        with self._lock:
            self._evict_expired(now)
            buckets = [
                (self._active_events(key, now), limit)
                for key, limit in keys_and_limits
            ]
            blocked_until = [
                events[0] + self.window_seconds
                for events, limit in buckets
                if len(events) >= limit
            ]
            if blocked_until:
                while len(self._events) > self.max_buckets:
                    self._events.popitem(last=False)
                retry_after = max(1, math.ceil(max(blocked_until) - now))
                return LoginRateLimitDecision(False, retry_after)

            for events, _limit in buckets:
                events.append(now)
            while len(self._events) > self.max_buckets:
                self._events.popitem(last=False)
        return LoginRateLimitDecision(True)

    def clear_identity(self, address: str, username: str) -> None:
        """Clear a successful account's narrow bucket while preserving its IP cap."""
        with self._lock:
            self._events.pop(self._identity_key(address, username), None)


def login_password_matches(user: Any, password: str) -> bool:
    """Perform exactly one normal bcrypt check for valid and invalid accounts."""
    try:
        candidate = bcrypt_password_bytes(str(password or ""))
        invalid_length = False
    except PasswordTooLongError:
        candidate = _DUMMY_PASSWORD
        invalid_length = True

    active_user = user is not None and bool(getattr(user, "is_active", False))
    password_hash = str(getattr(user, "password_hash", "") or "") if active_user else ""
    encoded_hash = password_hash.encode("utf-8")
    if len(encoded_hash) != 60 or not encoded_hash.startswith((b"$2a$", b"$2b$", b"$2y$")):
        encoded_hash = _DUMMY_PASSWORD_HASH
        active_user = False

    try:
        matches = bcrypt.checkpw(candidate, encoded_hash)
    except (TypeError, ValueError):
        matches = bcrypt.checkpw(candidate, _DUMMY_PASSWORD_HASH)
        active_user = False
    return bool(active_user and not invalid_length and matches)


def login_client_address(request: Any) -> str:
    """Resolve a bounded, normalized address key for login throttling."""
    return resolve_client_address(request)


def _environment_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(key, default)).strip())
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


_limiter: LoginAttemptLimiter | None = None
_limiter_lock = threading.Lock()


def get_login_attempt_limiter() -> LoginAttemptLimiter:
    """Create the process-local limiter lazily, after runtime env loading."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = LoginAttemptLimiter(
                    window_seconds=_environment_int(
                        "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300, 10, 3600
                    ),
                    per_ip_attempts=_environment_int(
                        "LOGIN_RATE_LIMIT_IP_ATTEMPTS", 20, 1, 1000
                    ),
                    per_identity_attempts=_environment_int(
                        "LOGIN_RATE_LIMIT_USERNAME_ATTEMPTS", 5, 1, 1000
                    ),
                )
    return _limiter
