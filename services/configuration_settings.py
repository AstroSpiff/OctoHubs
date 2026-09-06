"""Shared configuration snapshots and automation persistence."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from core import config_manager
from core.configuration_redaction import (
    public_connection_url,
    public_database_parameters,
    submitted_connection_url,
)
from core.config import (
    DEFAULT_CONFIG,
    _default_auto_tasks,
    _merge_justwatch_settings,
    _merge_trakt_settings,
    _normalize_time_list,
)
from core.utils import _coerce_request_int
from services.app_settings import _update_app_settings_overrides
from services.scheduler_manager import sync_auto_scheduler


AUTOMATION_TASK_IDS = ("scan", "refresh", "workflow", "sync")


def configuration_automation_snapshot(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the automation part of configuration in the API's stable shape."""
    source: dict[str, Any] = config if isinstance(config, dict) else {}
    defaults = _default_auto_tasks()
    current: dict[str, Any] = _mapping(source.get("AUTO_TASKS"))
    tasks = {
        task_id: _task_snapshot(current.get(task_id), defaults[task_id])
        for task_id in AUTOMATION_TASK_IDS
    }
    collection_defaults = DEFAULT_CONFIG["COLLECTIONS"]
    collections: dict[str, Any] = _mapping(source.get("COLLECTIONS"))
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
    """Expose service settings without leaking credentials to the browser."""
    source: dict[str, Any] = config if isinstance(config, dict) else {}
    database: dict[str, Any] = _mapping(source.get("DATABASE"))
    trakt: dict[str, Any] = _mapping(source.get("TRAKT"))
    justwatch: dict[str, Any] = _mapping(source.get("JUSTWATCH"))

    return {
        "database": {
            "enabled": bool(database.get("ENABLED")),
            "host": _string(database.get("HOST")),
            "port": _string(database.get("PORT")),
            "name": _string(database.get("NAME")),
            "user": _string(database.get("USER")),
            "driver": _string(database.get("DRIVER")) or "postgresql+psycopg2",
            "url_configured": bool(database.get("URL")),
            "params": public_database_parameters(database.get("PARAMS")),
            "password_configured": bool(database.get("PASSWORD")),
        },
        "connections": {
            "jellyseerr": _connection_snapshot(source, "JELLYSEERR"),
            "prowlarr": _connection_snapshot(source, "PROWLARR"),
            "jackett": _connection_snapshot(source, "JACKETT"),
            "qbittorrent": {
                "url": public_connection_url(source.get("QBITTORRENT_URL")),
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
            "refresh_token_configured": bool(trakt.get("REFRESH_TOKEN")),
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
    submitted_tasks: dict[str, Any] = _mapping(payload.get("tasks"))
    updated_tasks = {
        task_id: _task_snapshot(submitted_tasks.get(task_id), current["tasks"][task_id])
        for task_id in AUTOMATION_TASK_IDS
    }
    updated_collections = _collection_settings_payload(payload.get("collections"), current["collections"])
    persist_automation_settings(updated_tasks, updated_collections, config)
    return configuration_automation_snapshot(config)


@config_manager.serialized_config_update
def persist_automation_settings(
    tasks: dict[str, Any],
    collections: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Persist scheduler updates through the canonical application-settings path."""
    _update_app_settings_overrides({"AUTO_TASKS": tasks, "COLLECTIONS": collections})

    config_manager.publish_active_config_updates({"AUTO_TASKS": tasks, "COLLECTIONS": collections})
    config["AUTO_TASKS"] = copy.deepcopy(tasks)
    config["COLLECTIONS"] = copy.deepcopy(collections)
    sync_auto_scheduler(True)


@config_manager.serialized_config_update
def update_service_settings(payload: dict[str, Any], config: dict[str, Any]) -> None:
    """Persist integrations while keeping the database deployment-owned."""
    from services.manager import (
        _load_app_settings_snapshot,
        _save_app_settings_snapshot,
    )

    app_settings = _load_app_settings_snapshot()
    source = config | app_settings
    connections = _mapping(payload.get("connections"))
    _update_connection(app_settings, source, connections, "jellyseerr", "JELLYSEERR")
    _update_connection(app_settings, source, connections, "prowlarr", "PROWLARR")
    _update_connection(app_settings, source, connections, "jackett", "JACKETT")

    qbittorrent = _mapping(connections.get("qbittorrent"))
    app_settings["QBITTORRENT_URL"] = _submitted_connection_url(
        qbittorrent,
        "url",
        source.get("QBITTORRENT_URL"),
    )
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
        access_token=_string(trakt_input.get("access_token")),
        refresh_token=_string(trakt_input.get("refresh_token")),
        expires_at=_string(trakt_input.get("expires_at")),
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
    refresh_token: Any = "",
    expires_at: Any = "",
) -> dict[str, Any]:
    """Replace OAuth credentials only as one coherent token set."""
    existing = _mapping(existing_trakt)
    existing_client_id = _string(existing.get("CLIENT_ID"))
    existing_client_secret = _string(existing.get("CLIENT_SECRET"))
    effective_client_id = _string(client_id) or existing_client_id
    effective_client_secret = "" if clear_client_secret else _string(client_secret) or existing_client_secret
    payload: dict[str, Any] = {
        "CLIENT_ID": effective_client_id,
        "CLIENT_SECRET": effective_client_secret,
    }
    for token_key in ("REFRESH_TOKEN", "EXPIRES_AT", "ACCESS_TOKEN"):
        if existing.get(token_key):
            payload[token_key] = existing[token_key]
    submitted_tokens = (
        _string(access_token),
        _string(refresh_token),
        _string(expires_at),
    )
    client_identity_changed = (
        effective_client_id != existing_client_id
        or effective_client_secret != existing_client_secret
    )
    if any(submitted_tokens):
        if not all(submitted_tokens):
            raise ValueError(
                "Token Trakt manuale incompleto: access token, refresh token e scadenza sono obbligatori"
            )
        parsed_expiry = _parse_manual_trakt_expiry(submitted_tokens[2])
        payload["ACCESS_TOKEN"] = submitted_tokens[0]
        payload["REFRESH_TOKEN"] = submitted_tokens[1]
        payload["EXPIRES_AT"] = parsed_expiry.isoformat()
    elif client_identity_changed:
        for token_key in ("ACCESS_TOKEN", "REFRESH_TOKEN", "EXPIRES_AT"):
            payload.pop(token_key, None)
    has_token_set = bool(
        payload.get("ACCESS_TOKEN")
        and payload.get("REFRESH_TOKEN")
        and payload.get("EXPIRES_AT")
    )
    payload["ENABLED"] = True if has_token_set else (
        False if client_identity_changed else _is_true(enabled)
    )
    return payload


def _parse_manual_trakt_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Scadenza token Trakt non valida") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("La scadenza token Trakt deve includere il fuso orario")
    normalized = parsed.astimezone(timezone.utc)
    if normalized <= datetime.now(timezone.utc):
        raise ValueError("La scadenza token Trakt deve essere futura")
    return normalized


def _task_snapshot(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    source: dict[str, Any] = value if isinstance(value, dict) else {}
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
    source: dict[str, Any] = value if isinstance(value, dict) else {}
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
        "url": public_connection_url(config.get(f"{prefix}_URL")),
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


def _submitted_connection_url(values: dict[str, Any], key: str, fallback: Any) -> str:
    if key not in values:
        return _string(fallback)
    return submitted_connection_url(values.get(key), fallback)


def _submitted_secret(values: dict[str, Any], key: str, fallback: Any) -> str:
    if _is_true(values.get(f"clear_{key}")):
        return ""
    submitted = _string(values.get(key))
    return submitted or _string(fallback)


def _update_connection(app_settings: dict[str, Any], source: dict[str, Any], values: dict[str, Any], name: str, prefix: str) -> None:
    connection = _mapping(values.get(name))
    app_settings[f"{prefix}_URL"] = _submitted_connection_url(
        connection,
        "url",
        source.get(f"{prefix}_URL"),
    )
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
