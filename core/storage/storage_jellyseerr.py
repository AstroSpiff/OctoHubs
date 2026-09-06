"""Jellyseerr request storage operations."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Dict, List, Optional, Protocol, cast

from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_locks import lock_snapshot_writer
from core.storage.storage_models import SQLAlchemyError, JellyseerrRequest, func
from core.storage.storage_utils import _parse_datetime_value, _normalize_text_value


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


_jellyseerr_write_lock = threading.RLock()


def _string(value: Any) -> Optional[str]:
    return _normalize_text_value(value)


def _int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def replace_jellyseerr_requests_in_session(session: Any, entries: List[Dict[str, Any]]) -> int:
    """Replace the Jellyseerr projection inside a caller-owned transaction."""
    incoming_ids = {
        request_id
        for entry in entries or []
        if isinstance(entry, dict)
        for request_id in (_string(entry.get("request_id")),)
        if request_id
    }
    existing = {}
    if incoming_ids:
        for row in session.query(JellyseerrRequest).filter(
            JellyseerrRequest.request_id.in_(list(incoming_ids))  # type: ignore[attr-defined]
        ):
            existing[row.request_id] = row

    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        request_id = _string(entry.get("request_id"))
        if not request_id:
            continue
        row = cast(Any, existing.get(request_id) or JellyseerrRequest(request_id=request_id))
        tmdb_id = _int(entry.get("tmdb_id"))
        media_type = _string(entry.get("media_type"))
        status = _string(entry.get("status"))
        status_label = _string(entry.get("status_label"))
        requested_by = _string(entry.get("requested_by"))
        created_at = _parse_datetime_value(entry.get("created_at"))
        updated_at = _parse_datetime_value(entry.get("updated_at"))
        payload = entry.get("payload") or {}
        if (
            row.tmdb_id == tmdb_id
            and row.media_type == media_type
            and row.status == status
            and row.status_label == status_label
            and row.requested_by == requested_by
            and row.created_at == created_at
            and row.updated_at == updated_at
            and (row.payload or {}) == payload
        ):
            continue
        row.tmdb_id = tmdb_id
        row.media_type = media_type
        row.status = status
        row.status_label = status_label
        row.requested_by = requested_by
        row.created_at = created_at
        row.updated_at = updated_at
        row.payload = payload
        session.add(row)

    query = session.query(JellyseerrRequest)
    if incoming_ids:
        query.filter(
            ~JellyseerrRequest.request_id.in_(list(incoming_ids))  # type: ignore[attr-defined]
        ).delete(synchronize_session=False)
    else:
        query.delete()
    return len(incoming_ids)


class StorageJellyseerrMixin(_SessionProvider):
    def save_jellyseerr_requests(self, entries: List[Dict[str, Any]]) -> int:
        with _jellyseerr_write_lock:
            return self._save_jellyseerr_requests_locked(entries)

    def _save_jellyseerr_requests_locked(self, entries: List[Dict[str, Any]]) -> int:
        session = self._get_session()
        try:
            lock_snapshot_writer(session, "jellyseerr-requests")
            count = replace_jellyseerr_requests_in_session(session, entries)
            session.commit()
            return count
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio Jellyseerr: {exc}") from exc
        finally:
            close_session_safely(session)

    def load_jellyseerr_request_state(self) -> Dict[str, Dict[str, Any]]:
        session = self._get_session()
        try:
            rows = session.query(JellyseerrRequest).all()
            state: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                if not row.request_id:
                    continue
                state[str(row.request_id)] = {
                    "tmdb_id": row.tmdb_id,
                    "media_type": row.media_type,
                    "status": row.status,
                    "status_label": row.status_label,
                    "requested_by": row.requested_by,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "payload": row.payload or {}
                }
            return state
        finally:
            close_session_safely(session)

    def load_jellyseerr_requests(self) -> List[Dict[str, Any]]:
        session = self._get_session()
        try:
            rows = session.query(JellyseerrRequest).order_by(JellyseerrRequest.updated_at.desc()).all()
            payloads = []
            for row in rows:
                payload = row.payload or {}
                if isinstance(payload, dict):
                    payloads.append(payload)
            return payloads
        finally:
            close_session_safely(session)

    def get_jellyseerr_requests_last_updated(self) -> Optional[datetime]:
        session = self._get_session()
        try:
            return session.query(func.max(JellyseerrRequest.updated_at)).scalar()
        finally:
            close_session_safely(session)

    def load_jellyseerr_request_index(
        self,
        tmdb_ids: List[str],
        media_types: Optional[set[str]] = None
    ) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
        session = self._get_session()
        try:
            ids = [int(val) for val in tmdb_ids if str(val).isdigit()]
            if not ids:
                return {}
            query = session.query(JellyseerrRequest).filter(JellyseerrRequest.tmdb_id.in_(ids))  # type: ignore[attr-defined]
            if media_types:
                query = query.filter(JellyseerrRequest.media_type.in_(list(media_types)))  # type: ignore[attr-defined]
            rows = query.all()
            index: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
            for row in rows:
                if not row.tmdb_id or not row.media_type:
                    continue
                key = (row.media_type, str(row.tmdb_id))
                entry = {
                    "request_id": row.request_id,
                    "status": row.status,
                    "status_label": row.status_label,
                    "requested_by": row.requested_by,
                    "payload": row.payload or {}
                }
                if key not in index:
                    index[key] = []
                index[key].append(entry)
            return index
        finally:
            close_session_safely(session)
