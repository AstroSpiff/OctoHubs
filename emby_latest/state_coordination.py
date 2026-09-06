"""Cross-thread/process serialization for compound Latest state updates."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

from core.sqlalchemy_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_locks import lock_latest_state


_process_lock = threading.RLock()


@contextmanager
def latest_state_update_guard(storage: Any | None) -> Iterator[None]:
    """Serialize read/modify/write state changes, including across PostgreSQL workers."""
    with _process_lock:
        get_session = getattr(storage, "_get_session", None)
        if not callable(get_session):
            yield
            return

        guard_session: Any = get_session()
        try:
            bind = guard_session.get_bind()
            if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
                lock_latest_state(guard_session)
            yield
            guard_session.commit()
        except BaseException:
            rollback_session_safely(guard_session, context="Latest state guard")
            raise
        finally:
            close_session_safely(guard_session, context="Latest state guard")


__all__ = ["latest_state_update_guard"]
