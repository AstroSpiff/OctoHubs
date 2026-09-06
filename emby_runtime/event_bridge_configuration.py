"""Event Bridge configuration services shared by UI and API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.concurrency import run_in_threadpool

from core import config_manager as _config_manager
from core.configuration_redaction import public_connection_url
from core.log_sanitization import sanitize_text_for_log
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_plugin_client import push_event_bridge_settings_to_plugin
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_for_server,
    normalize_event_bridge_config,
    normalize_event_bridge_settings,
)

EVENT_BRIDGE_SETTING_LABELS = {
    "ENABLED": "Abilita",
    "WEBSOCKET_ENABLED": "WebSocket",
    "HTTP_FALLBACK_ENABLED": "Fallback HTTP",
    "WEBSOCKET_RECONNECT_SECONDS": "Reconnect WS",
    "CAPTURE_PLAYBACK_EVENTS": "Playback",
    "CAPTURE_SESSION_EVENTS": "Sessione",
    "CAPTURE_PLUGIN_EVENTS": "Plugin",
    "EVENT_BATCH_INTERVAL_SECONDS": "Batch secondi",
    "HTTP_TIMEOUT_SECONDS": "Timeout HTTP",
    "RETRY_COUNT": "Retry HTTP",
    "INCLUDE_RAW_PAYLOAD": "Raw",
    "PLAYBACK_EVENT_NAMES": "Eventi playback",
    "SESSION_EVENT_NAMES": "Eventi sessione",
    "PLUGIN_EVENT_NAMES": "Eventi plugin",
}


@_config_manager.serialized_config_update
def _save_event_bridge_settings(
    submitted_server_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Atomically merge submitted servers, then publish the committed value."""
    backend = _config_manager._ensure_db_backend()

    def merge_current(current: Any) -> dict[str, Any]:
        return _merged_event_bridge_config(
            normalize_event_bridge_config(current if isinstance(current, dict) else {}),
            submitted_server_settings,
        )

    persisted = backend.update_app_settings_section("EVENT_BRIDGE", merge_current)
    bridge_config = normalize_event_bridge_config(persisted.get("EVENT_BRIDGE"))
    _config_manager.publish_active_config_updates({"EVENT_BRIDGE": bridge_config})
    return bridge_config


def _empty_event_bridge_push_result() -> dict[str, Any]:
    return {"http_pushed": 0, "websocket_pushed": 0, "http_failed": []}


