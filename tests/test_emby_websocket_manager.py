import asyncio
import json

from emby_runtime import websocket_manager
from emby_runtime.websocket_manager import EmbyWebSocketConnection, EmbyWebSocketManager, _is_stream_session_event


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


def test_global_callbacks_are_additive():
    manager = EmbyWebSocketManager()
    calls = []

    manager.set_global_callback(lambda server_id, event: calls.append(("main", server_id, event["MessageType"])))
    manager.add_global_callback(lambda server_id, event: calls.append(("extra", server_id, event["MessageType"])))

    manager._handle_event("server-a", {"MessageType": "PlaybackStart"})

    assert calls == [
        ("main", "server-a", "PlaybackStart"),
        ("extra", "server-a", "PlaybackStart"),
    ]


def test_stream_session_event_detection_ignores_non_playback_events():
    assert _is_stream_session_event({"MessageType": "Sessions"}) is True
    assert _is_stream_session_event({"MessageType": "PlaybackStart"}) is True
    assert _is_stream_session_event({"MessageType": "PlaybackStopped"}) is True
    assert _is_stream_session_event({"MessageType": "GeneralCommand", "Data": {"SessionId": "session-1"}}) is True
    assert _is_stream_session_event({"MessageType": "RefreshProgress"}) is False
    assert _is_stream_session_event({"MessageType": "ConnectionEstablished"}) is False


def test_stream_session_forwarding_passes_playback_event_to_transcode_guard(monkeypatch):
    manager = EmbyWebSocketManager()
    calls = []

    class Guard:
        def record_playback_event(self, server_id, event_data):
            calls.append(("event", server_id, event_data["MessageType"]))

        def wake(self):
            calls.append(("wake",))

    monkeypatch.setattr("emby_runtime.transcode_guard.get_transcode_guard_service", lambda: Guard())

    manager.setup_stream_session_forwarding()
    manager._handle_event("server-a", {
        "MessageType": "PlaybackProgress",
        "Data": {"SessionId": "session-1", "EventName": "QualityChange"},
    })

    assert calls == [
        ("event", "server-a", "PlaybackProgress"),
        ("wake",),
    ]


def test_emby_websocket_subscribes_to_session_updates_on_open():
    connection = EmbyWebSocketConnection("server-a", "http://example.test", "token", lambda *_args: None)
    fake_ws = _FakeWebSocket()
    connection.ws = fake_ws

    connection._on_open(fake_ws)

    assert fake_ws.sent[0] == {"MessageType": "SessionsStart", "Data": "0,1500"}


def test_emby_websocket_unsubscribes_from_session_updates_on_stop():
    connection = EmbyWebSocketConnection("server-a", "http://example.test", "token", lambda *_args: None)
    fake_ws = _FakeWebSocket()
    connection.ws = fake_ws

    connection.stop()

    assert fake_ws.sent[0] == {"MessageType": "SessionsStop"}
    assert fake_ws.closed is True


def test_upsert_server_replaces_changed_connection_without_duplicates(monkeypatch):
    created = []

    class FakeConnection:
        def __init__(self, server_id, server_url, api_key, event_callback):
            self.server_id = server_id
            self.server_url = server_url
            self.api_key = api_key
            self.event_callback = event_callback
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(websocket_manager, "EmbyWebSocketConnection", FakeConnection)
    manager = EmbyWebSocketManager()

    assert manager.upsert_server("green", "http://green:8096/", "first-key") is True
    first = manager.get_connection("green")
    assert first is not None
    assert first.started is True
    assert first.server_url == "http://green:8096"

    assert manager.upsert_server("green", "http://green:8096", "second-key") is True
    replacement = manager.get_connection("green")
    assert replacement is not first
    assert first.stopped is True
    assert replacement is not None
    assert replacement.started is True
    assert replacement.api_key == "second-key"

    assert manager.upsert_server("green", "http://green:8096", "second-key") is False
    assert manager.get_connection("green") is replacement
    assert len(created) == 2


def test_refresh_progress_is_scheduled_on_the_registered_app_loop(monkeypatch):
    manager = EmbyWebSocketManager()
    class _Loop:
        def is_running(self):
            return True

    loop = _Loop()
    scheduled = []

    monkeypatch.setattr("app_state.get_app_event_loop", lambda: loop)
    monkeypatch.setattr(
        asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, target_loop: scheduled.append((coroutine, target_loop)),
    )

    manager.setup_scan_progress_forwarding()
    manager._handle_event(
        "green",
        {"MessageType": "RefreshProgress", "Data": {"ItemId": "library-1", "Progress": 20}},
    )

    assert len(scheduled) == 1
    assert scheduled[0][1] is loop
    scheduled[0][0].close()
