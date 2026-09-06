"""Persistence helpers for Event Bridge configuration reported by plugins."""

from __future__ import annotations

import logging
import threading
from typing import Any

from core import config_manager as _config_manager
from core.log_sanitization import format_exception_for_log
from core.storage import StorageError
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_from_plugin_payload,
    normalize_event_bridge_config,
)

_plugin_report_lock = threading.RLock()
logger = logging.getLogger(__name__)


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
        saved = _save_plugin_server_settings(server_id, server_settings)
    except StorageError as exc:
        logger.error(
            "[EVENT_BRIDGE] Impossibile salvare config plugin per %s:\n%s",
            server_id,
            format_exception_for_log(exc),
        )
        return False
    return saved


@_config_manager.serialized_config_update
def _save_plugin_server_settings(server_id: str, settings: dict[str, Any]) -> bool:
    saved = False

    def update_all(current: dict[str, Any]) -> dict[str, Any]:
        nonlocal saved
        emby = current.get("EMBY") if isinstance(current.get("EMBY"), dict) else {}
        servers = emby.get("SERVERS") if isinstance(emby, dict) else []
        if not any(
            isinstance(server, dict)
            and str(server.get("id") or server.get("server_id") or "").strip() == server_id
            for server in (servers or [])
        ):
            return current
        bridge_config = normalize_event_bridge_config(current.get("EVENT_BRIDGE"))
        bridge_config["SERVERS"][server_id] = settings
        current["EVENT_BRIDGE"] = bridge_config
        saved = True
        return current

    with _plugin_report_lock:
        backend = _config_manager._ensure_db_backend()
        persisted = backend.mutate_app_settings(update_all)
        if not saved:
            return False
        bridge_config = normalize_event_bridge_config(persisted.get("EVENT_BRIDGE"))
        _config_manager.publish_active_config_updates({"EVENT_BRIDGE": bridge_config})
        return True
