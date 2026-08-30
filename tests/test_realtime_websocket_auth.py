from fastapi import HTTPException
import pytest

from realtime.routes import (
    init_realtime_routes,
    websocket_scan_endpoint,
    websocket_search_endpoint,
    ws_events,
)


class _FakeWebSocket:
    def __init__(self, headers=None):
        self.headers = headers or {}
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

    async def receive_json(self):
        try:
            return next(self._messages)
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

    async def disconnect(self, client_id):
        self.disconnected.append(client_id)

    async def subscribe_to_job(self, _client_id, _job_id):
        return None

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
async def test_scan_socket_ignores_the_removed_legacy_cancel_message(monkeypatch):
    from realtime import routes

    manager = _ScanManager()
    init_realtime_routes(lambda _connection: True)
    monkeypatch.setattr(routes, "get_scan_connection_manager", lambda: manager)

    await websocket_scan_endpoint(
        _ScanWebSocket([{"action": "cancel", "job_id": "obsolete-job"}]),
        "client-1",
    )

    assert manager.connected == ["client-1"]
    assert manager.messages == []
    assert manager.disconnected == ["client-1"]
