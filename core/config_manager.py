"""Config loading and database backend helpers."""

from __future__ import annotations

import copy
from functools import wraps
import logging
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from core.log_sanitization import format_exception_for_log
from core.config import (
    CONNECTION_FIELDS,
    DEFAULT_CONFIG,
    _default_search_rules,
    _merge_collection_settings,
    _merge_database_settings,
    _merge_emby_settings,
    _merge_justwatch_settings,
    _merge_resolution_settings,
    _merge_trakt_settings,
    _normalize_auto_settings,
    _normalize_sort_settings,
)
from core.storage import DatabaseStorage, StorageError
from emby_runtime.event_bridge_settings import normalize_event_bridge_config
from emby_users.registry import refresh_emby_user_manager_config
from search.indexers import _jackett_configured, _prowlarr_configured


logger = logging.getLogger(__name__)

_ACTIVE_CONFIG: Optional[Dict[str, Any]] = copy.deepcopy(DEFAULT_CONFIG)
_DB_BACKEND: Optional[DatabaseStorage] = None
_DB_BACKEND_SIGNATURE: Optional[Tuple[Any, ...]] = None
_SYNC_AUTO_SCHEDULER: Optional[Callable[[bool], None]] = None
_CONFIG_LOAD_LOCK = threading.RLock()


def _serialized_config_load(
    callback: Callable[[], Tuple[Optional[Dict[str, Any]], bool]],
) -> Callable[[], Tuple[Optional[Dict[str, Any]], bool]]:
    @wraps(callback)
    def locked() -> Tuple[Optional[Dict[str, Any]], bool]:
        with _CONFIG_LOAD_LOCK:
            return callback()

    return locked


