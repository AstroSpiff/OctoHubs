"""Application settings storage operations."""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable, Dict, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, AppSettings


class _SessionProvider(Protocol):
    _app_settings_lock: threading.RLock

    def _get_session(self) -> Any: ...


class _AppSettingsSnapshot(dict[str, Any]):
    """Dictionary that remembers the version read before a read-modify-write."""

    def __init__(self, data: Dict[str, Any]):
        current = copy.deepcopy(data)
        super().__init__(current)
        self.original = copy.deepcopy(current)


def _merge_snapshot_changes(
    latest: Dict[str, Any],
    original: Dict[str, Any],
    submitted: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a snapshot's changes without discarding concurrent nested edits."""
    merged = copy.deepcopy(latest)
    for key in original.keys() - submitted.keys():
        merged.pop(key, None)
    for key, value in submitted.items():
        if key not in original:
            merged[key] = copy.deepcopy(value)
            continue
        previous = original[key]
        if value == previous:
            continue
        current = merged.get(key)
        if isinstance(previous, dict) and isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _merge_snapshot_changes(current, previous, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class StorageAppSettingsMixin(_SessionProvider):
    def load_app_settings(self) -> Optional[Dict[str, Any]]:
        session = self._get_session()
        try:
            entry = session.get(AppSettings, 1)
            if not entry:
                return None
            data = entry.data if isinstance(entry.data, dict) else {}
            return _AppSettingsSnapshot(data)
        finally:
            session.close()

    def save_app_settings(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise StorageError("Configurazione applicazione non valida")

        with self._app_settings_lock:
            session = self._get_session()
            try:
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})

                if isinstance(data, _AppSettingsSnapshot):
                    latest = dict(entry.data) if isinstance(entry.data, dict) else {}
                    persisted = _merge_snapshot_changes(latest, data.original, data)
                else:
                    persisted = copy.deepcopy(data)

                entry.data = persisted  # type: ignore[assignment]
                session.add(entry)
                session.commit()
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                session.rollback()
                raise StorageError(f"Errore salvataggio configurazione: {exc}") from exc
            finally:
                session.close()

    def update_app_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically merge top-level settings and return the stored snapshot."""
        if not isinstance(updates, dict):
            raise StorageError("Aggiornamento configurazione non valido")
        with self._app_settings_lock:
            session = self._get_session()
            try:
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})
                current = dict(entry.data) if isinstance(entry.data, dict) else {}
                current.update(copy.deepcopy(updates))
                entry.data = current  # type: ignore[assignment]
                session.add(entry)
                session.commit()
                return copy.deepcopy(current)
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                session.rollback()
                raise StorageError(f"Errore aggiornamento configurazione: {exc}") from exc
            finally:
                session.close()

    def update_app_settings_section(
        self,
        section: str,
        updater: Callable[[Any], Any],
    ) -> Dict[str, Any]:
        """Atomically transform one top-level section and return the stored snapshot."""
        if not isinstance(section, str) or not section or not callable(updater):
            raise StorageError("Aggiornamento sezione configurazione non valido")

        with self._app_settings_lock:
            session = self._get_session()
            try:
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})

                current = copy.deepcopy(entry.data) if isinstance(entry.data, dict) else {}
                current[section] = copy.deepcopy(updater(copy.deepcopy(current.get(section))))

                entry.data = current  # type: ignore[assignment]
                session.add(entry)
                session.commit()
                return copy.deepcopy(current)
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                session.rollback()
                raise StorageError(f"Errore aggiornamento configurazione: {exc}") from exc
            finally:
                session.close()
