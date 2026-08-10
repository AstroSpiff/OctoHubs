"""HTTP client for the OctoHubs Event Bridge Emby plugin."""

from __future__ import annotations

from typing import Any

from emby_runtime.api_clients_emby import _call_emby_api
from emby_runtime.event_bridge_settings import build_plugin_settings_payload


PLUGIN_CONFIGURATION_PATH = "OctoHubs/EventBridge/Configuration"


def push_event_bridge_settings_to_plugin(
    server: dict[str, Any] | None,
    server_id: str,
    settings: dict[str, Any],
) -> tuple[bool, str, dict[str, Any] | None]:
    """Apply settings through the authenticated Emby plugin API."""
    if not isinstance(server, dict):
        return False, "Server Emby non trovato", None

    plugin_payload = build_plugin_settings_payload(settings)
    payload = _plugin_configuration_payload(server_id, plugin_payload)
    success, response = _call_emby_api(
        server,
        PLUGIN_CONFIGURATION_PATH,
        method="POST",
        json_payload=payload,
    )
    if not success:
        return False, str(response or "chiamata plugin non riuscita"), None

    if isinstance(response, dict):
        ok = response.get("Ok")
        if ok is None:
            ok = response.get("ok")
        applied = response.get("Applied")
        if applied is None:
            applied = response.get("applied")
        if ok is False or applied is False:
            error = response.get("Error") or response.get("error") or "plugin non ha applicato la configurazione"
            return False, str(error), response
        return True, "", response

    return True, "", None


def _plugin_configuration_payload(server_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "ServerId": server_id,
        "Enabled": settings["enabled"],
        "UseWebSocket": settings["useWebSocket"],
        "UseHttpFallback": settings["useHttpFallback"],
        "WebSocketReconnectSeconds": settings["webSocketReconnectSeconds"],
        "CapturePlaybackEvents": settings["capturePlaybackEvents"],
        "CaptureSessionEvents": settings["captureSessionEvents"],
        "CapturePluginEvents": settings["capturePluginEvents"],
        "EventBatchIntervalSeconds": settings["eventBatchIntervalSeconds"],
        "HttpTimeoutSeconds": settings["httpTimeoutSeconds"],
        "RetryCount": settings["retryCount"],
        "IncludeRawPayload": settings["includeRawPayload"],
        "PlaybackEventNames": settings["playbackEventNames"],
        "ProgressEventNames": settings["progressEventNames"],
        "SessionEventNames": settings["sessionEventNames"],
        "PluginEventNames": settings["pluginEventNames"],
    }
