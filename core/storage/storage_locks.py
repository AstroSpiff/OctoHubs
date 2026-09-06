"""PostgreSQL transaction locks shared by compound storage operations."""

from __future__ import annotations

import threading
from typing import Any

from core.storage.storage_models import text


LATEST_STATE_ADVISORY_LOCK_ID = 4_699_431_785_721_103_117
LATEST_REFRESH_ADVISORY_LOCK_ID = 5_781_201_466_803_244_913
SNAPSHOT_WRITER_LOCK_NAMESPACE = 1_868_787_062
USER_BACKUP_LOCK_NAMESPACE = 1_868_787_063
COLLECTION_DEFINITION_LOCK_NAMESPACE = 1_868_787_064
_latest_refresh_local = threading.local()


def enter_latest_refresh_guard() -> None:
    _latest_refresh_local.depth = int(getattr(_latest_refresh_local, "depth", 0)) + 1


def exit_latest_refresh_guard() -> None:
    depth = int(getattr(_latest_refresh_local, "depth", 0))
    _latest_refresh_local.depth = max(0, depth - 1)


def latest_refresh_guard_held() -> bool:
    return bool(getattr(_latest_refresh_local, "depth", 0))


def lock_latest_state(session: Any) -> None:
    """Serialize canonical Latest state read/modify/write transactions."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": LATEST_STATE_ADVISORY_LOCK_ID},
        )


def lock_latest_refresh(session: Any) -> None:
    """Fence refresh, notification dispatch and destructive server cleanup."""
    if latest_refresh_guard_held():
        return
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": LATEST_REFRESH_ADVISORY_LOCK_ID},
        )


def lock_snapshot_writer(session: Any, key: str) -> None:
    """Serialize replacement of one logical snapshot across app workers."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))"),
            {"namespace": SNAPSHOT_WRITER_LOCK_NAMESPACE, "key": str(key)},
        )


def lock_user_backup_subject(session: Any, key: str) -> None:
    """Serialize insert-and-prune retention for one user's backup category."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))"),
            {"namespace": USER_BACKUP_LOCK_NAMESPACE, "key": str(key)},
        )


def lock_collection_definition(session: Any, definition_id: str) -> None:
    """Serialize one collection definition and its stored assets."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))"),
            {
                "namespace": COLLECTION_DEFINITION_LOCK_NAMESPACE,
                "key": str(definition_id),
            },
        )
