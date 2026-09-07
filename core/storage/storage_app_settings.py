"""Application settings storage operations."""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable, Dict, Optional, Protocol

from core.app_settings_crypto import (
    AppSettingsCryptoError,
    SettingsCipher,
    decode_app_settings_document,
    encode_app_settings_document,
)
from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_models import SQLAlchemyError, AppSettings, text


_APP_SETTINGS_ADVISORY_LOCK_ID = 4_872_221_935_817_104_003


def _lock_app_settings_row(session: Any) -> None:
    """Lock the singleton key even before its first row exists."""
    bind = session.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _APP_SETTINGS_ADVISORY_LOCK_ID},
        )


class _SessionProvider(Protocol):
    _app_settings_lock: threading.RLock
    _app_settings_cipher: SettingsCipher | None

    def _get_session(self) -> Any: ...


def _settings_cipher(provider: _SessionProvider) -> SettingsCipher:
    cipher = provider._app_settings_cipher
    if cipher is not None:
        return cipher
    try:
        from emby_users.password_crypto import password_cipher_from_environment

        cipher = password_cipher_from_environment()
    except Exception as exc:
        raise AppSettingsCryptoError(
            "PASSWORD_SECRET non disponibile per proteggere app_settings"
        ) from exc
    provider._app_settings_cipher = cipher
    return cipher


def _decode_settings(provider: _SessionProvider, value: Any) -> tuple[Dict[str, Any], bool]:
    document = copy.deepcopy(value) if isinstance(value, dict) else {}
    return decode_app_settings_document(document, lambda: _settings_cipher(provider))


def _encode_settings(provider: _SessionProvider, value: Dict[str, Any]) -> Dict[str, Any]:
    return encode_app_settings_document(value, lambda: _settings_cipher(provider))


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
        if key in latest and latest[key] != original[key]:
            raise StorageError(
                f"Conflitto aggiornamento configurazione per la chiave {key!r}"
            )
        merged.pop(key, None)
    for key, value in submitted.items():
        if key not in original:
            if key in latest and latest[key] != value:
                raise StorageError(
                    f"Conflitto aggiornamento configurazione per la chiave {key!r}"
                )
            merged[key] = copy.deepcopy(value)
            continue
        previous = original[key]
        if value == previous:
            continue
        if key not in latest:
            raise StorageError(
                f"Conflitto aggiornamento configurazione per la chiave {key!r}"
            )
        current = merged.get(key)
        if isinstance(previous, dict) and isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _merge_snapshot_changes(current, previous, value)
        else:
            if key in latest and current != previous and current != value:
                raise StorageError(
                    f"Conflitto aggiornamento configurazione per la chiave {key!r}"
                )
            merged[key] = copy.deepcopy(value)
    return merged