def serialized_config_update(callback: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize a DB configuration mutation through runtime publication."""
    @wraps(callback)
    def locked(*args: Any, **kwargs: Any) -> Any:
        with _CONFIG_LOAD_LOCK:
            return callback(*args, **kwargs)

    return locked


def publish_active_config_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically replace the process-local snapshot with committed updates."""
    global _ACTIVE_CONFIG
    with _CONFIG_LOAD_LOCK:
        snapshot = copy.deepcopy(_ACTIVE_CONFIG if _ACTIVE_CONFIG is not None else DEFAULT_CONFIG)
        for key, value in updates.items():
            snapshot[key] = copy.deepcopy(value)
        _ACTIVE_CONFIG = snapshot
        return snapshot


def set_sync_auto_scheduler(callback: Callable[[bool], None]) -> None:
    """Register a callback to sync the AutoScheduler after config load."""
    global _SYNC_AUTO_SCHEDULER
    _SYNC_AUTO_SCHEDULER = callback


def _apply_db_env_overrides(db_settings: Dict[str, Any]) -> Dict[str, Any]:
    from services.manager import _apply_db_env_overrides as _apply_db_env_overrides_impl

    return _apply_db_env_overrides_impl(db_settings)


def _get_effective_db_settings(raw_config: Dict[str, Any] | None) -> Dict[str, Any]:
    """Resolve database settings only from the deployment environment."""
    del raw_config
    base = _merge_database_settings(None)
    return _apply_db_env_overrides(base)


def _ensure_db_backend_for_settings(db_config: Dict[str, Any] | None) -> DatabaseStorage:
    """Create or return the database backend for explicit DB settings."""
    global _DB_BACKEND, _DB_BACKEND_SIGNATURE

    db_config = db_config or {}
    if not db_config.get("ENABLED"):
        raise StorageError("Database non abilitato nella configurazione")

    signature = (
        db_config.get("URL"),
        db_config.get("HOST"),
        db_config.get("PORT"),
        db_config.get("NAME"),
        db_config.get("USER"),
        db_config.get("PASSWORD"),
        db_config.get("DRIVER"),
        db_config.get("PARAMS"),
    )

    if _DB_BACKEND is None or _DB_BACKEND_SIGNATURE != signature:
        try:
            backend = DatabaseStorage(db_config)
            backend.ensure_ready()
        except Exception as exc:
            _DB_BACKEND = None
            _DB_BACKEND_SIGNATURE = None
            raise StorageError(f"Connessione database non disponibile: {exc}") from exc
        _DB_BACKEND = backend
        _DB_BACKEND_SIGNATURE = signature

    return _DB_BACKEND


def _ensure_db_backend() -> DatabaseStorage:
    """Create or return the database backend instance."""
    if _ACTIVE_CONFIG is None:
        raise StorageError("Configurazione non caricata")

    return _ensure_db_backend_for_settings(_ACTIVE_CONFIG.get("DATABASE", {}))


def close_database_backend() -> None:
    """Dispose the shared storage pool while keeping the backend reusable."""
    backend = _DB_BACKEND
    if backend is not None:
        backend.close()


def _db_enabled(settings: Dict[str, Any] | None) -> bool:
    if not settings:
        return False
    return bool(settings.get("ENABLED"))


def _get_db_backend(settings: Dict[str, Any] | None) -> DatabaseStorage:
    return _ensure_db_backend_for_settings(settings)


@_serialized_config_load
def load_config() -> Tuple[Optional[Dict[str, Any]], bool]:
    """Load the canonical runtime configuration from PostgreSQL."""
    global _ACTIVE_CONFIG

    database_settings = _get_effective_db_settings(None)
    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged["DATABASE"] = database_settings

    if not _db_enabled(database_settings):
        print("   -> Il database risulta disattivato nelle impostazioni: abilitalo per proseguire.")
        _ACTIVE_CONFIG = merged
        return merged, False

    try:
        backend = _get_db_backend(database_settings)
        if not backend:
            print("   -> Impossibile inizializzare la connessione al database.")
            _ACTIVE_CONFIG = merged
            return merged, False
    except StorageError as exc:
        logger.error("Database non disponibile:\n%s", format_exception_for_log(exc))
        merged["DATABASE"]["ENABLED"] = False
        _ACTIVE_CONFIG = merged
        return merged, False

    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        app_settings = {}
    search_rules = _default_search_rules()
    for key in CONNECTION_FIELDS:
        if key in app_settings:
            value = app_settings.get(key)
            if isinstance(value, list):
                merged[key] = value
            else:
                merged[key] = value or ""
    merged["TRAKT"] = _merge_trakt_settings(app_settings.get("TRAKT"))
    merged["JUSTWATCH"] = _merge_justwatch_settings(app_settings.get("JUSTWATCH"))
    merged["EMBY"] = _merge_emby_settings(app_settings.get("EMBY"))

    target_langs = app_settings.get("TARGET_LANGUAGES") or merged["TARGET_LANGUAGES"]
    exclude_tags = app_settings.get("EXCLUDE_TAGS") or merged["EXCLUDE_TAGS"]
    search_rules.update(app_settings.get("SEARCH_RULES") or {})
    search_rules = _normalize_sort_settings(search_rules)
    resolution_rules = _merge_resolution_settings(app_settings.get("RESOLUTION_RULES"))
    auto_settings = _normalize_auto_settings(app_settings.get("AUTO_TASKS"))
    collection_settings = _merge_collection_settings(app_settings.get("COLLECTIONS"))
    event_bridge_config = normalize_event_bridge_config(app_settings.get("EVENT_BRIDGE"))

    if not app_settings or "AUTO_TASKS" not in app_settings:
        persisted = dict(app_settings)
        persisted.update(
            {
                "TARGET_LANGUAGES": target_langs,
                "EXCLUDE_TAGS": exclude_tags,
                "SEARCH_RULES": search_rules,
                "RESOLUTION_RULES": resolution_rules,
                "AUTO_TASKS": auto_settings,
                "TRAKT": merged["TRAKT"],
                "JUSTWATCH": merged["JUSTWATCH"],
                "EMBY": merged["EMBY"],
                "COLLECTIONS": collection_settings,
                "EVENT_BRIDGE": event_bridge_config,
            }
        )
        for key in CONNECTION_FIELDS:
            value = merged.get(key)
            if value is None:
                persisted[key] = DEFAULT_CONFIG.get(key, "")
            else:
                persisted[key] = value
        app_settings = backend.seed_app_settings(persisted)
    else:
        app_settings.setdefault("COLLECTIONS", collection_settings)

    request_rules = backend.load_request_rules()

    merged["TARGET_LANGUAGES"] = target_langs
    merged["EXCLUDE_TAGS"] = exclude_tags
    merged["SEARCH_RULES"] = search_rules
    merged["RESOLUTION_RULES"] = resolution_rules
    merged["REQUEST_RULES"] = request_rules or {}
    merged["AUTO_TASKS"] = auto_settings
    merged["COLLECTIONS"] = collection_settings
    merged["EVENT_BRIDGE"] = event_bridge_config

    jellyseerr_ok = bool(merged.get("JELLYSEERR_URL") and merged.get("JELLYSEERR_API_KEY"))
    prowlarr_ok = _prowlarr_configured(merged)
    jackett_ok = _jackett_configured(merged)
    connection_valid = jellyseerr_ok and (prowlarr_ok or jackett_ok)

    _ACTIVE_CONFIG = merged
    refresh_emby_user_manager_config(merged)
    # Keep the already-created Latest singleton aligned with each committed
    # configuration snapshot without creating it during config-only callers.
    from emby_latest.manager import reconfigure_manager_if_initialized

    reconfigure_manager_if_initialized(merged, backend)

    if _SYNC_AUTO_SCHEDULER is not None:
        try:
            _SYNC_AUTO_SCHEDULER(connection_valid)
        except Exception as exc:
            logger.error("Errore sync AutoScheduler:\n%s", format_exception_for_log(exc))

    return merged, True
