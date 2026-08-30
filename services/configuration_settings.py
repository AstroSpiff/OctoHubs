"""Shared configuration snapshots and automation persistence."""

from __future__ import annotations

import copy
from typing import Any

from core import config_manager
from core.config import (
    DEFAULT_CONFIG,
    _default_auto_tasks,
    _merge_database_settings,
    _merge_justwatch_settings,
    _merge_trakt_settings,
    _normalize_time_list,
    read_raw_config,
)
from core.storage import DatabaseStorage, StorageError
from core.utils import _coerce_request_int
from services.app_settings import _update_app_settings_overrides
from services.scheduler_manager import sync_auto_scheduler


AUTOMATION_TASK_IDS = ("scan", "refresh", "workflow", "sync")


def configuration_automation_snapshot(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the automation part of configuration in the API's stable shape."""
    source = config or {}
    defaults = _default_auto_tasks()
    current = source.get("AUTO_TASKS") if isinstance(source.get("AUTO_TASKS"), dict) else {}
    tasks = {
        task_id: _task_snapshot(current.get(task_id), defaults[task_id])
        for task_id in AUTOMATION_TASK_IDS
    }
    collection_defaults = DEFAULT_CONFIG["COLLECTIONS"]
    collections = source.get("COLLECTIONS") if isinstance(source.get("COLLECTIONS"), dict) else {}
    return {
        "tasks": tasks,
        "collections": {
            "enabled": bool(collections.get("AUTO_REFRESH_ENABLED", collection_defaults["AUTO_REFRESH_ENABLED"])),
            "mode": _mode_value(collections.get("AUTO_REFRESH_MODE"), collection_defaults["AUTO_REFRESH_MODE"]),
            "interval_minutes": _coerce_request_int(
                collections.get("AUTO_REFRESH_INTERVAL_MINUTES"),
                collection_defaults["AUTO_REFRESH_INTERVAL_MINUTES"],
                5,
                10080,
            ),
            "times": _normalize_time_list(collections.get("AUTO_REFRESH_TIMES")),
        },
    }


def configuration_services_snapshot(config: dict[str, Any] | None) -> dict[str, Any]:
    """Expose editable service settings without leaking credentials to the browser."""
    source = config or {}
    database = source.get("DATABASE") if isinstance(source.get("DATABASE"), dict) else {}
    trakt = source.get("TRAKT") if isinstance(source.get("TRAKT"), dict) else {}
    justwatch = source.get("JUSTWATCH") if isinstance(source.get("JUSTWATCH"), dict) else {}

    return {
        "database": {
            "enabled": bool(database.get("ENABLED")),
            "host": _string(database.get("HOST")),
            "port": _string(database.get("PORT")),
            "name": _string(database.get("NAME")),
            "user": _string(database.get("USER")),
            "driver": _string(database.get("DRIVER")) or "postgresql+psycopg2",
            "url_configured": bool(database.get("URL")),
            "params": _string(database.get("PARAMS")),
            "password_configured": bool(database.get("PASSWORD")),
        },
        "connections": {
            "jellyseerr": _connection_snapshot(source, "JELLYSEERR"),
            "prowlarr": _connection_snapshot(source, "PROWLARR"),
            "jackett": _connection_snapshot(source, "JACKETT"),
            "qbittorrent": {
                "url": _string(source.get("QBITTORRENT_URL")),
                "username": _string(source.get("QBITTORRENT_USERNAME")),
                "password_configured": bool(source.get("QBITTORRENT_PASSWORD")),
            },
            "tmdb": {
                "language": _string(source.get("TMDB_LANGUAGE")) or "it-IT",
                "api_key_configured": bool(source.get("TMDB_API_KEY")),
            },
            "mdblist": {"api_keys_configured": len(_string_list(source.get("MDBLIST_API_KEYS")))},
            "omdb": {"api_keys_configured": len(_string_list(source.get("OMDB_API_KEYS")))},
        },
        "trakt": {
            "enabled": bool(trakt.get("ENABLED")),
            "client_id": _string(trakt.get("CLIENT_ID")),
            "client_secret_configured": bool(trakt.get("CLIENT_SECRET")),
            "access_token_configured": bool(trakt.get("ACCESS_TOKEN")),
            "expires_at": _string(trakt.get("EXPIRES_AT")),
        },
        "justwatch": {
            "enabled": bool(justwatch.get("ENABLED")),
            "locale": _string(justwatch.get("LOCALE")) or "it_IT",
        },
    }


def update_automation_settings(
    payload: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Normalize, persist and activate automation settings from a JSON payload."""
    current = configuration_automation_snapshot(config)
    submitted_tasks = payload.get("tasks") if isinstance(payload.get("tasks"), dict) else {}
    updated_tasks = {
        task_id: _task_snapshot(submitted_tasks.get(task_id), current["tasks"][task_id])
        for task_id in AUTOMATION_TASK_IDS
    }
    updated_collections = _collection_settings_payload(payload.get("collections"), current["collections"])
    persist_automation_settings(updated_tasks, updated_collections, config)
    return configuration_automation_snapshot(config)


def persist_automation_settings(
    tasks: dict[str, Any],
    collections: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Persist legacy and React scheduler updates through the same write path."""
    _update_app_settings_overrides({"AUTO_TASKS": tasks, "COLLECTIONS": collections})

    if config_manager._ACTIVE_CONFIG is None:
        config_manager._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    config_manager._ACTIVE_CONFIG["AUTO_TASKS"] = copy.deepcopy(tasks)
    config_manager._ACTIVE_CONFIG["COLLECTIONS"] = copy.deepcopy(collections)
    config["AUTO_TASKS"] = copy.deepcopy(tasks)
    config["COLLECTIONS"] = copy.deepcopy(collections)
    sync_auto_scheduler(True)


def update_service_settings(payload: dict[str, Any], config: dict[str, Any]) -> None:
    """Persist service integrations while preserving secrets omitted by the browser."""
    from services.manager import (
        _apply_db_env_overrides,
        _load_app_settings_snapshot,
        _save_app_settings_snapshot,
        _seed_db_from_legacy_config,
        _write_database_config,
    )

    database_input = _mapping(payload.get("database"))
    current_database = _mapping(config.get("DATABASE"))
    legacy_database = _mapping((read_raw_config() or {}).get("DATABASE"))
    database_payload = {
        "ENABLED": True,
        "HOST": _submitted_text(database_input, "host", current_database.get("HOST") or legacy_database.get("HOST")),
        "PORT": _submitted_port(database_input, current_database.get("PORT") or legacy_database.get("PORT")),
        "NAME": _submitted_text(database_input, "name", current_database.get("NAME") or legacy_database.get("NAME")),
        "USER": _submitted_text(database_input, "user", current_database.get("USER") or legacy_database.get("USER")),
        "PASSWORD": _submitted_secret(database_input, "password", current_database.get("PASSWORD") or legacy_database.get("PASSWORD")),
        "DRIVER": _submitted_text(database_input, "driver", current_database.get("DRIVER") or legacy_database.get("DRIVER") or "postgresql+psycopg2"),
        "URL": _submitted_secret(database_input, "url", current_database.get("URL") or legacy_database.get("URL")),
        "PARAMS": _submitted_text(database_input, "params", current_database.get("PARAMS") or legacy_database.get("PARAMS")),
    }
    db_settings_base = _merge_database_settings(database_payload)
    db_settings_effective = _apply_db_env_overrides(db_settings_base)
    if not db_settings_effective.get("URL") and (
        not db_settings_effective.get("HOST")
        or not db_settings_effective.get("NAME")
        or not db_settings_effective.get("USER")
    ):
        raise ValueError("Compila host, database e username.")

    backend = DatabaseStorage(db_settings_effective)
    backend.ensure_ready()
    _seed_db_from_legacy_config(read_raw_config() or {}, backend)
    _write_database_config(db_settings_base)

    app_settings = _load_app_settings_snapshot()
    source = config | app_settings
    connections = _mapping(payload.get("connections"))
    _update_connection(app_settings, source, connections, "jellyseerr", "JELLYSEERR")
    _update_connection(app_settings, source, connections, "prowlarr", "PROWLARR")
    _update_connection(app_settings, source, connections, "jackett", "JACKETT")

    qbittorrent = _mapping(connections.get("qbittorrent"))
    app_settings["QBITTORRENT_URL"] = _submitted_text(qbittorrent, "url", source.get("QBITTORRENT_URL"))
    app_settings["QBITTORRENT_USERNAME"] = _submitted_text(qbittorrent, "username", source.get("QBITTORRENT_USERNAME"))
    app_settings["QBITTORRENT_PASSWORD"] = _submitted_secret(qbittorrent, "password", source.get("QBITTORRENT_PASSWORD"))

    tmdb = _mapping(connections.get("tmdb"))
    app_settings["TMDB_LANGUAGE"] = _submitted_text(tmdb, "language", source.get("TMDB_LANGUAGE") or "it-IT")
    app_settings["TMDB_API_KEY"] = _submitted_secret(tmdb, "api_key", source.get("TMDB_API_KEY"))
    _update_api_key_list(app_settings, source, connections, "mdblist", "MDBLIST_API_KEYS")
    _update_api_key_list(app_settings, source, connections, "omdb", "OMDB_API_KEYS")
    app_settings["OMDB_API_KEY"] = (app_settings.get("OMDB_API_KEYS") or [""])[0]

    current_trakt = _mapping(source.get("TRAKT"))
    trakt_input = _mapping(payload.get("trakt"))
    trakt_payload = build_trakt_settings_payload(
        current_trakt,
        client_id=_submitted_text(trakt_input, "client_id", current_trakt.get("CLIENT_ID")),
        client_secret=_submitted_secret(trakt_input, "client_secret", current_trakt.get("CLIENT_SECRET")),
        clear_client_secret=_is_true(trakt_input.get("clear_client_secret")),
        access_token=_submitted_secret(trakt_input, "access_token", current_trakt.get("ACCESS_TOKEN")),
        enabled=trakt_input.get("enabled", current_trakt.get("ENABLED")),
    )
    app_settings["TRAKT"] = _merge_trakt_settings(trakt_payload)

    current_justwatch = _mapping(source.get("JUSTWATCH"))
    justwatch_input = _mapping(payload.get("justwatch"))
    app_settings["JUSTWATCH"] = _merge_justwatch_settings({
        "ENABLED": _is_true(justwatch_input.get("enabled", current_justwatch.get("ENABLED"))),
        "LOCALE": _submitted_text(justwatch_input, "locale", current_justwatch.get("LOCALE") or "it_IT"),
    })
    _save_app_settings_snapshot(app_settings)


def build_trakt_settings_payload(
    existing_trakt: Any,
    *,
    client_id: Any,
    client_secret: Any,
    access_token: Any,
    enabled: Any,
    clear_client_secret: bool = False,
) -> dict[str, Any]:
    """Keep Trakt refresh credentials when a form changes unrelated fields."""
    existing = _mapping(existing_trakt)
    payload: dict[str, Any] = {
        "CLIENT_ID": _string(client_id) or _string(existing.get("CLIENT_ID")),
        "CLIENT_SECRET": "" if clear_client_secret else _string(client_secret) or _string(existing.get("CLIENT_SECRET")),
    }
    for token_key in ("REFRESH_TOKEN", "EXPIRES_AT", "ACCESS_TOKEN"):
        if existing.get(token_key):
            payload[token_key] = existing[token_key]
    if _string(access_token):
        payload["ACCESS_TOKEN"] = _string(access_token)
    payload["ENABLED"] = _is_true(enabled) if not (payload.get("REFRESH_TOKEN") and payload.get("ACCESS_TOKEN")) else True
    return payload


def _task_snapshot(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": bool(source.get("enabled", fallback.get("enabled", False))),
        "mode": _mode_value(source.get("mode"), fallback.get("mode", "interval")),
        "interval_minutes": _coerce_request_int(
            source.get("interval_minutes"),
            _coerce_request_int(fallback.get("interval_minutes"), 60, 1),
            1,
        ),
        "times": _normalize_time_list(source.get("times", fallback.get("times", []))),
    }


def _collection_settings_payload(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "AUTO_REFRESH_ENABLED": bool(source.get("enabled", fallback["enabled"])),
        "AUTO_REFRESH_MODE": _mode_value(source.get("mode"), fallback["mode"]),
        "AUTO_REFRESH_INTERVAL_MINUTES": _coerce_request_int(
            source.get("interval_minutes"), fallback["interval_minutes"], 5, 10080
        ),
        "AUTO_REFRESH_TIMES": _normalize_time_list(source.get("times", fallback["times"])),
    }


def _mode_value(value: Any, fallback: Any) -> str:
    candidate = str(value or fallback or "interval").strip().lower()
    return candidate if candidate in {"interval", "fixed"} else "interval"


def _connection_snapshot(config: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "url": _string(config.get(f"{prefix}_URL")),
        "api_key_configured": bool(config.get(f"{prefix}_API_KEY")),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _string(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _submitted_text(values: dict[str, Any], key: str, fallback: Any) -> str:
    return _string(values[key]) if key in values else _string(fallback)


def _submitted_secret(values: dict[str, Any], key: str, fallback: Any) -> str:
    if _is_true(values.get(f"clear_{key}")):
        return ""
    submitted = _string(values.get(key))
    return submitted or _string(fallback)


def _submitted_port(values: dict[str, Any], fallback: Any) -> int | str:
    raw = values.get("port", fallback)
    return _coerce_request_int(raw, 5432) if _string(raw) else ""


def _update_connection(app_settings: dict[str, Any], source: dict[str, Any], values: dict[str, Any], name: str, prefix: str) -> None:
    connection = _mapping(values.get(name))
    app_settings[f"{prefix}_URL"] = _submitted_text(connection, "url", source.get(f"{prefix}_URL"))
    app_settings[f"{prefix}_API_KEY"] = _submitted_secret(connection, "api_key", source.get(f"{prefix}_API_KEY"))


def _update_api_key_list(app_settings: dict[str, Any], source: dict[str, Any], values: dict[str, Any], name: str, key: str) -> None:
    item = _mapping(values.get(name))
    if _is_true(item.get("clear_api_keys")):
        app_settings[key] = []
        return
    if "api_keys" not in item:
        app_settings[key] = _string_list(source.get(key))
        return
    app_settings[key] = _string_list(item.get("api_keys"))


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "configuration_automation_snapshot",
    "configuration_services_snapshot",
    "build_trakt_settings_payload",
    "persist_automation_settings",
    "update_service_settings",
    "update_automation_settings",
]
