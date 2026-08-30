from types import SimpleNamespace

import pytest

from emby_probe.operations import ProbeWorkerOperation, _monitor_probe_worker


class _Tracker:
    def __init__(self):
        self.updates = []
        self.finished = []
        self.failed = []
        self.skipped = []

    def update(self, operation_id, **kwargs):
        self.updates.append((operation_id, kwargs))

    def finish(self, operation_id, message, result=None):
        self.finished.append((operation_id, message, result))

    def fail(self, operation_id, message, result=None):
        self.failed.append((operation_id, message, result))

    def skip(self, operation_id, message, result=None):
        self.skipped.append((operation_id, message, result))


class _Manager:
    def __init__(self, states, running):
        self.states = states
        self.running = list(running)

    def get_status(self, server_id):
        return self.states.get(server_id, {})

    def is_worker_running(self, _worker_key, _server_ids, *, global_key=None):
        assert global_key is None
        return self.running.pop(0) if self.running else False


def test_probe_worker_monitor_finishes_after_live_worker_ends(monkeypatch):
    tracker = _Tracker()
    manager = _Manager(
        {"green": {"discovery": {"last_log": "Discovery completata"}}},
        [True, False],
    )
    monkeypatch.setattr("emby_probe.operations.time.sleep", lambda _seconds: None)

    _monitor_probe_worker(
        tracker,
        "operation-1",
        manager,
        ProbeWorkerOperation("discovery", "Media Probe: Discovery", "libraries"),
        ["green"],
    )

    assert tracker.updates
    assert tracker.finished == [
        ("operation-1", "Discovery completata", {"servers": {"green": {"last_log": "Discovery completata"}}}),
    ]
    assert not tracker.failed


def test_probe_worker_monitor_marks_user_stop_as_skipped(monkeypatch):
    tracker = _Tracker()
    manager = _Manager(
        {"green": {"discovery": {"last_log": "Discovery interrotta dall'utente"}}},
        [True, False],
    )
    monkeypatch.setattr("emby_probe.operations.time.sleep", lambda _seconds: None)

    _monitor_probe_worker(
        tracker,
        "operation-1",
        manager,
        ProbeWorkerOperation("discovery", "Media Probe: Discovery", "libraries"),
        ["green"],
    )

    assert tracker.skipped == [
        ("operation-1", "Discovery interrotta dall'utente", {"servers": {"green": {"last_log": "Discovery interrotta dall'utente"}}}),
    ]
    assert not tracker.finished


@pytest.mark.anyio
async def test_probe_start_response_contains_the_operation_snapshot(monkeypatch):
    from emby_probe import routes

    monkeypatch.setattr(
        routes,
        "_probe_discovery_start_snapshot",
        lambda body: ({"success": True, "message": "Discovery avviata", "started": [body["server_id"]]}, 200),
    )
    monkeypatch.setattr(
        routes,
        "start_probe_worker_operation",
        lambda **_kwargs: {"id": "operation-1", "status": "running"},
    )
    routes.init_emby_probe_routes(lambda _request: 1)
    request = SimpleNamespace(json=lambda: _async_value({"server_id": "green"}))

    response = await routes.probe_discovery_start(request)

    assert response.status_code == 200
    assert b'"operation":{"id":"operation-1","status":"running"}' in response.body


async def _async_value(value):
    return value
