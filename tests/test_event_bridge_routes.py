"""Event Bridge WebSocket routes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from emby_runtime.event_bridge_auth import EventBridgePrincipal


@pytest.fixture(autouse=True)
def _server_credentials(monkeypatch):
    from emby_runtime.event_bridge_limits import reset_event_bridge_ingress_limiter

    reset_event_bridge_ingress_limiter()
    monkeypatch.setattr(
        "emby_runtime.event_bridge_routes.authenticate_event_bridge",
        lambda headers: EventBridgePrincipal(str(headers.get("X-OctoHubs-Server-Id") or "")),
    )
    yield
    reset_event_bridge_ingress_limiter()


class _Service:
    def __init__(self):
        self.payloads = []

    def record_event_bridge_event(self, payload):
        self.payloads.append(payload)
        return {"recorded": True, "event": payload.get("event")}


class _FakeWebSocket:
    def __init__(self, messages, headers=None, client_host="127.0.0.1"):
        self._messages = list(messages)
        self.headers = headers or {}
        self.client = SimpleNamespace(host=client_host)
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code

    async def receive(self):
        if not self._messages:
            raise WebSocketDisconnect(code=1000)
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        if isinstance(message, bytes):
            return {"type": "websocket.receive", "bytes": message}
        if isinstance(message, str):
            return {"type": "websocket.receive", "text": message}
        return {"type": "websocket.receive", "text": json.dumps(message)}

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.anyio
async def test_event_bridge_websocket_accepts_plugin_events(monkeypatch):
    from emby_runtime.event_bridge_routes import init_event_bridge_routes, router
    from emby_runtime.event_bridge_routes import api_event_bridge_websocket
    from emby_runtime.event_bridge_manager import get_event_bridge_manager

    service = _Service()
    def settings_for_server(server_id=None):
        if server_id == "green":
            return {
                "WEBSOCKET_ENABLED": True,
                "HTTP_FALLBACK_ENABLED": True,
                "PLAYBACK_EVENT_NAMES": ["QualityChange"],
            }
        return {
            "WEBSOCKET_ENABLED": True,
            "HTTP_FALLBACK_ENABLED": True,
            "PLAYBACK_EVENT_NAMES": ["PlaybackStart"],
        }

    init_event_bridge_routes(
        get_service=lambda: service,
        get_settings=settings_for_server,
    )
    assert any(getattr(route, "path", "") == "/ws/emby/event-bridge" for route in router.routes)

    websocket = _FakeWebSocket(
        [
            {"type": "hello", "serverId": "green", "serverName": "Green"},
            {"type": "configure_ack", "serverId": "green", "id": "cfg-green-test", "ok": True, "applied": True},
            {
                "schema": "octohubs.emby.event.v1",
                "server": {"id": "green", "name": "Green"},
                "event": {"type": "playback.start", "name": "PlaybackStart"},
            },
        ],
        headers={"X-Webhook-Secret": "bridge-secret", "X-OctoHubs-Server-Id": "green"},
    )

    await api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "hello_ack"
    assert websocket.sent[0]["settings"]["progressEventNames"] == "QualityChange"
    assert websocket.sent[1]["type"] == "event_ack"
    assert websocket.sent[1]["processed"] == 1
    assert service.payloads[0]["event"]["name"] == "PlaybackStart"
    assert service.payloads[0]["_eventBridgeTransport"] == "websocket"
    status_by_id = {
        item["server_id"]: item
        for item in get_event_bridge_manager().status()["servers"]
    }
    assert status_by_id["green"]["last_config_ack_status"] == "applied"
    assert status_by_id["green"]["last_config_ack_message_id"] == "cfg-green-test"
    assert status_by_id["green"]["connected"] is False


@pytest.mark.anyio
async def test_event_bridge_websocket_cleans_up_after_unexpected_loop_error(monkeypatch):
    from emby_runtime import event_bridge_routes
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    monkeypatch.setattr(event_bridge_routes, "get_event_bridge_manager", lambda: manager)
    websocket = _FakeWebSocket(
        [
            {"type": "hello", "serverId": "green", "serverName": "Green"},
            RuntimeError("unexpected receive failure"),
        ],
        headers={"X-Webhook-Secret": "bridge-secret", "X-OctoHubs-Server-Id": "green"},
    )

    with pytest.raises(RuntimeError, match="unexpected receive failure"):
        await event_bridge_routes.api_event_bridge_websocket(websocket)

    status = manager.status()
    assert status["connected"] == 0
    assert status["servers"][0]["connected"] is False
    assert manager._websocket_servers == {}


@pytest.mark.anyio
async def test_event_bridge_websocket_cleans_up_after_partial_registration(monkeypatch):
    from emby_runtime import event_bridge_routes
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()
    original_register = manager.register

    async def register_then_fail(websocket, payload):
        await original_register(websocket, payload)
        raise RuntimeError("registration follow-up failed")

    monkeypatch.setattr(manager, "register", register_then_fail)
    monkeypatch.setattr(event_bridge_routes, "get_event_bridge_manager", lambda: manager)
    websocket = _FakeWebSocket(
        [{"type": "hello", "serverId": "green", "serverName": "Green"}],
        headers={"X-Webhook-Secret": "bridge-secret", "X-OctoHubs-Server-Id": "green"},
    )

    with pytest.raises(RuntimeError, match="registration follow-up failed"):
        await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert manager.status()["connected"] == 0
    assert manager._websocket_servers == {}


@pytest.mark.anyio
async def test_event_bridge_websocket_rejects_non_whitelisted_source(monkeypatch):
    from emby_runtime import event_bridge_routes

    monkeypatch.setenv("WEBHOOK_IP_WHITELIST", "10.0.0.0/8")
    monkeypatch.delenv("WEBHOOK_TRUST_PROXY_HEADERS", raising=False)
    websocket = _FakeWebSocket(
        [],
        headers={"X-Webhook-Secret": "bridge-secret", "X-OctoHubs-Server-Id": "green"},
        client_host="192.0.2.12",
    )

    await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_event_bridge_websocket_rejects_a_different_server_identity(monkeypatch):
    from emby_runtime import event_bridge_routes

    websocket = _FakeWebSocket(
        [{"type": "hello", "serverId": "blue", "serverName": "Blue"}],
        headers={"X-Webhook-Secret": "green-token", "X-OctoHubs-Server-Id": "green"},
    )

    await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_event_bridge_websocket_closes_oversized_frames_with_message_too_big():
    from emby_runtime import event_bridge_routes
    from emby_runtime.event_bridge_limits import EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES

    websocket = _FakeWebSocket(
        ["x" * (EVENT_BRIDGE_MAX_WEBSOCKET_FRAME_BYTES + 1)],
        headers={"X-Webhook-Secret": "green-token", "X-OctoHubs-Server-Id": "green"},
    )

    await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.close_code == 1009


@pytest.mark.anyio
async def test_event_bridge_websocket_closes_oversized_batches_with_policy_violation():
    from emby_runtime import event_bridge_routes
    from emby_runtime.event_bridge_limits import EVENT_BRIDGE_MAX_BATCH_EVENTS

    websocket = _FakeWebSocket(
        [
            {
                "schema": "octohubs.emby.event_batch.v1",
                "events": [
                    {"serverId": "green", "eventName": "Pause"}
                    for _ in range(EVENT_BRIDGE_MAX_BATCH_EVENTS + 1)
                ],
            }
        ],
        headers={"X-Webhook-Secret": "green-token", "X-OctoHubs-Server-Id": "green"},
    )

    await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_event_bridge_websocket_closes_when_server_quota_is_exhausted(monkeypatch):
    from emby_runtime import event_bridge_routes

    monkeypatch.setattr(
        event_bridge_routes,
        "consume_event_bridge_ingress",
        lambda _server_id, _payload: False,
    )
    websocket = _FakeWebSocket(
        [{"type": "hello", "serverId": "green", "serverName": "Green"}],
        headers={"X-Webhook-Secret": "green-token", "X-OctoHubs-Server-Id": "green"},
    )

    await event_bridge_routes.api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.close_code == 1008


def test_event_bridge_transport_marks_batched_events():
    from emby_runtime.event_bridge_payloads import event_bridge_payloads, mark_event_bridge_transport

    payload = mark_event_bridge_transport(
        {
            "schema": "octohubs.emby.event_batch.v1",
            "events": [
                {"event": {"name": "PlaybackStart"}},
                {"event": {"name": "Stopped"}},
            ],
        },
        "http_fallback",
    )

    events = event_bridge_payloads(payload)

    assert [event["_eventBridgeTransport"] for event in events] == ["http_fallback", "http_fallback"]
