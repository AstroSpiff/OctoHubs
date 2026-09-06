from fastapi import HTTPException
import json
import pytest

from realtime.routes import (
    init_realtime_routes,
    websocket_scan_endpoint,
    websocket_search_endpoint,
    ws_events,
)


class _FakeWebSocket:
    def __init__(self, headers=None, scheme=None):
        self.headers = headers or {}
        self.scope = {"scheme": scheme} if scheme else {}
        self.accepted = False
        self.closed = False
        self.close_code = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code


class _ScanWebSocket(_FakeWebSocket):
    def __init__(self, messages):
        super().__init__()
        self._messages = iter(messages)

    async def receive_text(self):
        try:
            message = next(self._messages)
            return message if isinstance(message, str) else json.dumps(message)
        except StopIteration as error:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect() from error


class _ScanManager:
    def __init__(self):
        self.messages = []
        self.connected = []
        self.disconnected = []

    async def connect(self, client_id, _websocket):
        self.connected.append(client_id)
        return True

    async def disconnect(self, client_id):
        self.disconnected.append(client_id)

    async def subscribe_to_job(self, _client_id, _job_id):
        return True

    async def unsubscribe_from_job(self, _client_id, _job_id):
        return None

    async def send_personal_message(self, _client_id, message):
        self.messages.append(message)


def _reject_auth(_connection):
    raise HTTPException(status_code=401, detail="Authentication required")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("handler", "arguments"),
    [
        (ws_events, ()),
        (websocket_scan_endpoint, ("client-1",)),
        (websocket_search_endpoint, ("search-1",)),
    ],
)
async def test_realtime_websockets_reject_unauthenticated_clients(handler, arguments):
    init_realtime_routes(_reject_auth)
    websocket = _FakeWebSocket()

    await handler(websocket, *arguments)

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_realtime_websockets_reject_cross_origin_connections_before_authentication():
    init_realtime_routes(lambda _connection: True)
    websocket = _FakeWebSocket(
        headers={"origin": "https://untrusted.example", "host": "octohubs.example"},
    )

    await ws_events(websocket)

    assert websocket.accepted is False
    assert websocket.closed is True
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_realtime_websockets_reject_same_host_cross_scheme_origin():
    from realtime.routes import _authorize_websocket

    init_realtime_routes(lambda _connection: True)
    websocket = _FakeWebSocket(
        headers={"origin": "http://octohubs.example", "host": "octohubs.example"},
        scheme="wss",
    )

    subject = await _authorize_websocket(websocket)

    assert subject is None
    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_scan_socket_ignores_the_removed_legacy_cancel_message(monkeypatch):
    from realtime import routes

    manager = _ScanManager()
    init_realtime_routes(lambda _connection: True)
    monkeypatch.setattr(routes, "get_scan_connection_manager", lambda: manager)

    websocket = _ScanWebSocket([{"action": "cancel", "job_id": "obsolete-job"}])
    await websocket_scan_endpoint(
        websocket,
        "client-1",
    )

    assert manager.connected == ["client-1"]
    assert manager.messages == []
    assert manager.disconnected == ["client-1"]
    assert websocket.close_code == 1008
