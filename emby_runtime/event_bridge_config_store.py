"""Persistence helpers for Event Bridge configuration reported by plugins."""

from __future__ import annotations

import threading
from typing import Any

from core import config_manager as _config_manager
from core.storage import StorageError
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_from_plugin_payload,
    normalize_event_bridge_config,
)

_plugin_report_lock = threading.RLock()


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

    server_settings = event_bridge_settings_from_plugin_payload(plugin_settings)
    try:
        _save_plugin_server_settings(server_id, server_settings)
    except StorageError as exc:
        print(f"[EVENT_BRIDGE] Impossibile salvare config plugin per {server_id}: {exc}")
        return False
    return True


def _save_plugin_server_settings(server_id: str, settings: dict[str, Any]) -> None:
    def update_server(current: Any) -> dict[str, Any]:
        bridge_config = normalize_event_bridge_config(current if isinstance(current, dict) else {})
        bridge_config["SERVERS"][server_id] = settings
        return bridge_config

    with _plugin_report_lock:
        backend = _config_manager._ensure_db_backend()
        persisted = backend.update_app_settings_section("EVENT_BRIDGE", update_server)
        bridge_config = normalize_event_bridge_config(persisted.get("EVENT_BRIDGE"))
        if _config_manager._ACTIVE_CONFIG is not None:
            _config_manager._ACTIVE_CONFIG["EVENT_BRIDGE"] = bridge_config
