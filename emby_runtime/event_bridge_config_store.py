"""Persistence helpers for Event Bridge configuration reported by plugins."""

from __future__ import annotations

from typing import Any

from core import config_manager as _config_manager
from core.config_manager import load_config
from core.storage import StorageError
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_from_plugin_payload,
    normalize_event_bridge_config,
)


def apply_plugin_reported_settings(payload: dict[str, Any]) -> bool:
    """Persist settings sent by a plugin after its Emby-side configuration changes."""
    if not isinstance(payload, dict):
        return False

    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    event_type = str(event.get("type") or payload.get("eventType") or "").strip().lower()
    if event_type != "plugin.config_saved":
        return False

    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    server_id = str(server.get("id") or payload.get("serverId") or "").strip()
    plugin_settings = payload.get("plugin") if isinstance(payload.get("plugin"), dict) else {}
    if not server_id or not plugin_settings:
        return False

    current_config, _is_valid = load_config()
    bridge_config = normalize_event_bridge_config((current_config or {}).get("EVENT_BRIDGE", {}))
    bridge_config["SERVERS"][server_id] = event_bridge_settings_from_plugin_payload(plugin_settings)
    try:
        _save_event_bridge_config(bridge_config)
    except StorageError as exc:
        print(f"[EVENT_BRIDGE] Impossibile salvare config plugin per {server_id}: {exc}")
        return False
    return True


def _save_event_bridge_config(settings: dict[str, Any]) -> None:
    if _config_manager._ACTIVE_CONFIG is not None:
        _config_manager._ACTIVE_CONFIG["EVENT_BRIDGE"] = settings
    backend = _config_manager._ensure_db_backend()
    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        raise StorageError("Impostazioni applicazione non valide")
    app_settings["EVENT_BRIDGE"] = settings
    backend.save_app_settings(app_settings)
