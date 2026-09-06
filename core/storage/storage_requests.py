"""Request rules and scan result storage operations."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import threading
from typing import Any, Callable, Dict, Iterable, Optional, Protocol, Tuple

from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_locks import lock_snapshot_writer
from core.storage.storage_models import SQLAlchemyError, RequestRuleEntry, ScanResultEntry, RequestCacheEntry
from search.download_references import protect_download_references


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


_request_rules_write_lock = threading.RLock()
_request_cache_write_lock = threading.RLock()
_scan_results_write_lock = threading.RLock()


def replace_request_overview_in_session(session: Any, payload: Any) -> None:
    """Replace the request overview inside a caller-owned transaction."""
    entry = session.get(RequestCacheEntry, 1)
    if entry:
        entry.payload = payload  # type: ignore[assignment]
        return
    new_entry = RequestCacheEntry(id=1)
    new_entry.payload = payload  # type: ignore[assignment]
    session.add(new_entry)


class StorageRequestsMixin(_SessionProvider):
    def load_request_rules(self) -> Dict[str, Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(RequestRuleEntry).all()
            return {entry.request_id: entry.data for entry in entries}
        finally:
            close_session_safely(session)

    def save_request_rules(self, rules: Dict[str, Dict[str, Any]]) -> None:
        with _request_rules_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "request-rules")
                keys = list(rules.keys())
                existing = {}
                if keys:
                    existing = {
                        entry.request_id: entry
                        for entry in session.query(RequestRuleEntry).filter(
                            RequestRuleEntry.request_id.in_(keys)  # type: ignore[attr-defined]
                        )
                    }
                else:
                    session.query(RequestRuleEntry).delete()
                for request_id, data in rules.items():
                    entry = existing.get(request_id)
                    if entry:
                        entry.data = data  # type: ignore[assignment]
                    else:
                        new_entry = RequestRuleEntry(request_id=request_id)
                        new_entry.data = data  # type: ignore[assignment]
                        session.add(new_entry)
                if keys:
                    session.query(RequestRuleEntry).filter(~RequestRuleEntry.request_id.in_(keys)).delete(synchronize_session=False)  # type: ignore[attr-defined]
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                rollback_session_safely(session)
                raise StorageError(f"Errore salvataggio regole: {exc}") from exc
            finally:
                close_session_safely(session)

    def patch_request_rules(
        self,
        updates: Dict[str, Dict[str, Any]],
        deletions: Iterable[str] = (),
    ) -> Dict[str, Dict[str, Any]]:
        """Atomically update only the submitted request rules.

        Unlike ``save_request_rules``, this operation does not treat its input as
        a complete snapshot. Independent request IDs can therefore be edited by
        concurrent workers without either writer deleting the other's change.
        """
        if not isinstance(updates, dict):
            raise StorageError("Aggiornamento regole non valido")
        normalized_updates = {
            str(request_id): data
            for request_id, data in updates.items()
            if isinstance(data, dict)
        }
        if len(normalized_updates) != len(updates):
            raise StorageError("Aggiornamento regole non valido")
        deletion_ids = {str(request_id) for request_id in deletions}
        deletion_ids.difference_update(normalized_updates)

        with _request_rules_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "request-rules")
                for request_id in deletion_ids:
                    session.query(RequestRuleEntry).filter(
                        RequestRuleEntry.request_id == request_id  # type: ignore[attr-defined]
                    ).delete(synchronize_session=False)
                for request_id, data in normalized_updates.items():
                    entry = session.get(RequestRuleEntry, request_id)
                    if entry is None:
                        entry = RequestRuleEntry(request_id=request_id)
                        session.add(entry)
                    entry.data = data  # type: ignore[assignment]
                session.flush()
                persisted = {
                    entry.request_id: entry.data
                    for entry in session.query(RequestRuleEntry).all()
                }
                session.commit()
                return persisted
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore aggiornamento regole: {exc}") from exc
            finally:
                close_session_safely(session)

    # --- Scan results ---

    def save_scan_result(self, payload: Dict[str, Any]) -> None:
        with _scan_results_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "scan-results")
                generated = payload.get("generated_at")
                if isinstance(generated, str):
                    normalized = generated.replace("Z", "+00:00")
                    try:
                        generated_dt = datetime.fromisoformat(normalized)
                    except ValueError:
                        generated_dt = datetime.now(timezone.utc)
                else:
                    generated_dt = datetime.now(timezone.utc)
                entry = ScanResultEntry(generated_at=generated_dt)
                entry.payload = protect_download_references(payload, persisted=True)  # type: ignore[assignment]
                session.add(entry)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                rollback_session_safely(session)
                raise StorageError(f"Errore salvataggio risultati: {exc}") from exc
            finally:
                close_session_safely(session)

    def load_last_result(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = (
                session.query(ScanResultEntry)
                .order_by(
                    ScanResultEntry.generated_at.desc(),  # type: ignore[attr-defined]
                    ScanResultEntry.id.desc(),  # type: ignore[attr-defined]
                )
                .first()
            )
            return entry.payload if entry else None
        finally:
            close_session_safely(session)

    def load_request_overview(self) -> Tuple[Optional[Any], Optional[datetime]]:
        session = self._get_session()
        try:
            entry = session.get(RequestCacheEntry, 1)
            if entry:
                return entry.payload, entry.updated_at
            return None, None
        finally:
            close_session_safely(session)

    def save_request_overview(self, payload: Any) -> None:
        with _request_cache_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "request-overview")
                replace_request_overview_in_session(session, payload)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover
                rollback_session_safely(session)
                raise StorageError(f"Errore cache richieste: {exc}") from exc
            finally:
                close_session_safely(session)

    def save_request_refresh_snapshot(
        self,
        overview: Any,
        jellyseerr_entries: list[Dict[str, Any]],
    ) -> int:
        """Atomically publish both projections produced by one Jellyseerr fetch."""
        from core.storage.storage_jellyseerr import (
            _jellyseerr_write_lock,
            replace_jellyseerr_requests_in_session,
        )

        with _request_cache_write_lock, _jellyseerr_write_lock:
            session = self._get_session()
            try:
                # One transaction owns both canonical snapshot fences.
                lock_snapshot_writer(session, "request-overview")
                lock_snapshot_writer(session, "jellyseerr-requests")
                replace_request_overview_in_session(session, overview)
                count = replace_jellyseerr_requests_in_session(session, jellyseerr_entries)
                session.commit()
                return count
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore snapshot richieste Jellyseerr: {exc}") from exc
            except Exception:
                rollback_session_safely(session)
                raise
            finally:
                close_session_safely(session)

    # --- Scan results cleanup ---

    def mutate_last_scan_result(
        self,
        transform: Callable[[Dict[str, Any]], tuple[Optional[Dict[str, Any]], Any]],
    ) -> Optional[Any]:
        """Atomically transform the latest result and optionally append its successor."""
        with _scan_results_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "scan-results")
                entry = (
                    session.query(ScanResultEntry)
                    .order_by(
                        ScanResultEntry.generated_at.desc(),  # type: ignore[attr-defined]
                        ScanResultEntry.id.desc(),  # type: ignore[attr-defined]
                    )
                    .with_for_update()
                    .first()
                )
                if entry is None:
                    session.commit()
                    return None
                next_payload, outcome = transform(copy.deepcopy(entry.payload))
                if next_payload is not None:
                    successor = ScanResultEntry(generated_at=datetime.now(timezone.utc))
                    successor.payload = protect_download_references(  # type: ignore[assignment]
                        next_payload,
                        persisted=True,
                    )
                    session.add(successor)
                session.commit()
                return outcome
            except SQLAlchemyError as exc:
                rollback_session_safely(session)
                raise StorageError(f"Errore aggiornamento risultati: {exc}") from exc
            except Exception:
                rollback_session_safely(session)
                raise
            finally:
                close_session_safely(session)

    def delete_scan_results(self, keep_last: int = 0) -> int:
        """Elimina i risultati ricerche salvati, opzionalmente mantenendo gli ultimi N."""
        with _scan_results_write_lock:
            session = self._get_session()
            try:
                lock_snapshot_writer(session, "scan-results")
                keep_last = int(keep_last or 0)
                if keep_last > 0:
                    keep_ids = [
                        entry.id
                        for entry in session.query(ScanResultEntry)  # type: ignore[attr-defined]
                        .order_by(
                            ScanResultEntry.generated_at.desc(),  # type: ignore[attr-defined]
                            ScanResultEntry.id.desc(),  # type: ignore[attr-defined]
                        )
                        .limit(keep_last)
                        .all()
                    ]
                    if keep_ids:
                        deleted = session.query(ScanResultEntry).filter(  # type: ignore[attr-defined]
                            ~ScanResultEntry.id.in_(keep_ids)
                        ).delete(synchronize_session=False)
                    else:
                        deleted = 0
                else:
                    deleted = session.query(ScanResultEntry).delete()  # type: ignore[attr-defined]
                session.commit()
                return int(deleted or 0)
            except SQLAlchemyError as exc:
                rollback_session_safely(session)
                raise StorageError(f"Errore pulizia risultati: {exc}") from exc
            finally:
                close_session_safely(session)
