"""Configuration helpers for the Emby Event Bridge."""

from __future__ import annotations

from typing import Any


DEFAULT_PLAYBACK_EVENT_NAMES = [
    "PlaybackStart",
    "PlaybackStopped",
    "Pause",
    "Unpause",
    "QualityChange",
    "AudioTrackChange",
    "SubtitleTrackChange",
]

DEFAULT_SESSION_EVENT_NAMES: list[str] = []

DEFAULT_PLUGIN_EVENT_NAMES = [
    "plugin.start",
    "plugin.config_saved",
]

DEFAULT_EVENT_BRIDGE_SETTINGS: dict[str, Any] = {
    "ENABLED": True,
    "WEBSOCKET_ENABLED": True,
    "HTTP_FALLBACK_ENABLED": True,
    "WEBSOCKET_RECONNECT_SECONDS": 5,
    "CAPTURE_PLAYBACK_EVENTS": True,
    "CAPTURE_SESSION_EVENTS": True,
    "CAPTURE_PLUGIN_EVENTS": True,
    "EVENT_BATCH_INTERVAL_SECONDS": 1,
    "HTTP_TIMEOUT_SECONDS": 5,
    "RETRY_COUNT": 1,
    "INCLUDE_RAW_PAYLOAD": False,
    "PLAYBACK_EVENT_NAMES": DEFAULT_PLAYBACK_EVENT_NAMES,
    "SESSION_EVENT_NAMES": DEFAULT_SESSION_EVENT_NAMES,
    "PLUGIN_EVENT_NAMES": DEFAULT_PLUGIN_EVENT_NAMES,
}

EVENT_BRIDGE_CONFIG_KEYS = {"DEFAULT", "SERVERS"}


def normalize_event_bridge_settings(value: dict[str, Any] | None = None) -> dict[str, Any]:
    source = value or {}
    settings = dict(DEFAULT_EVENT_BRIDGE_SETTINGS)

    for key in (
        "ENABLED",
        "WEBSOCKET_ENABLED",
        "HTTP_FALLBACK_ENABLED",
        "CAPTURE_PLAYBACK_EVENTS",
        "CAPTURE_SESSION_EVENTS",
        "CAPTURE_PLUGIN_EVENTS",
        "INCLUDE_RAW_PAYLOAD",
    ):
        if key in source:
            settings[key] = _bool_value(source.get(key), bool(settings[key]))

    for key, minimum in (
        ("WEBSOCKET_RECONNECT_SECONDS", 1),
        ("EVENT_BATCH_INTERVAL_SECONDS", 0),
        ("HTTP_TIMEOUT_SECONDS", 1),
        ("RETRY_COUNT", 0),
    ):
        if key in source:
            settings[key] = _int_value(source.get(key), int(settings[key]), minimum)

    for key in ("PLAYBACK_EVENT_NAMES", "SESSION_EVENT_NAMES", "PLUGIN_EVENT_NAMES"):
        if key in source:
            settings[key] = _event_names(source.get(key))
        else:
            settings[key] = list(settings[key])

    return settings


def normalize_event_bridge_config(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize the canonical DEFAULT/SERVERS Event Bridge container."""
    source = value or {}
    if not _is_structured_config(source):
        source = {}
    default_settings = normalize_event_bridge_settings(source.get("DEFAULT") or {})
    servers_source = source.get("SERVERS") or {}
    servers: dict[str, dict[str, Any]] = {}
    if isinstance(servers_source, dict):
        for server_id, raw_settings in servers_source.items():
            key = str(server_id or "").strip()
            if not key or not isinstance(raw_settings, dict):
                continue
            servers[key] = normalize_event_bridge_settings({**default_settings, **raw_settings})
    return {"DEFAULT": default_settings, "SERVERS": servers}


def event_bridge_settings_for_server(config: dict[str, Any] | None, server_id: str | None = None) -> dict[str, Any]:
    normalized = normalize_event_bridge_config(config)
    default_settings = normalized["DEFAULT"]
    key = str(server_id or "").strip()
    if not key:
        return dict(default_settings)
    server_settings = normalized["SERVERS"].get(key)
    if not server_settings:
        return dict(default_settings)
    return normalize_event_bridge_settings({**default_settings, **server_settings})


def build_plugin_settings_payload(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_event_bridge_settings(settings)
    return {
        "enabled": normalized["ENABLED"],
        "useWebSocket": normalized["WEBSOCKET_ENABLED"],
        "useHttpFallback": normalized["HTTP_FALLBACK_ENABLED"],
        "webSocketReconnectSeconds": normalized["WEBSOCKET_RECONNECT_SECONDS"],
        "capturePlaybackEvents": normalized["CAPTURE_PLAYBACK_EVENTS"],
        "captureSessionEvents": normalized["CAPTURE_SESSION_EVENTS"],
        "capturePluginEvents": normalized["CAPTURE_PLUGIN_EVENTS"],
        "eventBatchIntervalSeconds": normalized["EVENT_BATCH_INTERVAL_SECONDS"],
        "httpTimeoutSeconds": normalized["HTTP_TIMEOUT_SECONDS"],
        "retryCount": normalized["RETRY_COUNT"],
        "includeRawPayload": normalized["INCLUDE_RAW_PAYLOAD"],
        "playbackEventNames": "\n".join(normalized["PLAYBACK_EVENT_NAMES"]),
        "progressEventNames": "\n".join(normalized["PLAYBACK_EVENT_NAMES"]),
        "sessionEventNames": "\n".join(normalized["SESSION_EVENT_NAMES"]),
        "pluginEventNames": "\n".join(normalized["PLUGIN_EVENT_NAMES"]),
    }


def event_bridge_settings_from_plugin_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload or {}
    return normalize_event_bridge_settings(
        {
            "ENABLED": source.get("enabled"),
            "WEBSOCKET_ENABLED": source.get("useWebSocket"),
            "HTTP_FALLBACK_ENABLED": source.get("useHttpFallback"),
            "WEBSOCKET_RECONNECT_SECONDS": source.get("webSocketReconnectSeconds"),
            "CAPTURE_PLAYBACK_EVENTS": source.get("capturePlaybackEvents"),
            "CAPTURE_SESSION_EVENTS": source.get("captureSessionEvents"),
            "CAPTURE_PLUGIN_EVENTS": source.get("capturePluginEvents"),
            "EVENT_BATCH_INTERVAL_SECONDS": source.get("eventBatchIntervalSeconds"),
            "HTTP_TIMEOUT_SECONDS": source.get("httpTimeoutSeconds"),
            "RETRY_COUNT": source.get("retryCount"),
            "INCLUDE_RAW_PAYLOAD": source.get("includeRawPayload"),
            "PLAYBACK_EVENT_NAMES": source.get("playbackEventNames") or source.get("progressEventNames"),
            "SESSION_EVENT_NAMES": source.get("sessionEventNames"),
            "PLUGIN_EVENT_NAMES": source.get("pluginEventNames"),
        }
    )


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "on", "yes", "y", "si", "sì"}:
        return True
    if text in {"0", "false", "off", "no", "n", ""}:
        return False
    return default


def _int_value(value: Any, default: int, minimum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _event_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.replace("\r\n", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value]
    else:
        candidates = [str(value)]

    names: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        name = str(item or "").strip()
        if not name or name.startswith("#"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _is_structured_config(value: dict[str, Any]) -> bool:
    return any(key in value for key in EVENT_BRIDGE_CONFIG_KEYS)
