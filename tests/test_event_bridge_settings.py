"""Event Bridge settings normalization."""

from __future__ import annotations


def test_event_bridge_settings_normalize_flags_limits_and_event_names():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_settings

    settings = normalize_event_bridge_settings(
        {
            "WEBSOCKET_ENABLED": "on",
            "HTTP_FALLBACK_ENABLED": "",
            "EVENT_BATCH_INTERVAL_SECONDS": "0",
            "HTTP_TIMEOUT_SECONDS": "0",
            "RETRY_COUNT": "-3",
            "PLAYBACK_EVENT_NAMES": "PlaybackStart\n#VolumeChange\nQualityChange\nQualityChange\n",
            "SESSION_EVENT_NAMES": ["session.started", "#session.activity", "session.ended"],
            "PLUGIN_EVENT_NAMES": "",
        }
    )

    assert settings["WEBSOCKET_ENABLED"] is True
    assert settings["HTTP_FALLBACK_ENABLED"] is False
    assert settings["EVENT_BATCH_INTERVAL_SECONDS"] == 0
    assert settings["HTTP_TIMEOUT_SECONDS"] == 1
    assert settings["RETRY_COUNT"] == 0
    assert settings["PLAYBACK_EVENT_NAMES"] == ["PlaybackStart", "QualityChange"]
    assert settings["SESSION_EVENT_NAMES"] == ["session.started", "session.ended"]
    assert settings["PLUGIN_EVENT_NAMES"] == []


def test_event_bridge_settings_payload_uses_plugin_field_names():
    from emby_runtime.event_bridge_settings import build_plugin_settings_payload, normalize_event_bridge_settings

    settings = normalize_event_bridge_settings(
        {
            "ENABLED": True,
            "WEBSOCKET_ENABLED": True,
            "HTTP_FALLBACK_ENABLED": False,
            "WEBSOCKET_RECONNECT_SECONDS": 8,
            "CAPTURE_PLAYBACK_EVENTS": True,
            "CAPTURE_SESSION_EVENTS": False,
            "CAPTURE_PLUGIN_EVENTS": True,
            "EVENT_BATCH_INTERVAL_SECONDS": 2,
            "HTTP_TIMEOUT_SECONDS": 4,
            "RETRY_COUNT": 0,
            "INCLUDE_RAW_PAYLOAD": False,
            "PLAYBACK_EVENT_NAMES": ["PlaybackStart", "QualityChange"],
            "SESSION_EVENT_NAMES": [],
            "PLUGIN_EVENT_NAMES": ["plugin.start"],
        }
    )

    payload = build_plugin_settings_payload(settings)

    assert payload == {
        "enabled": True,
        "useWebSocket": True,
        "useHttpFallback": False,
        "webSocketReconnectSeconds": 8,
        "capturePlaybackEvents": True,
        "captureSessionEvents": False,
        "capturePluginEvents": True,
        "eventBatchIntervalSeconds": 2,
        "httpTimeoutSeconds": 4,
        "retryCount": 0,
        "includeRawPayload": False,
        "playbackEventNames": "PlaybackStart\nQualityChange",
        "progressEventNames": "PlaybackStart\nQualityChange",
        "sessionEventNames": "",
        "pluginEventNames": "plugin.start",
    }


def test_event_bridge_settings_from_plugin_payload_reads_complete_plugin_report():
    from emby_runtime.event_bridge_settings import event_bridge_settings_from_plugin_payload

    settings = event_bridge_settings_from_plugin_payload(
        {
            "enabled": False,
            "useWebSocket": True,
            "useHttpFallback": False,
            "webSocketReconnectSeconds": 8,
            "capturePlaybackEvents": True,
            "captureSessionEvents": False,
            "capturePluginEvents": True,
            "eventBatchIntervalSeconds": 2,
            "httpTimeoutSeconds": 4,
            "retryCount": 0,
            "includeRawPayload": False,
            "playbackEventNames": "PlaybackStart\nPlaybackStopped\nQualityChange",
            "progressEventNames": "TimeUpdate",
            "sessionEventNames": "session.started",
            "pluginEventNames": "plugin.config_saved",
        }
    )

    assert settings["ENABLED"] is False
    assert settings["WEBSOCKET_ENABLED"] is True
    assert settings["HTTP_FALLBACK_ENABLED"] is False
    assert settings["WEBSOCKET_RECONNECT_SECONDS"] == 8
    assert settings["CAPTURE_PLAYBACK_EVENTS"] is True
    assert settings["CAPTURE_SESSION_EVENTS"] is False
    assert settings["CAPTURE_PLUGIN_EVENTS"] is True
    assert settings["EVENT_BATCH_INTERVAL_SECONDS"] == 2
    assert settings["HTTP_TIMEOUT_SECONDS"] == 4
    assert settings["RETRY_COUNT"] == 0
    assert settings["INCLUDE_RAW_PAYLOAD"] is False
    assert settings["PLAYBACK_EVENT_NAMES"] == ["PlaybackStart", "PlaybackStopped", "QualityChange"]
    assert settings["SESSION_EVENT_NAMES"] == ["session.started"]
    assert settings["PLUGIN_EVENT_NAMES"] == ["plugin.config_saved"]


def test_event_bridge_config_supports_server_overrides_with_default_fallback():
    from emby_runtime.event_bridge_settings import (
        event_bridge_settings_for_server,
        normalize_event_bridge_config,
    )

    config = normalize_event_bridge_config(
        {
            "DEFAULT": {
                "WEBSOCKET_ENABLED": True,
                "HTTP_FALLBACK_ENABLED": True,
                "PLAYBACK_EVENT_NAMES": ["PlaybackStart"],
            },
            "SERVERS": {
                "green": {
                    "WEBSOCKET_ENABLED": False,
                    "HTTP_FALLBACK_ENABLED": False,
                    "PLAYBACK_EVENT_NAMES": ["QualityChange"],
                }
            },
        }
    )

    green = event_bridge_settings_for_server(config, "green")
    blue = event_bridge_settings_for_server(config, "blue")

    assert green["WEBSOCKET_ENABLED"] is False
    assert green["HTTP_FALLBACK_ENABLED"] is False
    assert green["PLAYBACK_EVENT_NAMES"] == ["QualityChange"]
    assert blue["WEBSOCKET_ENABLED"] is True
    assert blue["HTTP_FALLBACK_ENABLED"] is True
    assert blue["PLAYBACK_EVENT_NAMES"] == ["PlaybackStart"]


def test_event_bridge_config_ignores_removed_flat_settings_shape():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config

    config = normalize_event_bridge_config(
        {
            "WEBSOCKET_ENABLED": False,
            "PLAYBACK_EVENT_NAMES": "PlaybackStart\nQualityChange",
        }
    )

    assert config["DEFAULT"]["WEBSOCKET_ENABLED"] is True
    assert config["DEFAULT"]["PLAYBACK_EVENT_NAMES"] != ["PlaybackStart", "QualityChange"]
    assert config["SERVERS"] == {}
