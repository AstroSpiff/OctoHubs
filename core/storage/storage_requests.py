"""Request rules and scan result storage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol, Tuple

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, RequestRuleEntry, ScanResultEntry, RequestCacheEntry


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageRequestsMixin(_SessionProvider):
    def load_request_rules(self) -> Dict[str, Dict[str, Any]]:
        session = self._get_session()
        try:
            entries = session.query(RequestRuleEntry).all()
            return {entry.request_id: entry.data for entry in entries}
        finally:
            session.close()

    def save_request_rules(self, rules: Dict[str, Dict[str, Any]]) -> None:
        session = self._get_session()
        try:
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
            session.rollback()
            raise StorageError(f"Errore salvataggio regole: {exc}") from exc
        finally:
            session.close()

    # --- Scan results ---

    def save_scan_result(self, payload: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
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
            entry.payload = payload  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio risultati: {exc}") from exc
        finally:
            session.close()

    def load_last_result(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = (
                session.query(ScanResultEntry)
                .order_by(ScanResultEntry.generated_at.desc())  # type: ignore[attr-defined]
                .first()
            )
            return entry.payload if entry else None
        finally:
            session.close()

    def load_request_overview(self) -> Tuple[Optional[Dict[str, Any]], Optional[datetime]]:
        session = self._get_session()
        try:
            entry = session.get(RequestCacheEntry, 1)
            if entry:
                return entry.payload, entry.updated_at
            return None, None
        finally:
            session.close()

    def save_request_overview(self, payload: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            entry = session.get(RequestCacheEntry, 1)
            if entry:
                entry.payload = payload  # type: ignore[assignment]
            else:
                new_entry = RequestCacheEntry(id=1)
                new_entry.payload = payload  # type: ignore[assignment]
                session.add(new_entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore cache richieste: {exc}") from exc
        finally:
            session.close()

    # --- Scan results cleanup ---

    def delete_scan_results(self, keep_last: int = 0) -> int:
        """Elimina i risultati ricerche salvati, opzionalmente mantenendo gli ultimi N."""
        session = self._get_session()
        try:
            keep_last = int(keep_last or 0)
            if keep_last > 0:
                keep_ids = [
                    entry.id
                    for entry in session.query(ScanResultEntry)  # type: ignore[attr-defined]
                    .order_by(ScanResultEntry.generated_at.desc())  # type: ignore[attr-defined]
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
            session.rollback()
            raise StorageError(f"Errore pulizia risultati: {exc}") from exc
        finally:
            session.close()
