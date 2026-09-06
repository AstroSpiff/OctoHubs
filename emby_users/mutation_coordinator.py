"""Cross-thread and cross-process fences for Emby user mutations."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import threading
from typing import Any, Iterable, Iterator


_LOCKS_GUARD = threading.Lock()


@dataclass
class _LockEntry:
    lock: Any
    references: int = 0


_LOCKS: dict[str, _LockEntry] = {}
_HELD_KEYS = threading.local()


def group_sync_key(group_id: str) -> str:
    return f"user-sync:{str(group_id or '').strip()}"


def server_mutation_key(server_id: str) -> str:
    """Fence every remote/user mutation against deletion of one Emby server."""
    return f"emby-server-mutation:{str(server_id or '').strip()}"


def user_mutation_key(server_id: str, user_id: str) -> str:
    return f"emby-user-mutation:{str(server_id or '').strip()}:{str(user_id or '').strip()}"


def user_mutation_keys(server_id: str, user_id: str) -> tuple[str, str]:
    """Return the canonical server-wide and per-user mutation fences."""
    return server_mutation_key(server_id), user_mutation_key(server_id, user_id)


def _held_key_counts() -> dict[str, int]:
    counts = getattr(_HELD_KEYS, "counts", None)
    if counts is None:
        counts = {}
        _HELD_KEYS.counts = counts
    return counts


@contextmanager
def _local_lock(key: str) -> Iterator[tuple[bool, bool]]:
    """Acquire one ref-counted local lock and report whether this is outermost."""
    with _LOCKS_GUARD:
        entry = _LOCKS.get(key)
        if entry is None:
            entry = _LockEntry(threading.RLock())
            _LOCKS[key] = entry
        entry.references += 1

    acquired = entry.lock.acquire(blocking=False)
    if not acquired:
        with _LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and _LOCKS.get(key) is entry:
                _LOCKS.pop(key, None)
        yield False, False
        return

    counts = _held_key_counts()
    outermost = counts.get(key, 0) == 0
    counts[key] = counts.get(key, 0) + 1
    try:
        yield True, outermost
    finally:
        remaining = counts.get(key, 1) - 1
        if remaining:
            counts[key] = remaining
        else:
            counts.pop(key, None)
        entry.lock.release()
        with _LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and _LOCKS.get(key) is entry:
                _LOCKS.pop(key, None)


class UserMutationCoordinator:
    """Acquire the same ordered keys locally and in PostgreSQL."""

    def __init__(self, storage: Any):
        self.storage = storage

    @contextmanager
    def guard(self, keys: Iterable[str]) -> Iterator[bool]:
        ordered = sorted({str(key).strip() for key in keys if str(key).strip()})
        with ExitStack() as stack:
            outermost_keys: list[str] = []
            for key in ordered:
                acquired, outermost = stack.enter_context(_local_lock(key))
                if not acquired:
                    yield False
                    return
                if not outermost and key.startswith("user-sync:"):
                    # A nested group sync is a competing logical operation even
                    # when invoked on the same thread. Server/user fences are
                    # reentrant so coordinated domain managers can compose.
                    yield False
                    return
                if outermost:
                    outermost_keys.append(key)

            lock_factory = getattr(self.storage, "advisory_lock", None)
            if callable(lock_factory):
                # PostgreSQL advisory locks are acquired only by the outermost
                # guard for a key. Nested domain managers in the same thread are
                # already protected by that owner's local and database fence.
                for key in outermost_keys:
                    acquired = stack.enter_context(lock_factory(key))
                    if not acquired:
                        yield False
                        return
            yield True


__all__ = [
    "UserMutationCoordinator",
    "group_sync_key",
    "server_mutation_key",
    "user_mutation_key",
    "user_mutation_keys",
]
