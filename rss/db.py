from __future__ import annotations

from typing import Any, Dict

from core.storage import DatabaseStorage, StorageError

_DB_BACKEND = None
_DB_BACKEND_SIGNATURE = None


def _db_enabled(settings: Dict[str, Any] | None) -> bool:
    """Check if database is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))


def _ensure_db_backend(db_settings: Dict[str, Any]) -> DatabaseStorage:
    """Create or return a cached DatabaseStorage instance for given settings."""
    global _DB_BACKEND, _DB_BACKEND_SIGNATURE

    if not _db_enabled(db_settings):
        raise StorageError("Database non abilitato nella configurazione")

    signature = (
        db_settings.get("URL"),
        db_settings.get("HOST"),
        db_settings.get("PORT"),
        db_settings.get("NAME"),
        db_settings.get("USER"),
        db_settings.get("PASSWORD"),
        db_settings.get("DRIVER"),
        db_settings.get("PARAMS")
    )

    if _DB_BACKEND is None or _DB_BACKEND_SIGNATURE != signature:
        backend = DatabaseStorage(db_settings)
        backend.ensure_ready()
        _DB_BACKEND = backend
        _DB_BACKEND_SIGNATURE = signature

    return _DB_BACKEND


def _get_db_backend(db_settings: Dict[str, Any]) -> DatabaseStorage:
    """Get or create database backend instance."""
    return _ensure_db_backend(db_settings)
