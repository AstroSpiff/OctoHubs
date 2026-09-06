"""Process-wide coordination for Emby server configuration lifecycle changes."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator


_SERVER_CONFIGURATION_LOCK = threading.Lock()


@contextmanager
def server_configuration_guard() -> Iterator[bool]:
    """Serialize create, update, quiesce, and delete as one lifecycle unit."""
    acquired = _SERVER_CONFIGURATION_LOCK.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _SERVER_CONFIGURATION_LOCK.release()


__all__ = ["server_configuration_guard"]
