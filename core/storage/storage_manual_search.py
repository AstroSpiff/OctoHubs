"""Manual search history storage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, ManualSearchHistory


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageManualSearchMixin(_SessionProvider):
    def save_manual_search(self, payload: Dict[str, Any]) -> None:
        """Salva una ricerca manuale (stesso formato di save_scan_result)."""
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
            entry = ManualSearchHistory(generated_at=generated_dt)
            entry.payload = payload  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore salvataggio ricerca manuale: {exc}") from exc
        finally:
            session.close()

    def load_manual_searches(self, limit: int = 20) -> list[Dict[str, Any]]:
        """Recupera lo storico delle ricerche manuali recenti."""
        session = self._get_session()
        try:
            entries = (
                session.query(ManualSearchHistory)  # type: ignore[attr-defined]
                .order_by(ManualSearchHistory.generated_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": entry.id,
                    "generated_at": entry.generated_at.isoformat() if entry.generated_at else None,
                    **entry.payload  # type: ignore[misc]
                }
                for entry in entries
            ]
        except SQLAlchemyError as exc:
            raise StorageError(f"Errore recupero ricerche manuali: {exc}") from exc
        finally:
            session.close()

    def delete_manual_search(self, search_id: int) -> None:
        """Elimina una ricerca manuale dallo storico."""
        session = self._get_session()
        try:
            session.query(ManualSearchHistory).filter(  # type: ignore[attr-defined]
                ManualSearchHistory.id == search_id
            ).delete()
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore eliminazione ricerca manuale: {exc}") from exc
        finally:
            session.close()

    def delete_manual_searches(self, keep_last: int = 0) -> int:
        """Elimina lo storico ricerche manuali, opzionalmente mantenendo gli ultimi N."""
        session = self._get_session()
        try:
            keep_last = int(keep_last or 0)
            if keep_last > 0:
                keep_ids = [
                    entry.id
                    for entry in session.query(ManualSearchHistory)  # type: ignore[attr-defined]
                    .order_by(ManualSearchHistory.generated_at.desc())  # type: ignore[attr-defined]
                    .limit(keep_last)
                    .all()
                ]
                if keep_ids:
                    deleted = session.query(ManualSearchHistory).filter(  # type: ignore[attr-defined]
                        ~ManualSearchHistory.id.in_(keep_ids)
                    ).delete(synchronize_session=False)
                else:
                    deleted = 0
            else:
                deleted = session.query(ManualSearchHistory).delete()  # type: ignore[attr-defined]
            session.commit()
            return int(deleted or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore pulizia storico manuale: {exc}") from exc
        finally:
            session.close()
