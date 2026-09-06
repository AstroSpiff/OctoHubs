"""Coordination for tracked scan admission and destructive state resets."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator


_SCAN_LIFECYCLE_LOCK = threading.Lock()


@contextmanager
def scan_lifecycle_guard() -> Iterator[bool]:
    """Keep reserve, remote trigger, and poller scheduling atomic against reset."""
    acquired = _SCAN_LIFECYCLE_LOCK.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _SCAN_LIFECYCLE_LOCK.release()


__all__ = ["scan_lifecycle_guard"]
