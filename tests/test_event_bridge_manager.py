"""Event Bridge WebSocket connection manager."""

from __future__ import annotations

import pytest


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class _ClosableWebSocket(_FakeWebSocket):
    async def close(self, code=1000):
        self.close_code = code


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
    assert status["servers"][0]["last_config_transport"] == "websocket"
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


@pytest.mark.anyio
async def test_disconnect_from_replaced_socket_preserves_the_current_connection():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    previous_socket = _FakeWebSocket()
    current_socket = _FakeWebSocket()
    await manager.register(previous_socket, {"serverId": "green"})
    await manager.register(current_socket, {"serverId": "green"})

    await manager.disconnect(previous_socket)

    assert manager.status()["connected"] == 1
    assert await manager.push_configuration("green", {}) == 1
    assert previous_socket.sent == []
    assert current_socket.sent[0]["type"] == "configure"


@pytest.mark.anyio
async def test_socket_replacement_waits_for_inflight_side_effect_dispatch():
    import asyncio

    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    previous_socket = _FakeWebSocket()
    current_socket = _FakeWebSocket()
    await manager.register(previous_socket, {"serverId": "green"})

    async with manager.websocket_dispatch(previous_socket) as current:
        assert current is True
        replacement = asyncio.create_task(
            manager.register(current_socket, {"serverId": "green"})
        )
        await asyncio.sleep(0)
        assert replacement.done() is False

    await replacement
    assert manager.status()["servers"][0]["generation"] == 2


@pytest.mark.anyio
async def test_credential_rotation_closes_the_current_server_socket():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    websocket = _ClosableWebSocket()
    await manager.register(websocket, {"serverId": "green"})

    closed = await manager.close_server_connection("green")

    assert closed is True
    assert websocket.close_code == 1008
    assert manager.status()["connected"] == 0


@pytest.mark.anyio
async def test_shutdown_closes_admission_and_discards_loop_bound_state():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    websocket = _ClosableWebSocket()
    await manager.register(websocket, {"serverId": "green"})

    await manager.shutdown()

    assert websocket.close_code == 1001
    assert manager.status()["servers"] == []
    assert manager._dispatch_locks == {}
    manager.record_http_event({"serverId": "late"})
    assert manager.status()["servers"] == []
    with pytest.raises(RuntimeError, match="shutting down"):
        await manager.register(_FakeWebSocket(), {"serverId": "blue"})


def test_new_lifespan_replaces_event_bridge_manager_without_reusing_locks():
    from emby_runtime import event_bridge_manager

    previous = event_bridge_manager.initialize_event_bridge_manager()
    previous_lock = previous._dispatch_lock("green")
    current = event_bridge_manager.initialize_event_bridge_manager()

    assert current is event_bridge_manager.get_event_bridge_manager()
    assert current is not previous
    assert current._dispatch_lock("green") is not previous_lock


@pytest.mark.anyio
async def test_credential_rotation_detaches_socket_when_close_never_finishes(monkeypatch):
    import asyncio

    from emby_runtime import event_bridge_manager

    class _StalledWebSocket(_FakeWebSocket):
        async def close(self, code=1000):
            await asyncio.Event().wait()

    monkeypatch.setattr(event_bridge_manager, "EVENT_BRIDGE_SEND_TIMEOUT_SECONDS", 0.01)
    manager = event_bridge_manager.EventBridgeConnectionManager()
    websocket = _StalledWebSocket()
    await manager.register(websocket, {"serverId": "green"})

    assert await asyncio.wait_for(manager.close_server_connection("green"), 0.2) is True
    assert manager.status()["connected"] == 0


@pytest.mark.anyio
async def test_reregistering_one_socket_disconnects_its_previous_server_identity():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    websocket = _FakeWebSocket()
    await manager.register(websocket, {"serverId": "green"})
    await manager.register(websocket, {"serverId": "blue"})

    statuses = {item["server_id"]: item for item in manager.status()["servers"]}
    assert statuses["green"]["connected"] is False
    assert statuses["blue"]["connected"] is True
    assert manager.status()["connected"] == 1


@pytest.mark.anyio
async def test_websocket_event_cannot_create_a_second_connected_server_identity():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    websocket = _FakeWebSocket()
    await manager.register(websocket, {"serverId": "green", "serverName": "Green"})

    manager.record_websocket_event(
        websocket,
        {
            "server": {"id": "blue", "name": "Unexpected Blue"},
            "event": {"type": "playback.start"},
        },
    )

    statuses = {item["server_id"]: item for item in manager.status()["servers"]}
    assert set(statuses) == {"green"}
    assert statuses["green"]["connected"] is True


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


def test_event_bridge_manager_publishes_state_changes(monkeypatch):
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager
    from realtime import manager as realtime_manager

    events = []
    monkeypatch.setattr(
        realtime_manager,
        "publish_application_event",
        lambda message_type, data: events.append((message_type, data)),
    )
    manager = EventBridgeConnectionManager()

    manager.record_http_event(
        {
            "schema": "octohubs.emby.event.v1",
            "server": {"id": "green", "name": "Green"},
            "event": {"type": "plugin.start"},
        }
    )

    assert events == [
        (
            "OctoHubsEventBridgeUpdated",
            {"server_ids": ["green"], "reason": "event_received"},
        )
    ]


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


def test_event_bridge_public_status_redacts_plugin_urls_and_ack_errors():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    canary = "EVENT_BRIDGE_CANARY_SECRET"
    manager = EventBridgeConnectionManager()
    manager.record_http_event(
        {
            "server": {"id": "green"},
            "event": {"type": "plugin.config_saved"},
            "plugin": {
                "octoHubsTargets": [
                    {"name": "Primary", "url": f"https://user:{canary}@example.test/hook?token={canary}"}
                ]
            },
        }
    )
    manager.record_plugin_configuration_response(
        "green",
        {"Ok": False, "Error": f"failed https://example.test/hook?token={canary}"},
    )

    public = manager.status()["servers"][0]

    assert canary not in str(public)
    assert "[REDACTED]" in public["plugin_targets"][0]["url"]
    assert "[REDACTED]" in public["last_config_ack_error"]


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
    assert status["last_config_transport"] == "http"
    assert status["last_config_sent_at"]
    assert status["last_config_ack_at"]
    assert status["last_plugin_settings_at"]
    assert status["plugin_settings"]["WEBSOCKET_ENABLED"] is False
    assert status["plugin_settings"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert status["plugin_target_count"] == 1


def test_event_bridge_rejects_removed_octohub_batch_schema():
    import pytest
    from emby_runtime.event_bridge_limits import (
        EventBridgePayloadShapeError,
        validate_event_bridge_payload_shape,
    )

    with pytest.raises(EventBridgePayloadShapeError, match="non supportato"):
        validate_event_bridge_payload_shape({
            "schema": "octohub.emby.event_batch.v1",
            "events": [
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.start"}},
                {"server": {"id": "green", "name": "Green"}, "event": {"type": "playback.stop"}},
            ],
        })
