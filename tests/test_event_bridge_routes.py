"""Event Bridge WebSocket routes."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


class _Service:
    def __init__(self):
        self.payloads = []

    def record_event_bridge_event(self, payload):
        self.payloads.append(payload)
        return {"recorded": True, "event": payload.get("event")}


class _FakeWebSocket:
    def __init__(self, messages, headers=None):
        self._messages = list(messages)
        self.headers = headers or {}
        self.accepted = False
        self.closed = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code

    async def receive_json(self):
        if not self._messages:
            raise WebSocketDisconnect(code=1000)
        return self._messages.pop(0)

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.anyio
async def test_event_bridge_websocket_accepts_plugin_events(monkeypatch):
    from emby_runtime.event_bridge_routes import init_event_bridge_routes, router
    from emby_runtime.event_bridge_routes import api_event_bridge_websocket

    service = _Service()
    monkeypatch.setenv("WEBHOOK_SECRET", "bridge-secret")
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
            {
                "schema": "octohubs.emby.event.v1",
                "server": {"id": "green", "name": "Green"},
                "event": {"type": "playback.start", "name": "PlaybackStart"},
            },
        ],
        headers={"X-Webhook-Secret": "bridge-secret"},
    )

    await api_event_bridge_websocket(websocket)

    assert websocket.accepted is True
    assert websocket.sent[0]["type"] == "hello_ack"
    assert websocket.sent[0]["settings"]["progressEventNames"] == "QualityChange"
    assert websocket.sent[1]["type"] == "event_ack"
    assert websocket.sent[1]["processed"] == 1
    assert service.payloads[0]["event"]["name"] == "PlaybackStart"
    assert service.payloads[0]["_eventBridgeTransport"] == "websocket"


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
