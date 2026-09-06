"""Cross-thread/process lifecycle guard for Latest refresh and server removal."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Callable, Iterator, cast

from core.storage.storage_locks import (
    LATEST_REFRESH_ADVISORY_LOCK_ID,
    enter_latest_refresh_guard,
    exit_latest_refresh_guard,
)
from core.storage.storage_models import text


_process_lock = threading.RLock()


@contextmanager
def latest_refresh_guard(storage: Any | None) -> Iterator[None]:
    """Serialize a complete refresh with destructive server cleanup."""
    with _process_lock:
        get_session = getattr(storage, "_get_session", None)
        if not callable(get_session):
            yield
            return

        guard_session: Any = cast(Callable[[], Any], get_session)()
        try:
            bind = guard_session.get_bind()
            if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
                guard_session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": LATEST_REFRESH_ADVISORY_LOCK_ID},
                )
            enter_latest_refresh_guard()
            try:
                yield
            finally:
                exit_latest_refresh_guard()
            guard_session.commit()
        except Exception:
            guard_session.rollback()
            raise
        finally:
            guard_session.close()


__all__ = ["latest_refresh_guard"]