class StorageAppSettingsMixin(_SessionProvider):
    def load_app_settings(self) -> Optional[Dict[str, Any]]:
        with self._app_settings_lock:
            session = self._get_session()
            try:
                _lock_app_settings_row(session)
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    return None
                data, rewrite_required = _decode_settings(self, entry.data)
                if rewrite_required:
                    entry.data = _encode_settings(self, data)  # type: ignore[assignment]
                    session.add(entry)
                    session.commit()
                return _AppSettingsSnapshot(data)
            except AppSettingsCryptoError as exc:
                rollback_session_safely(session)
                raise StorageError(str(exc)) from exc
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore lettura configurazione: {exc}") from exc
            except Exception:
                rollback_session_safely(session)
                raise
            finally:
                close_session_safely(session)

    def save_app_settings(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise StorageError("Configurazione applicazione non valida")

        with self._app_settings_lock:
            session = self._get_session()
            try:
                _lock_app_settings_row(session)
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})

                if isinstance(data, _AppSettingsSnapshot):
                    latest, _needs_rewrite = _decode_settings(self, entry.data)
                    persisted = _merge_snapshot_changes(latest, data.original, data)
                else:
                    persisted = copy.deepcopy(data)

                entry.data = _encode_settings(self, persisted)  # type: ignore[assignment]
                session.add(entry)
                session.commit()
            except AppSettingsCryptoError as exc:
                rollback_session_safely(session)
                raise StorageError(str(exc)) from exc
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore salvataggio configurazione: {exc}") from exc
            except Exception:
                rollback_session_safely(session)
                raise
            finally:
                close_session_safely(session)

    def update_app_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically merge top-level settings and return the stored snapshot."""
        if not isinstance(updates, dict):
            raise StorageError("Aggiornamento configurazione non valido")
        with self._app_settings_lock:
            session = self._get_session()
            try:
                _lock_app_settings_row(session)
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})
                current, _needs_rewrite = _decode_settings(self, entry.data)
                current.update(copy.deepcopy(updates))
                entry.data = _encode_settings(self, current)  # type: ignore[assignment]
                session.add(entry)
                session.commit()
                return copy.deepcopy(current)
            except AppSettingsCryptoError as exc:
                rollback_session_safely(session)
                raise StorageError(str(exc)) from exc
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore aggiornamento configurazione: {exc}") from exc
            finally:
                close_session_safely(session)

    def save_app_settings_changes(
        self,
        original: Dict[str, Any],
        submitted: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Atomically merge changes made from an explicit settings snapshot."""
        if not isinstance(original, dict) or not isinstance(submitted, dict):
            raise StorageError("Aggiornamento configurazione non valido")

        def merge(latest: Dict[str, Any]) -> Dict[str, Any]:
            return _merge_snapshot_changes(latest, original, submitted)

        return self.mutate_app_settings(merge)

    def seed_app_settings(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        """Insert missing top-level settings without replacing concurrent values."""
        if not isinstance(defaults, dict):
            raise StorageError("Configurazione iniziale non valida")

        def seed(current: Dict[str, Any]) -> Dict[str, Any]:
            for key, value in defaults.items():
                if key not in current:
                    current[key] = copy.deepcopy(value)
            return current

        return self.mutate_app_settings(seed)

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
                _lock_app_settings_row(session)
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if not entry:
                    entry = AppSettings(id=1, data={})

                current, _needs_rewrite = _decode_settings(self, entry.data)
                current[section] = copy.deepcopy(updater(copy.deepcopy(current.get(section))))

                entry.data = _encode_settings(self, current)  # type: ignore[assignment]
                session.add(entry)
                session.commit()
                return copy.deepcopy(current)
            except AppSettingsCryptoError as exc:
                rollback_session_safely(session)
                raise StorageError(str(exc)) from exc
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore aggiornamento configurazione: {exc}") from exc
            finally:
                close_session_safely(session)

    def mutate_app_settings(
        self,
        updater: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Atomically transform the complete settings document."""
        if not callable(updater):
            raise StorageError("Aggiornamento configurazione non valido")
        with self._app_settings_lock:
            session = self._get_session()
            try:
                _lock_app_settings_row(session)
                entry = (
                    session.query(AppSettings)
                    .filter(AppSettings.id == 1)  # type: ignore[attr-defined]
                    .with_for_update()
                    .one_or_none()
                )
                if entry is None:
                    entry = AppSettings(id=1, data={})
                current, _needs_rewrite = _decode_settings(self, entry.data)
                result = updater(copy.deepcopy(current))
                persisted = current if result is None else result
                if not isinstance(persisted, dict):
                    raise StorageError("Aggiornamento configurazione non valido")
                entry.data = _encode_settings(self, persisted)  # type: ignore[assignment]
                session.add(entry)
                session.commit()
                return copy.deepcopy(persisted)
            except AppSettingsCryptoError as exc:
                rollback_session_safely(session)
                raise StorageError(str(exc)) from exc
            except SQLAlchemyError as exc:  # pragma: no cover - runtime guard
                rollback_session_safely(session)
                raise StorageError(f"Errore aggiornamento configurazione: {exc}") from exc
            except Exception:
                rollback_session_safely(session)
                raise
            finally:
                close_session_safely(session)
