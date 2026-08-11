"""Event Bridge WebSocket connection manager."""

from __future__ import annotations

import pytest


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.anyio
async def test_event_bridge_manager_tracks_websocket_connections_and_pushes_config():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    websocket = _FakeWebSocket()

    await manager.register(
        websocket,
        {
            "serverId": "green",
            "serverName": "Green",
            "pluginVersion": "0.2.0",
        },
    )
    pushed = await manager.push_configuration(
        "green",
        {
            "WEBSOCKET_ENABLED": True,
            "HTTP_FALLBACK_ENABLED": False,
            "PLAYBACK_EVENT_NAMES": ["PlaybackStart", "QualityChange"],
        },
    )
    status = manager.status()

    assert pushed == 1
    assert status["connected"] == 1
    assert status["servers"][0]["server_id"] == "green"
    assert status["servers"][0]["server_name"] == "Green"
    assert status["servers"][0]["transport"] == "websocket"
    assert status["servers"][0]["last_config_ack_status"] == "pending"
    assert status["servers"][0]["last_config_message_id"]
    assert websocket.sent[0]["type"] == "configure"
    assert websocket.sent[0]["id"] == status["servers"][0]["last_config_message_id"]
    assert websocket.sent[0]["settings"]["useWebSocket"] is True
    assert websocket.sent[0]["settings"]["useHttpFallback"] is False
    assert websocket.sent[0]["settings"]["progressEventNames"] == "PlaybackStart\nQualityChange"

    manager.record_config_ack(
        websocket,
        {
            "type": "configure_ack",
            "id": websocket.sent[0]["id"],
            "serverId": "green",
            "ok": True,
            "applied": True,
        },
    )
    status = manager.status()

    assert status["servers"][0]["last_config_ack_status"] == "applied"
    assert status["servers"][0]["last_config_ack_message_id"] == websocket.sent[0]["id"]


@pytest.mark.anyio
async def test_event_bridge_manager_pushes_configuration_only_to_target_server():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    green_socket = _FakeWebSocket()
    blue_socket = _FakeWebSocket()

    await manager.register(green_socket, {"serverId": "green", "serverName": "Green"})
    await manager.register(blue_socket, {"serverId": "blue", "serverName": "Blue"})

    pushed = await manager.push_configuration(
        "green",
        {
            "PLAYBACK_EVENT_NAMES": ["QualityChange"],
        },
    )

    assert pushed == 1
    assert green_socket.sent[0]["settings"]["progressEventNames"] == "QualityChange"
    assert blue_socket.sent == []


def test_event_bridge_manager_tracks_http_events_without_connection():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()

    manager.record_http_event(
        {
            "schema": "octohubs.emby.event_batch.v1",
            "events": [
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.start"}},
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.stop"}},
            ],
        }
    )
    status = manager.status()

    assert status["connected"] == 0
    assert status["servers"][0]["server_id"] == "green"
    assert status["servers"][0]["server_name"] == "Green"
    assert status["servers"][0]["transport"] == "http"
    assert status["servers"][0]["received_count"] == 2
    assert status["servers"][0]["last_event_type"] == "playback.stop"


def test_event_bridge_manager_tracks_plugin_reported_settings_and_targets():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()

    manager.record_http_event(
        {
            "schema": "octohubs.emby.event.v1",
            "server": {"id": "green", "name": "Green"},
            "event": {"type": "plugin.config_saved", "name": "PluginConfigSaved"},
            "plugin": {
                "version": "0.4.2",
                "useWebSocket": False,
                "webSocketReconnectSeconds": 3,
                "octoHubsTargetCount": 2,
                "octoHubsTargets": [
                    {"name": "OctoHubs 1", "url": "https://primary.example"},
                    {"name": "OctoHubs 2", "url": "https://secondary.example"},
                ],
            },
        }
    )
    status = manager.status()["servers"][0]

    assert status["plugin_version"] == "0.4.2"
    assert status["last_plugin_settings_at"]
    assert status["plugin_settings"]["WEBSOCKET_ENABLED"] is False
    assert status["plugin_settings"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert status["plugin_target_count"] == 2
    assert status["plugin_targets"] == [
        {"name": "OctoHubs 1", "url": "https://primary.example"},
        {"name": "OctoHubs 2", "url": "https://secondary.example"},
    ]
    assert status["last_event_name"] == "PluginConfigSaved"


def test_event_bridge_manager_records_http_configuration_response():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()

    manager.record_plugin_configuration_response(
        "green",
        {
            "Ok": True,
            "Applied": True,
            "ServerName": "Green",
            "PluginVersion": "0.4.2",
            "Settings": {
                "useWebSocket": False,
                "webSocketReconnectSeconds": 3,
                "octoHubsTargetCount": 1,
            },
        },
    )
    status = manager.status()["servers"][0]

    assert status["server_id"] == "green"
    assert status["server_name"] == "Green"
    assert status["transport"] == "http"
    assert status["plugin_version"] == "0.4.2"
    assert status["last_config_ack_status"] == "applied"
    assert status["last_config_sent_at"]
    assert status["last_config_ack_at"]
    assert status["last_plugin_settings_at"]
    assert status["plugin_settings"]["WEBSOCKET_ENABLED"] is False
    assert status["plugin_settings"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert status["plugin_target_count"] == 1


def test_event_bridge_manager_tracks_legacy_octohub_http_batches():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()

    manager.record_http_event(
        {
            "schema": "octohub.emby.event_batch.v1",
            "events": [
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.start"}},
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.stop"}},
            ],
        }
    )
    status = manager.status()

    assert status["servers"][0]["server_id"] == "green"
    assert status["servers"][0]["received_count"] == 2
