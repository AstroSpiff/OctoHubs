"""Emby probe storage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, cast

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    EmbyProbeBlacklist,
    EmbyProbeQueue,
    EmbyProbeHistory,
    EmbyProbeRecentScan,
    _utcnow,
    or_,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class _KeyValueProvider(Protocol):
    def get_key_value(self, key: str) -> Optional[Any]: ...
    def set_key_value(self, key: str, value: Any) -> None: ...


class StorageProbeMixin(_SessionProvider):
    def _normalize_probe_scope(self, scope: Optional[str]) -> str:
        value = (scope or "").strip().lower()
        if value in ("recent", "libraries"):
            return value
        return "libraries"

    def _apply_scope_filter(self, query, model, scope: Optional[str]):
        if not scope:
            return query
        normalized = self._normalize_probe_scope(scope)
        if normalized == "libraries":
            return query.filter(or_(model.scope == normalized, model.scope.is_(None)))  # type: ignore[attr-defined]
        return query.filter(model.scope == normalized)  # type: ignore[attr-defined]

    def load_probe_blacklist(self, server_id: str, scope: Optional[str] = None) -> Dict[str, Any]:
        session = self._get_session()
        try:
            entries = (
                session.query(EmbyProbeBlacklist)
                .filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
            )
            entries = self._apply_scope_filter(entries, EmbyProbeBlacklist, scope).all()
            # Use composite key: item_id + media_source_id to handle multi-source items
            return {
                f"{entry.item_id}:{entry.media_source_id or ''}": {
                    "item_id": entry.item_id,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count,
                    "error_type": entry.error_type or "ERROR"
                }
                for entry in entries
            }
        finally:
            session.close()

    def update_probe_blacklist(
        self,
        server_id: str,
        item_id: str,
        name: str,
        reason: str,
        media_source_id: Optional[str] = None,
        increment_retry: bool = True,
        error_type: Optional[str] = None,
        scope: Optional[str] = None,
        library_id: Optional[str] = None,
        library_name: Optional[str] = None
    ) -> int:
        session = self._get_session()
        try:
            scope_value = self._normalize_probe_scope(scope)
            entry = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            ).first()

            if entry:
                entry.scope = scope_value  # type: ignore[assignment]
                entry.item_name = name  # type: ignore[assignment]
                entry.reason = reason  # type: ignore[assignment]
                entry.failed_at = _utcnow()  # type: ignore[assignment]
                entry.media_source_id = media_source_id  # type: ignore[assignment]
                entry.library_id = library_id  # type: ignore[assignment]
                entry.library_name = library_name  # type: ignore[assignment]
                entry.error_type = error_type or entry.error_type  # type: ignore[assignment]
                if increment_retry:
                    entry.retry_count += 1  # type: ignore[assignment]
                retry_count = int(entry.retry_count)  # type: ignore[arg-type]
            else:
                retry_count_value = 1 if increment_retry else 0
                new_entry = EmbyProbeBlacklist(
                    server_id=server_id,
                    item_id=item_id,
                    scope=scope_value,
                    media_source_id=media_source_id,
                    library_id=library_id,
                    library_name=library_name,
                    item_name=name,
                    reason=reason,
                    retry_count=retry_count_value,
                    error_type=error_type
                )
                session.add(new_entry)
                retry_count = retry_count_value

            session.commit()
            return retry_count
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiornamento blacklist probe: {exc}") from exc
        finally:
            session.close()

    def remove_from_probe_blacklist(
        self,
        server_id: str,
        item_id: str,
        media_source_id: Optional[str] = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dalla blacklist probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_blacklist(
        self,
        server_id: Optional[str] = None,
        min_retry_count: int = 0,
        error_type: Optional[str] = None,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """Get blacklist entries as a list, optionally filtered by server and retry count."""
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist)
            if server_id:
                query = query.filter(EmbyProbeBlacklist.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            if min_retry_count > 0:
                query = query.filter(EmbyProbeBlacklist.retry_count >= min_retry_count)  # type: ignore[attr-defined]

            entries = query.order_by(EmbyProbeBlacklist.failed_at.desc()).all()  # type: ignore[attr-defined]

            def _normalize_error_type(entry: EmbyProbeBlacklist) -> str:
                # Convert Column to str to avoid conditional issues
                error_type_str = str(entry.error_type) if entry.error_type is not None else ""
                if error_type_str:
                    return error_type_str
                reason_str = str(entry.reason) if entry.reason is not None else ""
                reason = reason_str.lower()
                if "mediainfo" in reason or "metadati" in reason or "metadata" in reason:
                    return "INCOMPLETE"
                return "ERROR"

            if error_type:
                normalized_type = error_type.upper()
                entries = [entry for entry in entries if _normalize_error_type(entry) == normalized_type]

            return [
                {
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "scope": entry.scope,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "item_name": entry.item_name,
                    "failed_at": entry.failed_at.isoformat() if entry.failed_at else None,
                    "reason": entry.reason,
                    "retry_count": entry.retry_count,
                    "error_type": _normalize_error_type(entry)
                }
                for entry in entries
            ]
        finally:
            session.close()

    def clear_probe_blacklist(
        self,
        server_id: str,
        error_type: Optional[str] = None,
        scope: Optional[str] = None
    ) -> None:
        """Clear all blacklist entries for a server, optionally filtered by error type."""
        session = self._get_session()
        try:
            query = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope)
            if not error_type:
                query.delete()
                session.commit()
                return

            normalized_type = error_type.upper()
            entries = query.all()

            def _normalize_error_type(entry: EmbyProbeBlacklist) -> str:
                # Convert Column to str to avoid conditional issues
                error_type_str = str(entry.error_type) if entry.error_type is not None else ""
                if error_type_str:
                    return error_type_str
                reason_str = str(entry.reason) if entry.reason is not None else ""
                reason = reason_str.lower()
                if "mediainfo" in reason or "metadati" in reason or "metadata" in reason:
                    return "INCOMPLETE"
                return "ERROR"

            for entry in entries:
                if _normalize_error_type(entry) == normalized_type:
                    session.delete(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento blacklist probe: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe Queue ---

    def add_to_probe_queue(self, items: list[Dict[str, Any]]) -> None:
        session = self._get_session()
        try:
            for item_data in items:
                server_id = item_data.get("server_id")
                item_id = item_data.get("item_id")
                media_source_id = item_data.get("media_source_id")
                scope_value = self._normalize_probe_scope(item_data.get("scope"))

                if not server_id or not item_id:
                    continue

                # Check if already exists
                existing_query = session.query(EmbyProbeQueue).filter(
                    EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
                )
                existing_query = self._apply_scope_filter(existing_query, EmbyProbeQueue, scope_value)
                if media_source_id is not None:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id == media_source_id)  # type: ignore[attr-defined]
                else:
                    existing_query = existing_query.filter(EmbyProbeQueue.media_source_id.is_(None))  # type: ignore[attr-defined]
                existing = existing_query.first()

                if media_source_id is not None:
                    query = session.query(EmbyProbeQueue).filter(
                        EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.item_id == item_id,  # type: ignore[attr-defined]
                        EmbyProbeQueue.media_source_id.is_(None)  # type: ignore[attr-defined]
                    )
                    query = self._apply_scope_filter(query, EmbyProbeQueue, scope_value)
                    query.delete(synchronize_session=False)

                if existing:
                    continue  # Skip duplicates

                new_entry = EmbyProbeQueue(
                    server_id=server_id,
                    item_id=item_id,
                    scope=scope_value,
                    media_source_id=media_source_id,
                    library_id=item_data.get("library_id"),
                    library_name=item_data.get("library_name"),
                    name=item_data.get("name", "Sconosciuto"),
                    series_name=item_data.get("series_name"),
                    season_number=item_data.get("season_number"),
                    episode_number=item_data.get("episode_number"),
                    year=item_data.get("year"),
                    media_type=item_data.get("media_type"),
                    path=item_data.get("path")
                )
                session.add(new_entry)

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta elementi alla coda probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_queue(
        self,
        server_id: Optional[str] = None,
        library_ids: Optional[list[str]] = None,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue)

            if server_id:
                query = query.filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)

            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]

            # Sort order depends on scope
            normalized_scope = self._normalize_probe_scope(scope)
            if normalized_scope == "recent":
                # For recent scope: process oldest items first (ASC by added_at)
                query = query.order_by(
                    EmbyProbeQueue.added_at.asc()  # type: ignore[attr-defined]
                )
            else:
                # For libraries scope: alphabetical by series/name
                query = query.order_by(
                    EmbyProbeQueue.series_name,  # type: ignore[attr-defined]
                    EmbyProbeQueue.season_number,  # type: ignore[attr-defined]
                    EmbyProbeQueue.episode_number,  # type: ignore[attr-defined]
                    EmbyProbeQueue.name  # type: ignore[attr-defined]
                )

            entries = query.all()

            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "scope": entry.scope,
                    "media_source_id": entry.media_source_id,
                    "library_id": entry.library_id,
                    "library_name": entry.library_name,
                    "name": entry.name,
                    "series_name": entry.series_name,
                    "season_number": entry.season_number,
                    "episode_number": entry.episode_number,
                    "year": entry.year,
                    "media_type": entry.media_type,
                    "path": entry.path,
                    "added_at": entry.added_at.isoformat() if entry.added_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_queue(
        self,
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            if media_source_id is not None:
                query = query.filter(EmbyProbeQueue.media_source_id == media_source_id)  # type: ignore[attr-defined]
            else:
                query = query.filter(EmbyProbeQueue.media_source_id.is_(None))  # type: ignore[attr-defined]
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dalla coda probe: {exc}") from exc
        finally:
            session.close()

    def clear_probe_queue(self, server_id: str, scope: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento coda probe: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe History ---

    def add_probe_history(self, data: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            new_entry = EmbyProbeHistory(
                server_id=data.get("server_id", ""),
                item_id=data.get("item_id", ""),
                scope=self._normalize_probe_scope(data.get("scope")),
                media_source_id=data.get("media_source_id"),
                name=data.get("name", "Sconosciuto"),
                library_name=data.get("library_name"),
                status=data.get("status", "UNKNOWN"),
                error_details=data.get("error_details"),
                duration_ms=data.get("duration_ms")
            )
            session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta allo storico probe: {exc}") from exc
        finally:
            session.close()

    def get_probe_history(
        self,
        server_id: Optional[str] = None,
        limit: int = 100,
        scope: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory)

            if server_id:
                query = query.filter(EmbyProbeHistory.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)

            query = query.order_by(EmbyProbeHistory.processed_at.desc())  # type: ignore[attr-defined]
            query = query.limit(limit)

            entries = query.all()

            return [
                {
                    "id": entry.id,
                    "server_id": entry.server_id,
                    "item_id": entry.item_id,
                    "scope": entry.scope,
                    "media_source_id": entry.media_source_id,
                    "name": entry.name,
                    "library_name": entry.library_name,
                    "processed_at": entry.processed_at.isoformat() if entry.processed_at else None,
                    "status": entry.status,
                    "error_details": entry.error_details,
                    "duration_ms": entry.duration_ms
                }
                for entry in entries
            ]
        finally:
            session.close()

    def remove_from_probe_history(
        self,
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeHistory.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)
            if media_source_id is not None:
                query = query.filter(EmbyProbeHistory.media_source_id == media_source_id)  # type: ignore[attr-defined]
            else:
                query = query.filter(EmbyProbeHistory.media_source_id.is_(None))  # type: ignore[attr-defined]
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione dallo storico probe: {exc}") from exc
        finally:
            session.close()

    def clear_probe_history(self, server_id: str, scope: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore svuotamento storico probe: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe Recent Scan Tracking ---

    def get_recent_scan_timestamp(self, server_id: str, library_id: Optional[str] = None) -> Optional[datetime]:
        """Get the oldest scanned timestamp from the last scan for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            entry = session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                EmbyProbeRecentScan.server_id == server_id,
                EmbyProbeRecentScan.library_id == lib_id
            ).first()
            if entry and entry.oldest_scanned_timestamp:
                # Ensure timezone aware datetime (PostgreSQL TIMESTAMP returns naive)
                ts = entry.oldest_scanned_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            return None
        finally:
            session.close()

    def save_recent_scan_timestamp(self, server_id: str, oldest_timestamp: Optional[datetime], library_id: Optional[str] = None) -> None:
        """Save the oldest scanned timestamp for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            entry = session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                EmbyProbeRecentScan.server_id == server_id,
                EmbyProbeRecentScan.library_id == lib_id
            ).first()
            if entry:
                entry.oldest_scanned_timestamp = oldest_timestamp  # type: ignore[assignment]
            else:
                new_entry = EmbyProbeRecentScan(
                    server_id=server_id,
                    library_id=lib_id,
                    oldest_scanned_timestamp=oldest_timestamp,
                    payload={}
                )
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio timestamp scan recent: {exc}") from exc
        finally:
            session.close()

    # --- Emby Probe Recent Scan Config ---

    def get_recent_scan_config(self, server_id: str) -> Dict[str, Any]:
        """Get discovery configuration parameters for a server."""
        defaults = {
            "window_size": 500,
            "window_threshold": 0.90,
            "max_days": 60,
            "max_items": 2000,
            "safety_margin_days": 7
        }
        key = f"probe_recent_config:{server_id}"
        provider = cast(_KeyValueProvider, self)
        value = provider.get_key_value(key)
        if isinstance(value, dict):
            merged = defaults.copy()
            for field in defaults:
                if field in value:
                    merged[field] = value[field]
            return merged
        return defaults

    def save_recent_scan_config(self, server_id: str, config: Dict[str, Any]) -> None:
        """Save discovery configuration parameters for a server."""
        if not isinstance(config, dict):
            raise StorageError("Config recente non valida")
        key = f"probe_recent_config:{server_id}"
        provider = cast(_KeyValueProvider, self)
        provider.set_key_value(key, config)