async def _push_event_bridge_settings(
    current_config: dict[str, Any] | None,
    bridge_config: dict[str, Any],
    submitted_server_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Deliver saved settings to plugins, preferring their authenticated HTTP API."""
    result = _empty_event_bridge_push_result()
    manager = get_event_bridge_manager()
    connected_ids = {
        str(item.get("server_id") or "")
        for item in manager.status().get("servers", [])
        if isinstance(item, dict) and item.get("connected")
    }
    target_ids = set(submitted_server_settings) | {server_id for server_id in connected_ids if server_id}
    raw_servers = _raw_emby_servers_by_id(current_config)
    websocket_target_ids = set(target_ids)

    for server_id in sorted(target_ids):
        settings = event_bridge_settings_for_server(bridge_config, server_id)
        http_ok, http_error, response = await run_in_threadpool(
            push_event_bridge_settings_to_plugin,
            raw_servers.get(server_id),
            server_id,
            settings,
        )
        if http_ok:
            result["http_pushed"] += 1
            manager.record_plugin_configuration_response(server_id, response)
            websocket_target_ids.discard(server_id)
        elif raw_servers.get(server_id):
            result["http_failed"].append(f"{server_id}: {http_error}")

    for server_id in sorted(websocket_target_ids):
        result["websocket_pushed"] += await manager.push_configuration(
            server_id,
            event_bridge_settings_for_server(bridge_config, server_id),
        )
    return result


def _event_bridge_push_message(push_result: dict[str, Any], error: str = "") -> str:
    parts: list[str] = []
    http_pushed = int(push_result.get("http_pushed") or 0)
    websocket_pushed = int(push_result.get("websocket_pushed") or 0)
    if http_pushed:
        parts.append(f"{http_pushed} plugin aggiornati via HTTP")
    if websocket_pushed:
        parts.append(f"{websocket_pushed} plugin aggiornati via WebSocket")
    suffix = f" ({', '.join(parts)})" if parts else ""
    if error:
        return f"Event Bridge salvato{suffix}, ma push plugin non riuscito: {error}"
    return f"Event Bridge aggiornato{suffix}"


def _merged_event_bridge_config(
    current_bridge: dict[str, Any],
    submitted_server_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current_bridge = normalize_event_bridge_config(current_bridge)
    merged_servers = {
        str(server_id): settings
        for server_id, settings in (current_bridge.get("SERVERS") or {}).items()
        if str(server_id or "").strip()
    }
    merged_servers.update(submitted_server_settings or {})
    return normalize_event_bridge_config(
        {
            "DEFAULT": current_bridge["DEFAULT"],
            "SERVERS": merged_servers,
        }
    )


def _event_bridge_settings_payload(form: Any, prefix: str) -> dict[str, Any]:
    return {
        "ENABLED": bool(form.get(prefix + "enabled")),
        "WEBSOCKET_ENABLED": bool(form.get(prefix + "websocket_enabled")),
        "HTTP_FALLBACK_ENABLED": bool(form.get(prefix + "http_fallback_enabled")),
        "WEBSOCKET_RECONNECT_SECONDS": form.get(prefix + "ws_reconnect_seconds"),
        "CAPTURE_PLAYBACK_EVENTS": bool(form.get(prefix + "capture_playback")),
        "CAPTURE_SESSION_EVENTS": bool(form.get(prefix + "capture_session")),
        "CAPTURE_PLUGIN_EVENTS": bool(form.get(prefix + "capture_plugin")),
        "EVENT_BATCH_INTERVAL_SECONDS": form.get(prefix + "batch_interval_seconds"),
        "HTTP_TIMEOUT_SECONDS": form.get(prefix + "http_timeout_seconds"),
        "RETRY_COUNT": form.get(prefix + "retry_count"),
        "INCLUDE_RAW_PAYLOAD": bool(form.get(prefix + "include_raw_payload")),
        "PLAYBACK_EVENT_NAMES": form.get(prefix + "playback_event_names"),
        "SESSION_EVENT_NAMES": form.get(prefix + "session_event_names"),
        "PLUGIN_EVENT_NAMES": form.get(prefix + "plugin_event_names"),
    }


def _raw_emby_servers_by_id(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    servers = ((config or {}).get("EMBY") or {}).get("SERVERS") or []
    result: dict[str, dict[str, Any]] = {}
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id = str(server.get("id") or server.get("server_id") or "").strip()
        if server_id:
            result[server_id] = server
    return result


def _event_bridge_servers_for_view(
    emby_servers: list[dict[str, Any]],
    bridge_config: dict[str, Any],
    event_bridge_status: dict[str, Any],
    credential_server_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    credential_server_ids = credential_server_ids or set()
    status_by_id = {
        str(item.get("server_id") or ""): item
        for item in (event_bridge_status or {}).get("servers", [])
        if isinstance(item, dict)
    }
    items: list[dict[str, Any]] = []
    for server in emby_servers or []:
        server_id = str(server.get("id") or server.get("server_id") or "").strip()
        if not server_id:
            continue
        name = server.get("alias") or server.get("original_name") or server.get("name") or server_id
        settings = event_bridge_settings_for_server(bridge_config, server_id)
        diagnostics = _event_bridge_diagnostics(settings, status_by_id.get(server_id))
        items.append(
            {
                "id": server_id,
                "name": name,
                "icon": server.get("icon") or "fa-server",
                "icon_color": server.get("icon_color") or "#3b82f6",
                "icon_style": server.get("icon_style") or "solid",
                "settings": settings,
                "status": status_by_id.get(server_id),
                "settings_editable": _event_bridge_settings_editable(status_by_id.get(server_id)),
                "credential": _event_bridge_credential_payload(server_id in credential_server_ids),
                "diagnostics": diagnostics,
            }
        )
    return items


def _event_bridge_settings_editable(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    return bool(
        status.get("connected")
        or status.get("received_count")
        or status.get("plugin_settings")
        or status.get("last_plugin_settings_at")
        or status.get("last_config_ack_status")
    )


def _event_bridge_credential_payload(configured: bool) -> dict[str, Any]:
    return {
        "configured": configured,
        "label": "Credenziale per-server" if configured else "Da collegare",
        "class_name": "status-ok" if configured else "status-fail",
    }


def _event_bridge_status_payload(bridge_server: dict[str, Any]) -> dict[str, Any]:
    status = bridge_server.get("status") if isinstance(bridge_server.get("status"), dict) else {}
    diagnostics = bridge_server.get("diagnostics") if isinstance(bridge_server.get("diagnostics"), dict) else {}
    return {
        "id": str(bridge_server.get("id") or ""),
        "name": str(bridge_server.get("name") or ""),
        "icon": str(bridge_server.get("icon") or "fa-server"),
        "icon_color": str(bridge_server.get("icon_color") or "#3b82f6"),
        "icon_style": str(bridge_server.get("icon_style") or "solid"),
        "settings_editable": bool(bridge_server.get("settings_editable")),
        "credential": dict(bridge_server.get("credential") or _event_bridge_credential_payload(False)),
        "settings": normalize_event_bridge_settings(bridge_server.get("settings") or {}),
        "transport": _event_bridge_transport_payload(status),
        "config_ack": _event_bridge_config_ack_payload(status),
        "diagnostics": _event_bridge_diagnostics_payload(diagnostics),
    }


def _event_bridge_transport_payload(status: dict[str, Any]) -> dict[str, str]:
    if status.get("connected"):
        return {"label": "WebSocket connesso", "class_name": "status-ok"}
    if status.get("received_count"):
        return {"label": "HTTP ricevuto", "class_name": "status-skip"}
    return {"label": "Non visto", "class_name": "status-skip"}


def _event_bridge_config_ack_payload(status: dict[str, Any]) -> dict[str, str]:
    ack_status = str(status.get("last_config_ack_status") or "").strip()
    if not ack_status:
        return {"label": "", "class_name": "status-skip", "title": ""}

    if ack_status == "applied":
        label = "Config applicata"
        class_name = "status-ok"
    elif ack_status == "pending":
        label = "Config inviata"
        class_name = "status-skip"
    else:
        label = "Errore configurazione"
        class_name = "status-fail"

    return {
        "label": label,
        "class_name": class_name,
        "title": str(
            status.get("last_config_ack_error")
            or _event_bridge_timestamp_label(status.get("last_config_ack_at"))
            or _event_bridge_timestamp_label(status.get("last_config_sent_at"))
            or ""
        ),
    }


def _event_bridge_diagnostics_payload(diagnostics: dict[str, Any]) -> dict[str, Any]:
    plugin_version = str(diagnostics.get("plugin_version") or "").strip()
    sync_status = str(diagnostics.get("sync_status") or "unknown").strip()
    return {
        "sync_status": sync_status,
        "sync_label": str(diagnostics.get("sync_label") or "Report plugin assente"),
        "sync_class": _event_bridge_sync_class(sync_status),
        "plugin_version": plugin_version,
        "plugin_version_label": f"Plugin {plugin_version}" if plugin_version else "Plugin non rilevato",
        "last_seen_at": str(diagnostics.get("last_seen_at") or "Mai"),
        "last_event": str(diagnostics.get("last_event") or "Mai"),
        "last_event_at": str(diagnostics.get("last_event_at") or ""),
        "last_config_sent_at": str(diagnostics.get("last_config_sent_at") or "Mai"),
        "last_config_ack_at": str(diagnostics.get("last_config_ack_at") or "Mai"),
        "last_config_transport_label": _event_bridge_config_transport_label(
            diagnostics.get("last_config_transport")
        ),
        "last_config_ack_error": sanitize_text_for_log(diagnostics.get("last_config_ack_error") or ""),
        "last_plugin_settings_at": str(diagnostics.get("last_plugin_settings_at") or "Mai"),
        "target_count": diagnostics.get("target_count"),
        "target_count_label": (
            str(diagnostics.get("target_count"))
            if diagnostics.get("target_count") is not None
            else "Non riportate"
        ),
        "plugin_targets": _event_bridge_targets_payload(diagnostics.get("plugin_targets")),
        "diffs": _event_bridge_diffs_payload(diagnostics.get("diffs")),
    }


def _event_bridge_sync_class(sync_status: str) -> str:
    if sync_status == "aligned":
        return "status-ok"
    if sync_status == "mismatch":
        return "status-fail"
    return "status-skip"


def _event_bridge_config_transport_label(value: Any) -> str:
    transport = str(value or "").strip().lower()
    if transport == "http":
        return "HTTP"
    if transport == "websocket":
        return "WebSocket"
    return "Non rilevato"


def _event_bridge_targets_payload(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    targets: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        targets.append({
            "name": str(item.get("name") or "OctoHubs").strip(),
            "url": public_connection_url(url),
        })
    return targets


def _event_bridge_diffs_payload(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    diffs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        diffs.append(
            {
                "label": str(item.get("label") or ""),
                "octohubs": str(item.get("octohubs") or ""),
                "plugin": str(item.get("plugin") or ""),
            }
        )
    return diffs


def _event_bridge_diagnostics(settings: dict[str, Any], status: dict[str, Any] | None) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    plugin_settings = status.get("plugin_settings") if isinstance(status.get("plugin_settings"), dict) else {}
    plugin_targets = status.get("plugin_targets") if isinstance(status.get("plugin_targets"), list) else []
    diffs = _event_bridge_setting_differences(settings, plugin_settings)
    if not plugin_settings:
        sync_status = "unknown"
        sync_label = "Report plugin assente"
    elif diffs:
        sync_status = "mismatch"
        sync_label = "Config diversa"
    else:
        sync_status = "aligned"
        sync_label = "Config allineata"

    target_count = status.get("plugin_target_count")
    if target_count is None and plugin_targets:
        target_count = len(plugin_targets)

    last_event = _event_bridge_last_event_label(status)
    return {
        "sync_status": sync_status,
        "sync_label": sync_label,
        "diffs": diffs,
        "plugin_settings_seen": bool(plugin_settings),
        "plugin_version": status.get("plugin_version") or "",
        "target_count": target_count,
        "plugin_targets": plugin_targets,
        "last_event": last_event,
        "last_seen_at": _event_bridge_timestamp_label(status.get("last_seen_at")),
        "last_event_at": _event_bridge_timestamp_label(status.get("last_event_at")),
        "last_plugin_settings_at": _event_bridge_timestamp_label(status.get("last_plugin_settings_at")),
        "last_config_sent_at": _event_bridge_timestamp_label(status.get("last_config_sent_at")),
        "last_config_ack_at": _event_bridge_timestamp_label(status.get("last_config_ack_at")),
        "last_config_transport": status.get("last_config_transport") or "",
        "last_config_ack_status": status.get("last_config_ack_status") or "",
        "last_config_ack_error": sanitize_text_for_log(status.get("last_config_ack_error") or ""),
    }


def _event_bridge_setting_differences(expected: dict[str, Any], reported: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(reported, dict) or not reported:
        return []

    expected = normalize_event_bridge_settings(expected)
    reported = normalize_event_bridge_settings(reported)
    diffs: list[dict[str, str]] = []
    for key, label in EVENT_BRIDGE_SETTING_LABELS.items():
        expected_value = expected.get(key)
        reported_value = reported.get(key)
        if _event_bridge_comparable_value(expected_value) == _event_bridge_comparable_value(reported_value):
            continue
        diffs.append(
            {
                "label": label,
                "octohubs": _event_bridge_value_label(expected_value),
                "plugin": _event_bridge_value_label(reported_value),
            }
        )
    return diffs


def _event_bridge_comparable_value(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value]
    return value


def _event_bridge_value_label(value: Any) -> str:
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "vuoto"
    if value is None or value == "":
        return "vuoto"
    return str(value)


def _event_bridge_last_event_label(status: dict[str, Any]) -> str:
    event_name = str(status.get("last_event_name") or "").strip()
    event_type = str(status.get("last_event_type") or "").strip()
    if event_name and event_type and event_name.lower() != event_type.lower():
        return f"{event_name} ({event_type})"
    return event_name or event_type or ""


def _event_bridge_timestamp_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _event_bridge_trim_timestamp(text)

    label = parsed.isoformat(sep=" ", timespec="seconds")
    return label.replace("+00:00", " UTC")


def _event_bridge_trim_timestamp(value: str) -> str:
    text = value.replace("T", " ")
    if "." not in text:
        return text

    prefix, suffix = text.split(".", 1)
    for marker in ("+", "-"):
        if marker in suffix:
            timezone = suffix[suffix.find(marker):]
            return f"{prefix}{timezone}".replace("+00:00", " UTC")
    if "Z" in suffix:
        return f"{prefix} UTC"
    return prefix
