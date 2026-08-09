from datetime import datetime, timedelta, timezone

from emby_runtime.streams import EmbyStreamsManager


class Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def tick(self, seconds: int):
        self.value += timedelta(seconds=seconds)


def test_refresh_server_reuses_cache_until_stale_or_expired():
    clock = Clock()
    manager = EmbyStreamsManager(now=clock)
    calls = []

    def fetch_sessions(server):
        calls.append(server["id"])
        return ([{"session_id": f"s{len(calls)}"}], None)

    server = {"id": "server-a"}

    streams, error = manager.refresh_server(server, fetch_sessions, max_age_seconds=5)
    assert error is None
    assert streams == [{"session_id": "s1", "_last_update": "2026-07-22T10:00:00+00:00"}]

    streams, error = manager.refresh_server(server, fetch_sessions, max_age_seconds=5)
    assert error is None
    assert streams[0]["session_id"] == "s1"
    assert calls == ["server-a"]

    manager.mark_stale("server-a", "websocket:Sessions")
    streams, error = manager.refresh_server(server, fetch_sessions, max_age_seconds=5)
    assert error is None
    assert streams[0]["session_id"] == "s2"
    assert calls == ["server-a", "server-a"]

    clock.tick(6)
    streams, error = manager.refresh_server(server, fetch_sessions, max_age_seconds=5)
    assert error is None
    assert streams[0]["session_id"] == "s3"
    assert calls == ["server-a", "server-a", "server-a"]


def test_refresh_server_preserves_cached_streams_after_error_without_hammering():
    clock = Clock()
    manager = EmbyStreamsManager(now=clock)
    calls = []

    def fetch_ok(server):
        calls.append("ok")
        return ([{"session_id": "good"}], None)

    def fetch_error(server):
        calls.append("error")
        return ([], "timeout")

    server = {"id": "server-a"}
    manager.refresh_server(server, fetch_ok, max_age_seconds=5)

    manager.mark_stale("server-a", "websocket:Sessions")
    streams, error = manager.refresh_server(server, fetch_error, max_age_seconds=5)
    assert error == "timeout"
    assert streams[0]["session_id"] == "good"

    streams, error = manager.refresh_server(server, fetch_error, max_age_seconds=5)
    assert error == "timeout"
    assert streams[0]["session_id"] == "good"
    assert calls == ["ok", "error"]
