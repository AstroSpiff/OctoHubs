"""Application settings storage operations."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, AppSettings


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageAppSettingsMixin(_SessionProvider):
    def load_app_settings(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = session.get(AppSettings, 1)
            return entry.data if entry else None
        finally:
            session.close()

    def save_app_settings(self, data: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            entry = session.get(AppSettings, 1)
            if not entry:
                entry = AppSettings(id=1)
            entry.data = data  # type: ignore[assignment]
            session.add(entry)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
            session.rollback()
            raise StorageError(f"Errore salvataggio configurazione: {exc}") from exc
        finally:
            session.close()
