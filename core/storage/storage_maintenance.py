"""Maintenance storage operations."""

from __future__ import annotations

from typing import Any, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    LibraryAssociation,
    EmbyProbeBlacklist,
    EmbyProbeQueue,
    EmbyProbeHistory,
    EmbyProbeRecentScan,
    EmbyUserLink,
    EmbyUserBackup,
    EmbyLatestNotificationDelivery,
    EmbyIconRule,
    EmbyIconBinding,
    KeyValueEntry,
    or_,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageMaintenanceMixin(_SessionProvider):
    def remove_emby_server_data(self, server_id: str) -> None:
        """Remove all Emby-related records tied to a server_id."""
        session = self._get_session()
        try:
            session.query(EmbyLatestNotificationDelivery).filter(  # type: ignore[attr-defined]
                EmbyLatestNotificationDelivery.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(LibraryAssociation).filter(  # type: ignore[attr-defined]
                LibraryAssociation.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeBlacklist).filter(  # type: ignore[attr-defined]
                EmbyProbeBlacklist.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeQueue).filter(  # type: ignore[attr-defined]
                EmbyProbeQueue.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeHistory).filter(  # type: ignore[attr-defined]
                EmbyProbeHistory.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                EmbyProbeRecentScan.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyUserLink).filter(  # type: ignore[attr-defined]
                EmbyUserLink.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyUserBackup).filter(  # type: ignore[attr-defined]
                EmbyUserBackup.server_id == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconRule).filter(  # type: ignore[attr-defined]
                EmbyIconRule.column_key == server_id
            ).delete(synchronize_session=False)
            session.query(EmbyIconBinding).filter(  # type: ignore[attr-defined]
                EmbyIconBinding.target_type == "user",
                EmbyIconBinding.target_id.like(f"{server_id}:%")
            ).delete(synchronize_session=False)
            session.query(KeyValueEntry).filter(  # type: ignore[attr-defined]
                or_(
                    KeyValueEntry.key == f"library_scan_state:{server_id}",
                    KeyValueEntry.key.like(f"library_scan_state:{server_id}:%")
                )
            ).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore rimozione dati server Emby: {exc}") from exc
        finally:
            session.close()
