"""Emby probe storage operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Protocol, cast
from uuid import uuid4

from sqlalchemy import and_, func, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.storage.storage_app_settings import _lock_app_settings_row
from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_locks import lock_snapshot_writer
from core.storage.storage_models import (
    SQLAlchemyError,
    AppSettings,
    EmbyProbeBlacklist,
    EmbyProbeQueue,
    EmbyProbeHistory,
    EmbyProbeRecentScan,
    KeyValueEntry,
    _utcnow,
    or_,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class _KeyValueProvider(Protocol):
    def get_key_value(self, key: str) -> Optional[Any]: ...
    def set_key_value(self, key: str, value: Any) -> None: ...
    def delete_key(self, key: str) -> None: ...


class StorageProbeMixin(_SessionProvider):
    _PROBE_HISTORY_RETENTION = timedelta(days=90)
    _PROBE_QUEUE_LEASE_SECONDS = 300
    _PROBE_RENEWAL_STATEMENT_TIMEOUT_MS = 2_000

    @staticmethod
    def _probe_queue_payload(entry: EmbyProbeQueue) -> Dict[str, Any]:
        added_at = cast(Optional[datetime], entry.added_at)
        claimed_at = cast(Optional[datetime], entry.claimed_at)
        return {
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
            "added_at": added_at.isoformat() if added_at is not None else None,
            "claim_token": entry.claim_token,
            "claimed_at": claimed_at.isoformat() if claimed_at is not None else None,
        }

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

    def _normalize_probe_media_source_id(self, media_source_id: Optional[str]) -> Optional[str]:
        value = str(media_source_id or "").strip()
        return value or None

    def _apply_media_source_filter(self, query, model, media_source_id: Optional[str]):
        normalized = self._normalize_probe_media_source_id(media_source_id)
        if normalized is None:
            return query.filter(
                or_(model.media_source_id.is_(None), model.media_source_id == "")  # type: ignore[attr-defined]
            )
        return query.filter(model.media_source_id == normalized)  # type: ignore[attr-defined]

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
            close_session_safely(session)

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
            retry_count = self._update_probe_blacklist_in_session(
                session,
                server_id=server_id,
                item_id=item_id,
                name=name,
                reason=reason,
                media_source_id=media_source_id,
                increment_retry=increment_retry,
                error_type=error_type,
                scope=scope,
                library_id=library_id,
                library_name=library_name,
            )
            session.commit()
            return retry_count
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore aggiornamento blacklist probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def _update_probe_blacklist_in_session(
        self,
        session: Any,
        *,
        server_id: str,
        item_id: str,
        name: str,
        reason: str,
        media_source_id: Optional[str],
        increment_retry: bool,
        error_type: Optional[str],
        scope: Optional[str],
        library_id: Optional[str],
        library_name: Optional[str],
    ) -> int:
        """Update one blacklist identity without committing the caller's transaction."""
        scope_value = self._normalize_probe_scope(scope)
        media_source_value = self._normalize_probe_media_source_id(media_source_id)
        if session.get_bind().dialect.name == "postgresql":
            retry_count_value = 1 if increment_retry else 0
            values = {
                "server_id": server_id,
                "item_id": item_id,
                "scope": scope_value,
                "media_source_id": media_source_value,
                "library_id": library_id,
                "library_name": library_name,
                "item_name": name,
                "reason": reason,
                "retry_count": retry_count_value,
                "error_type": error_type,
                "failed_at": _utcnow(),
            }
            statement = postgresql_insert(EmbyProbeBlacklist).values(**values)
            excluded = statement.excluded
            update_values = {
                "scope": excluded.scope,
                "media_source_id": excluded.media_source_id,
                "library_id": excluded.library_id,
                "library_name": excluded.library_name,
                "item_name": excluded.item_name,
                "reason": excluded.reason,
                "failed_at": excluded.failed_at,
                "retry_count": (
                    EmbyProbeBlacklist.retry_count + 1
                    if increment_retry
                    else EmbyProbeBlacklist.retry_count
                ),
            }
            if error_type is not None:
                update_values["error_type"] = excluded.error_type
            statement = statement.on_conflict_do_update(
                index_elements=("server_id", "item_id", "scope", "media_source_id"),
                set_=update_values,
            ).returning(EmbyProbeBlacklist.retry_count)
            return int(session.execute(statement).scalar_one())

        query = session.query(EmbyProbeBlacklist).filter(
            EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
            EmbyProbeBlacklist.item_id == item_id,  # type: ignore[attr-defined]
        )
        query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope_value)
        query = self._apply_media_source_filter(
            query,
            EmbyProbeBlacklist,
            media_source_value,
        )
        entry = query.first()
        if entry:
            entry.scope = scope_value  # type: ignore[assignment]
            entry.item_name = name  # type: ignore[assignment]
            entry.reason = reason  # type: ignore[assignment]
            entry.failed_at = _utcnow()  # type: ignore[assignment]
            entry.media_source_id = media_source_value  # type: ignore[assignment]
            entry.library_id = library_id  # type: ignore[assignment]
            entry.library_name = library_name  # type: ignore[assignment]
            entry.error_type = error_type or entry.error_type  # type: ignore[assignment]
            if increment_retry:
                entry.retry_count += 1  # type: ignore[assignment]
            return int(entry.retry_count)  # type: ignore[arg-type]

        retry_count = 1 if increment_retry else 0
        session.add(
            EmbyProbeBlacklist(
                server_id=server_id,
                item_id=item_id,
                scope=scope_value,
                media_source_id=media_source_value,
                library_id=library_id,
                library_name=library_name,
                item_name=name,
                reason=reason,
                retry_count=retry_count,
                error_type=error_type,
            )
        )
        return retry_count

    def remove_from_probe_blacklist(
        self,
        server_id: str,
        item_id: str,
        media_source_id: Optional[str] = None,
        scope: Optional[str] = None
    ) -> None:
        session = self._get_session()
        try:
            scope_value = self._normalize_probe_scope(scope)
            query = session.query(EmbyProbeBlacklist).filter(
                EmbyProbeBlacklist.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeBlacklist.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeBlacklist, scope_value)
            query = self._apply_media_source_filter(
                query,
                EmbyProbeBlacklist,
                media_source_id,
            )
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione dalla blacklist probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def get_probe_blacklist(
        self,
        server_id: Optional[str] = None,
        min_retry_count: int = 0,
        error_type: Optional[str] = None,
        scope: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor_id: int | None = None,
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

            normalized_type = str(error_type or "").strip().upper()
            if normalized_type:
                stored_type = func.upper(func.coalesce(EmbyProbeBlacklist.error_type, ""))
                reason = func.lower(func.coalesce(EmbyProbeBlacklist.reason, ""))
                inferred_incomplete = or_(
                    reason.contains("mediainfo"),
                    reason.contains("metadati"),
                    reason.contains("metadata"),
                )
                if normalized_type == "INCOMPLETE":
                    query = query.filter(
                        or_(
                            stored_type == "INCOMPLETE",
                            and_(stored_type == "", inferred_incomplete),
                        )
                    )
                elif normalized_type == "ERROR":
                    query = query.filter(
                        or_(
                            stored_type == "ERROR",
                            and_(stored_type == "", ~inferred_incomplete),
                        )
                    )
                else:
                    query = query.filter(stored_type == normalized_type)

            if cursor_id is not None:
                if cursor_id > 0:
                    query = query.filter(EmbyProbeBlacklist.id < cursor_id)  # type: ignore[attr-defined]
                query = query.order_by(EmbyProbeBlacklist.id.desc())  # type: ignore[attr-defined]
            else:
                query = query.order_by(
                    EmbyProbeBlacklist.failed_at.desc(),  # type: ignore[attr-defined]
                    EmbyProbeBlacklist.id.desc(),  # type: ignore[attr-defined]
                )
                if offset > 0:
                    query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
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

            return [
                {
                    "id": entry.id,
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
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore svuotamento blacklist probe: {exc}") from exc
        finally:
            close_session_safely(session)

    # --- Emby Probe Queue ---

    def _prepare_concrete_probe_queue_entry(
        self,
        session: Any,
        server_id: str,
        item_id: str,
        media_source_id: str | None,
        scope: str,
    ) -> bool:
        """Remove an idle generic row without invalidating an active lease."""
        if media_source_id is None:
            return True
        query = session.query(EmbyProbeQueue).filter(
            EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
            EmbyProbeQueue.item_id == item_id,  # type: ignore[attr-defined]
            EmbyProbeQueue.media_source_id.is_(None),  # type: ignore[attr-defined]
        )
        query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
        generic_entry = query.with_for_update().first()
        if generic_entry is None:
            return True
        if self._probe_queue_claim_is_active(generic_entry):
            return False
        session.delete(generic_entry)
        return True

    def _probe_queue_claim_is_active(self, entry: EmbyProbeQueue) -> bool:
        claim_token = cast(Optional[str], entry.claim_token)
        claimed_at = cast(Optional[datetime], entry.claimed_at)
        if not claim_token or claimed_at is None:
            return False
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        stale_before = _utcnow() - timedelta(seconds=self._PROBE_QUEUE_LEASE_SECONDS)
        return claimed_at >= stale_before

    def add_to_probe_queue(self, items: list[Dict[str, Any]]) -> None:
        session = self._get_session()
        try:
            self._add_probe_queue_items_in_session(session, items)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore aggiunta elementi alla coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def _add_probe_queue_items_in_session(
        self,
        session: Any,
        items: list[Dict[str, Any]],
    ) -> int:
        """Insert concrete queue identities without committing the transaction."""
        queued = 0
        for item_data in items:
            server_id = item_data.get("server_id")
            item_id = item_data.get("item_id")
            media_source_id = self._normalize_probe_media_source_id(item_data.get("media_source_id"))
            scope_value = self._normalize_probe_scope(item_data.get("scope"))
            if not server_id or not item_id:
                continue
            if not self._prepare_concrete_probe_queue_entry(
                session,
                str(server_id),
                str(item_id),
                media_source_id,
                scope_value,
            ):
                continue
            values = {
                "server_id": server_id,
                "item_id": item_id,
                "scope": scope_value,
                "media_source_id": media_source_id,
                "library_id": item_data.get("library_id"),
                "library_name": item_data.get("library_name"),
                "name": item_data.get("name", "Sconosciuto"),
                "series_name": item_data.get("series_name"),
                "season_number": item_data.get("season_number"),
                "episode_number": item_data.get("episode_number"),
                "year": item_data.get("year"),
                "media_type": item_data.get("media_type"),
                "path": item_data.get("path"),
                "added_at": _utcnow(),
            }
            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                statement = postgresql_insert(EmbyProbeQueue).values(**values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=("server_id", "item_id", "scope", "media_source_id")
                ).returning(EmbyProbeQueue.id)
                inserted = session.execute(statement).scalar_one_or_none() is not None
            elif dialect_name == "sqlite":
                statement = (
                    sqlite_insert(EmbyProbeQueue)
                    .values(**values)
                    .on_conflict_do_nothing()
                    .returning(EmbyProbeQueue.id)
                )
                inserted = session.execute(statement).scalar_one_or_none() is not None
            else:  # pragma: no cover - PostgreSQL is the production backend
                existing_query = session.query(EmbyProbeQueue).filter(
                    EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.item_id == item_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.scope == scope_value,  # type: ignore[attr-defined]
                )
                existing_query = self._apply_media_source_filter(
                    existing_query,
                    EmbyProbeQueue,
                    media_source_id,
                )
                if existing_query.first() is None:
                    session.add(EmbyProbeQueue(**values))
                    inserted = True
                else:
                    inserted = False
            if inserted:
                queued += 1
        return queued

    def retry_probe_items(
        self,
        items: list[Dict[str, Any]],
        *,
        server_id: str,
        item_id: str,
        media_source_id: Optional[str],
        scope: Optional[str],
    ) -> int:
        """Atomically enqueue a retry and clear its stale history/blacklist state."""
        session = self._get_session()
        try:
            lock_snapshot_writer(session, f"probe-retry:{server_id}:{item_id}")
            queued = self._add_probe_queue_items_in_session(session, items)
            if not queued:
                raise StorageError("Nessuna sorgente Probe valida da accodare")
            for model in (EmbyProbeBlacklist, EmbyProbeHistory):
                query = session.query(model).filter(
                    model.server_id == server_id,
                    model.item_id == item_id,
                )
                query = self._apply_scope_filter(query, model, scope)
                query = self._apply_media_source_filter(query, model, media_source_id)
                query.delete(synchronize_session=False)
            session.commit()
            return queued
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore retry atomico Probe: {exc}") from exc
        except Exception:
            rollback_session_safely(session)
            raise
        finally:
            close_session_safely(session)

    def remove_probe_item_state(
        self,
        *,
        server_id: str,
        item_id: str,
        media_source_id: Optional[str],
        scope: Optional[str],
    ) -> None:
        """Remove queue, blacklist and history state in one transaction."""
        session = self._get_session()
        try:
            lock_snapshot_writer(session, f"probe-remove:{server_id}:{item_id}")
            for model in (EmbyProbeQueue, EmbyProbeBlacklist, EmbyProbeHistory):
                query = session.query(model).filter(
                    model.server_id == server_id,
                    model.item_id == item_id,
                )
                query = self._apply_scope_filter(query, model, scope)
                query = self._apply_media_source_filter(query, model, media_source_id)
                query.delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione stato Probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def claim_probe_queue_items(
        self,
        entry_ids: list[int],
        *,
        lease_seconds: int = _PROBE_QUEUE_LEASE_SECONDS,
    ) -> list[Dict[str, Any]]:
        """Atomically lease queue rows so separate workers cannot probe them twice."""
        if not entry_ids:
            return []
        session = self._get_session()
        try:
            now = _utcnow()
            stale_before = now - timedelta(seconds=max(30, lease_seconds))
            entries = (
                session.query(EmbyProbeQueue)
                .filter(
                    EmbyProbeQueue.id.in_(entry_ids),  # type: ignore[attr-defined]
                    or_(
                        EmbyProbeQueue.claim_token.is_(None),  # type: ignore[attr-defined]
                        EmbyProbeQueue.claimed_at.is_(None),  # type: ignore[attr-defined]
                        EmbyProbeQueue.claimed_at < stale_before,  # type: ignore[attr-defined]
                    ),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            claim_token = uuid4().hex
            for entry in entries:
                entry.claim_token = claim_token
                entry.claimed_at = now
            session.commit()
            claimed = {
                int(entry.id): self._probe_queue_payload(entry)
                for entry in entries
            }
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore acquisizione coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

        return [claimed[entry_id] for entry_id in entry_ids if entry_id in claimed]

    def renew_probe_queue_claim(self, entry_id: int, claim_token: str) -> bool:
        """Renew a lease only while the caller still owns its claim token."""
        session = self._get_session()
        try:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(
                    text(
                        "SET LOCAL statement_timeout = "
                        f"'{self._PROBE_RENEWAL_STATEMENT_TIMEOUT_MS}ms'"
                    )
                )
            updated = (
                session.query(EmbyProbeQueue)
                .filter(
                    EmbyProbeQueue.id == entry_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.claim_token == claim_token,  # type: ignore[attr-defined]
                )
                .update({"claimed_at": _utcnow()}, synchronize_session=False)
            )
            session.commit()
            return updated == 1
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore rinnovo lease coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def commit_probe_queue_result(
        self,
        entry_id: int,
        claim_token: str,
        history: Dict[str, Any],
        *,
        failure: Dict[str, Any] | None = None,
        max_retries: int = 3,
        allow_requeue: bool = True,
    ) -> Dict[str, Any] | None:
        """Persist a Probe result and finish its queue claim in one fenced commit.

        The queue row is locked and matched by its opaque claim token before any
        blacklist or history mutation is made.  Losing ownership therefore
        rolls back the whole result instead of allowing a stale worker to leave
        partial state behind.
        """
        if not claim_token:
            return None
        session = self._get_session()
        try:
            queue_entry = (
                session.query(EmbyProbeQueue)
                .filter(
                    EmbyProbeQueue.id == entry_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.claim_token == claim_token,  # type: ignore[attr-defined]
                )
                .with_for_update()
                .one_or_none()
            )
            if queue_entry is None:
                rollback_session_safely(session)
                return None

            if failure is None:
                blacklist_query = session.query(EmbyProbeBlacklist).filter(
                    EmbyProbeBlacklist.server_id == history.get("server_id", ""),  # type: ignore[attr-defined]
                    EmbyProbeBlacklist.item_id == history.get("item_id", ""),  # type: ignore[attr-defined]
                )
                blacklist_query = self._apply_scope_filter(
                    blacklist_query,
                    EmbyProbeBlacklist,
                    history.get("scope"),
                )
                blacklist_query = self._apply_media_source_filter(
                    blacklist_query,
                    EmbyProbeBlacklist,
                    history.get("media_source_id"),
                )
                blacklist_query.delete(synchronize_session=False)
                retry_count = 0
            else:
                retry_count = self._update_probe_blacklist_in_session(
                    session,
                    server_id=str(history.get("server_id") or ""),
                    item_id=str(history.get("item_id") or ""),
                    name=str(history.get("name") or "Sconosciuto"),
                    reason=str(failure.get("reason") or "Errore probe"),
                    media_source_id=history.get("media_source_id"),
                    increment_retry=True,
                    error_type=str(failure.get("error_type") or "ERROR"),
                    scope=history.get("scope"),
                    library_id=failure.get("library_id"),
                    library_name=history.get("library_name"),
                )

            session.add(
                EmbyProbeHistory(
                    server_id=history.get("server_id", ""),
                    item_id=history.get("item_id", ""),
                    scope=self._normalize_probe_scope(history.get("scope")),
                    media_source_id=self._normalize_probe_media_source_id(
                        history.get("media_source_id")
                    ),
                    name=history.get("name", "Sconosciuto"),
                    library_name=history.get("library_name"),
                    status=history.get("status", "UNKNOWN"),
                    error_details=history.get("error_details"),
                    duration_ms=history.get("duration_ms"),
                )
            )
            session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.processed_at
                < _utcnow() - self._PROBE_HISTORY_RETENTION  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)

            requeued = bool(
                failure is not None
                and allow_requeue
                and retry_count < max(1, int(max_retries))
            )
            if requeued:
                queue_entry.claim_token = None  # type: ignore[assignment]
                queue_entry.claimed_at = None  # type: ignore[assignment]
            else:
                session.delete(queue_entry)
            session.commit()
            return {"retry_count": retry_count, "requeued": requeued}
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore commit risultato coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def complete_probe_queue_claim(self, entry_id: int, claim_token: str) -> bool:
        """Delete a queue row only if the caller still owns the lease."""
        session = self._get_session()
        try:
            deleted = (
                session.query(EmbyProbeQueue)
                .filter(
                    EmbyProbeQueue.id == entry_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.claim_token == claim_token,  # type: ignore[attr-defined]
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted == 1
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore completion lease coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def release_probe_queue_claim(self, entry_id: int, claim_token: str) -> bool:
        """Make a claimed row immediately available for a retry by its owner."""
        session = self._get_session()
        try:
            updated = (
                session.query(EmbyProbeQueue)
                .filter(
                    EmbyProbeQueue.id == entry_id,  # type: ignore[attr-defined]
                    EmbyProbeQueue.claim_token == claim_token,  # type: ignore[attr-defined]
                )
                .update(
                    {"claim_token": None, "claimed_at": None},
                    synchronize_session=False,
                )
            )
            session.commit()
            return updated == 1
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore rilascio lease coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def get_probe_queue(
        self,
        server_id: Optional[str] = None,
        library_ids: Optional[list[str]] = None,
        scope: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor_id: int | None = None,
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue)

            if server_id:
                query = query.filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)

            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]

            if cursor_id is not None:
                query = query.filter(EmbyProbeQueue.id > cursor_id)  # type: ignore[attr-defined]
                query = query.order_by(EmbyProbeQueue.id.asc())  # type: ignore[attr-defined]
            else:
                # Sort order depends on scope for offset-based compatibility reads.
                normalized_scope = self._normalize_probe_scope(scope)
                if normalized_scope == "recent":
                    query = query.order_by(
                        EmbyProbeQueue.added_at.asc(),  # type: ignore[attr-defined]
                        EmbyProbeQueue.id.asc(),  # type: ignore[attr-defined]
                    )
                else:
                    query = query.order_by(
                        EmbyProbeQueue.series_name,  # type: ignore[attr-defined]
                        EmbyProbeQueue.season_number,  # type: ignore[attr-defined]
                        EmbyProbeQueue.episode_number,  # type: ignore[attr-defined]
                        EmbyProbeQueue.name,  # type: ignore[attr-defined]
                        EmbyProbeQueue.id,  # type: ignore[attr-defined]
                    )
                if offset > 0:
                    query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            entries = query.all()

            return [self._probe_queue_payload(entry) for entry in entries]
        finally:
            close_session_safely(session)

    def get_probe_matching_titles(self, normalized_titles: set[str]) -> set[str]:
        """Find only requested normalized titles without materializing Probe tables."""
        candidates = {str(value) for value in normalized_titles if str(value)}
        if not candidates:
            return set()
        from core.scanner import sanitize_title

        session = self._get_session()
        matches: set[str] = set()
        try:
            sources = (
                session.query(EmbyProbeQueue.name, EmbyProbeQueue.series_name),
                session.query(EmbyProbeHistory.name),
            )
            for query in sources:
                for row in query.yield_per(500):
                    for value in row:
                        if not value:
                            continue
                        normalized = sanitize_title(str(value).lower())
                        if normalized in candidates:
                            matches.add(normalized)
                    if matches == candidates:
                        return matches
            return matches
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore indice titoli Probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def count_probe_queue(
        self,
        server_id: Optional[str] = None,
        library_ids: Optional[list[str]] = None,
        scope: Optional[str] = None,
    ) -> int:
        """Count queued rows without materializing their payloads."""
        session = self._get_session()
        try:
            query = session.query(func.count(EmbyProbeQueue.id))
            if server_id:
                query = query.filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]
            return int(query.scalar() or 0)
        finally:
            close_session_safely(session)

    def count_probe_queue_by_library(
        self,
        server_id: str,
        library_ids: Optional[list[str]] = None,
        scope: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return per-library queue totals through one grouped query."""
        session = self._get_session()
        try:
            query = session.query(
                EmbyProbeQueue.library_id,
                func.count(EmbyProbeQueue.id),
            ).filter(EmbyProbeQueue.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            if library_ids:
                query = query.filter(EmbyProbeQueue.library_id.in_(library_ids))  # type: ignore[attr-defined]
            rows = query.group_by(EmbyProbeQueue.library_id).all()  # type: ignore[attr-defined]
            return {
                str(library_id): int(total or 0)
                for library_id, total in rows
                if library_id
            }
        finally:
            close_session_safely(session)

    def remove_from_probe_queue(
        self,
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: Optional[str] = None
    ) -> bool:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id,  # type: ignore[attr-defined]
                EmbyProbeQueue.item_id == item_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            query = self._apply_media_source_filter(query, EmbyProbeQueue, media_source_id)
            deleted = query.filter(EmbyProbeQueue.claim_token.is_(None)).delete(
                synchronize_session=False
            )
            session.commit()
            return deleted == 1
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione dalla coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def clear_probe_queue(self, server_id: str, scope: Optional[str] = None) -> int:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeQueue).filter(
                EmbyProbeQueue.server_id == server_id  # type: ignore[attr-defined]
            )
            query = self._apply_scope_filter(query, EmbyProbeQueue, scope)
            deleted = query.filter(EmbyProbeQueue.claim_token.is_(None)).delete(
                synchronize_session=False
            )
            session.commit()
            return int(deleted or 0)
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore svuotamento coda probe: {exc}") from exc
        finally:
            close_session_safely(session)

    # --- Emby Probe History ---

    def add_probe_history(self, data: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            new_entry = EmbyProbeHistory(
                server_id=data.get("server_id", ""),
                item_id=data.get("item_id", ""),
                scope=self._normalize_probe_scope(data.get("scope")),
                media_source_id=self._normalize_probe_media_source_id(data.get("media_source_id")),
                name=data.get("name", "Sconosciuto"),
                library_name=data.get("library_name"),
                status=data.get("status", "UNKNOWN"),
                error_details=data.get("error_details"),
                duration_ms=data.get("duration_ms")
            )
            session.add(new_entry)
            session.query(EmbyProbeHistory).filter(
                EmbyProbeHistory.processed_at < _utcnow() - self._PROBE_HISTORY_RETENTION  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore aggiunta allo storico probe: {exc}") from exc
        finally:
            close_session_safely(session)

    def get_probe_history(
        self,
        server_id: Optional[str] = None,
        limit: int = 100,
        scope: Optional[str] = None,
        *,
        offset: int = 0,
        cursor_id: int | None = None,
    ) -> list[Dict[str, Any]]:
        session = self._get_session()
        try:
            query = session.query(EmbyProbeHistory)

            if server_id:
                query = query.filter(EmbyProbeHistory.server_id == server_id)  # type: ignore[attr-defined]
            query = self._apply_scope_filter(query, EmbyProbeHistory, scope)

            if cursor_id is not None:
                if cursor_id > 0:
                    query = query.filter(EmbyProbeHistory.id < cursor_id)  # type: ignore[attr-defined]
                query = query.order_by(EmbyProbeHistory.id.desc())  # type: ignore[attr-defined]
            else:
                query = query.order_by(
                    EmbyProbeHistory.processed_at.desc(),  # type: ignore[attr-defined]
                    EmbyProbeHistory.id.desc(),  # type: ignore[attr-defined]
                )
                if offset > 0:
                    query = query.offset(offset)
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
            close_session_safely(session)

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
            query = self._apply_media_source_filter(query, EmbyProbeHistory, media_source_id)
            query.delete()
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione dallo storico probe: {exc}") from exc
        finally:
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore svuotamento storico probe: {exc}") from exc
        finally:
            close_session_safely(session)

    # --- Emby Probe Recent Scan Tracking ---

    def get_recent_scan_timestamp(self, server_id: str, library_id: Optional[str] = None) -> Optional[datetime]:
        """Get the oldest scanned timestamp from the last scan for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            entry = session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                EmbyProbeRecentScan.server_id == server_id,
                EmbyProbeRecentScan.library_id == lib_id
            ).order_by(EmbyProbeRecentScan.id.desc()).first()
            if entry and entry.oldest_scanned_timestamp:
                # Ensure timezone aware datetime (PostgreSQL TIMESTAMP returns naive)
                ts = entry.oldest_scanned_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            return None
        finally:
            close_session_safely(session)

    def save_recent_scan_timestamp(self, server_id: str, oldest_timestamp: Optional[datetime], library_id: Optional[str] = None) -> None:
        """Save the oldest scanned timestamp for a server/library."""
        session = self._get_session()
        try:
            lib_id = library_id or "__all__"
            values = {
                "server_id": server_id,
                "library_id": lib_id,
                "oldest_scanned_timestamp": oldest_timestamp,
                "payload": {},
                "last_scan_at": _utcnow(),
            }
            dialect_name = session.get_bind().dialect.name
            if dialect_name == "postgresql":
                statement = postgresql_insert(EmbyProbeRecentScan).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=("server_id", "library_id"),
                    set_={
                        "oldest_scanned_timestamp": statement.excluded.oldest_scanned_timestamp,
                        "last_scan_at": statement.excluded.last_scan_at,
                    },
                )
                session.execute(statement)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(EmbyProbeRecentScan).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=("server_id", "library_id"),
                    set_={
                        "oldest_scanned_timestamp": statement.excluded.oldest_scanned_timestamp,
                        "last_scan_at": statement.excluded.last_scan_at,
                    },
                )
                session.execute(statement)
            else:  # pragma: no cover - PostgreSQL is the production backend
                entry = session.query(EmbyProbeRecentScan).filter(  # type: ignore[attr-defined]
                    EmbyProbeRecentScan.server_id == server_id,
                    EmbyProbeRecentScan.library_id == lib_id,
                ).with_for_update().one_or_none()
                if entry is None:
                    session.add(EmbyProbeRecentScan(**values))
                else:
                    entry.oldest_scanned_timestamp = oldest_timestamp  # type: ignore[assignment]
                    entry.last_scan_at = values["last_scan_at"]  # type: ignore[assignment]
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio timestamp scan recent: {exc}") from exc
        finally:
            close_session_safely(session)

    # --- Emby Probe Configuration ---

    def get_probe_config(self, server_id: str) -> Dict[str, Any]:
        """Get the shared Probe configuration for one server."""
        defaults = {
            "window_size": 500,
            "window_threshold": 0.90,
            "max_days": 60,
            "max_items": 2000,
            "safety_margin_days": 7,
            "probe_parallelism": 1,
            "media_policy": "strm_only",
        }
        key = f"probe_config:{server_id}"
        provider = cast(_KeyValueProvider, self)
        value = provider.get_key_value(key)
        if isinstance(value, dict):
            merged = defaults.copy()
            for field in defaults:
                if field in value:
                    merged[field] = value[field]
            return merged
        return defaults

    def save_probe_config(self, server_id: str, config: Dict[str, Any]) -> None:
        """Save the shared Probe configuration for one server."""
        if not isinstance(config, dict):
            raise StorageError("Configurazione Probe non valida")
        key = f"probe_config:{server_id}"
        provider = cast(_KeyValueProvider, self)
        provider.set_key_value(key, config)

    def save_probe_config_if_server_exists(self, server_id: str, config: Dict[str, Any]) -> bool:
        """Persist Probe settings only while the owning server still exists."""
        if not isinstance(config, dict):
            raise StorageError("Configurazione Probe non valida")
        server_key = str(server_id or "").strip()
        if not server_key:
            return False
        key = f"probe_config:{server_key}"
        session = self._get_session()
        try:
            _lock_app_settings_row(session)
            lock_snapshot_writer(session, f"key-value:{key}")
            settings_row = (
                session.query(AppSettings)
                .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                .with_for_update()
                .one_or_none()
            )
            settings = settings_row.data if settings_row is not None and isinstance(settings_row.data, dict) else {}
            emby = settings.get("EMBY") if isinstance(settings, dict) else {}
            servers = emby.get("SERVERS") if isinstance(emby, dict) else []
            if not any(
                isinstance(server, dict) and str(server.get("id") or "") == server_key
                for server in (servers if isinstance(servers, list) else [])
            ):
                rollback_session_safely(session)
                return False
            entry = session.get(KeyValueEntry, key)
            if entry is None:
                session.add(KeyValueEntry(key=key, value=config))
            else:
                entry.value = config  # type: ignore[assignment]
            session.commit()
            return True
        except SQLAlchemyError as exc:
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio configurazione Probe: {exc}") from exc
        finally:
            close_session_safely(session)
