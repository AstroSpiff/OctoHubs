"""Concurrent connection leases for the authenticated Event Bridge transport."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass


_DEFAULT_GLOBAL_LIMIT = 64
_DEFAULT_PER_SERVER_LIMIT = 3
_LOCK = threading.Lock()
_GLOBAL_COUNT = 0
_SERVER_COUNTS: dict[str, int] = {}


def _bounded_limit(name: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(os.environ.get(name, "") or default), maximum))
    except ValueError:
        return default


@dataclass
class EventBridgeConnectionLease:
    server_id: str
    released: bool = False

    def release(self) -> None:
        global _GLOBAL_COUNT
        if self.released:
            return
        with _LOCK:
            _GLOBAL_COUNT = max(0, _GLOBAL_COUNT - 1)
            count = _SERVER_COUNTS.get(self.server_id, 0)
            if count <= 1:
                _SERVER_COUNTS.pop(self.server_id, None)
            else:
                _SERVER_COUNTS[self.server_id] = count - 1
        self.released = True


def acquire_event_bridge_connection(server_id: str) -> EventBridgeConnectionLease | None:
    """Reserve one bounded live connection for an authenticated server."""
    global _GLOBAL_COUNT
    clean_server_id = str(server_id or "").strip()
    if not clean_server_id:
        return None
    global_limit = _bounded_limit(
        "OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_GLOBAL",
        _DEFAULT_GLOBAL_LIMIT,
        1024,
    )
    server_limit = _bounded_limit(
        "OCTOHUBS_EVENT_BRIDGE_CONNECTIONS_PER_SERVER",
        _DEFAULT_PER_SERVER_LIMIT,
        20,
    )
    with _LOCK:
        if _GLOBAL_COUNT >= global_limit:
            return None
        current = _SERVER_COUNTS.get(clean_server_id, 0)
        if current >= server_limit:
            return None
        _GLOBAL_COUNT += 1
        _SERVER_COUNTS[clean_server_id] = current + 1
    return EventBridgeConnectionLease(clean_server_id)


def reset_event_bridge_connection_limits() -> None:
    """Clear process-local leases for isolated tests and lifespan resets."""
    global _GLOBAL_COUNT
    with _LOCK:
        _GLOBAL_COUNT = 0
        _SERVER_COUNTS.clear()
