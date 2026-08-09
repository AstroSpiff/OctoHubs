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
    assert websocket.sent[0]["type"] == "configure"
    assert websocket.sent[0]["settings"]["useWebSocket"] is True
    assert websocket.sent[0]["settings"]["useHttpFallback"] is False
    assert websocket.sent[0]["settings"]["progressEventNames"] == "PlaybackStart\nQualityChange"


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
