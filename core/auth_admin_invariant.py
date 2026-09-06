"""Serialize mutations that could remove the last active administrator."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

from sqlalchemy import text


_PROCESS_ADMIN_MUTATION_LOCK = threading.RLock()
_POSTGRES_ADMIN_LOCK_ID = 5711514714793194067


@contextmanager
def active_admin_mutation_guard(session: Any) -> Iterator[None]:
    """Hold a process lock and, on PostgreSQL, a transaction advisory lock."""
    with _PROCESS_ADMIN_MUTATION_LOCK:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite" and session.in_transaction():
            session.rollback()
        if dialect == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _POSTGRES_ADMIN_LOCK_ID},
            )
        yield


__all__ = ["active_admin_mutation_guard"]
