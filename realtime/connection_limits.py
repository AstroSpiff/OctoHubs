"""Per-subject connection quotas for long-lived realtime transports."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any


_DEFAULT_LIMIT = 3
_LOCK = threading.Lock()
_COUNTS: dict[tuple[str, str], int] = {}


def auth_subject_id(subject: Any) -> str:
    value = getattr(subject, "id", None)
    if value is None and isinstance(subject, dict):
        value = subject.get("id") or subject.get("user_id")
    if value is None:
        value = subject
    return str(value)


@dataclass
class ConnectionLease:
    key: tuple[str, str]
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        with _LOCK:
            count = _COUNTS.get(self.key, 0)
            if count <= 1:
                _COUNTS.pop(self.key, None)
            else:
                _COUNTS[self.key] = count - 1
        self.released = True


def acquire_connection(subject: Any, channel: str) -> ConnectionLease | None:
    raw_limit = os.environ.get("OCTOHUBS_REALTIME_CONNECTIONS_PER_CHANNEL", "")
    try:
        limit = max(1, min(int(raw_limit or _DEFAULT_LIMIT), 20))
    except ValueError:
        limit = _DEFAULT_LIMIT
    key = (auth_subject_id(subject), channel)
    with _LOCK:
        current = _COUNTS.get(key, 0)
        if current >= limit:
            return None
        _COUNTS[key] = current + 1
    return ConnectionLease(key)


def reset_connection_limits() -> None:
    with _LOCK:
        _COUNTS.clear()
