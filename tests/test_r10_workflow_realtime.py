"""Regression coverage for tenth-pass workflow and realtime findings."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.anyio
@pytest.mark.parametrize("consume_initial", [False, True])
async def test_workflow_sse_releases_lease_on_early_close(
    monkeypatch: pytest.MonkeyPatch,
    consume_initial: bool,
) -> None:
    from realtime import connection_limits, routes

    connection_limits.reset_connection_limits()
    routes.init_realtime_routes(lambda _request: SimpleNamespace(id=761))
    monkeypatch.setattr(
        routes.workflow_manager,
        "get_status",
        lambda: {"status": "running"},
    )

    response = await routes.workflow_events(SimpleNamespace())
    if consume_initial:
        assert '"status": "running"' in await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert connection_limits._COUNTS == {}


def test_probe_completion_check_rejects_invalid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import workflows

    monkeypatch.setattr(workflows, "get_probe_manager", lambda: SimpleNamespace(_global_workers={}))
    monkeypatch.setattr(workflows, "load_config", lambda: ({}, False))

    with pytest.raises(RuntimeError, match="verificare il completamento Probe"):
        workflows._wf_check_probe({})


def test_probe_completion_check_propagates_status_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import workflows

    class _Manager:
        _global_workers = {}

        def get_status(self, _server_id: str):
            raise RuntimeError("database temporarily unavailable")

    monkeypatch.setattr(workflows, "get_probe_manager", _Manager)
    monkeypatch.setattr(
        workflows,
        "load_config",
        lambda: ({"EMBY": {"SERVERS": [{"id": "emby-1", "enabled": True}]}}, True),
    )

    with pytest.raises(RuntimeError, match="verificare il completamento Probe"):
        workflows._wf_check_probe({})


def test_probe_callback_error_marks_workflow_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.tasks import WorkflowManager

    manager = WorkflowManager()
    manager.set_callbacks(
        trigger_scan_func=lambda _context: True,
        check_scan_func=lambda _context: True,
        trigger_probe_func=lambda _context: True,
        check_probe_func=lambda _context: (_ for _ in ()).throw(RuntimeError("status unavailable")),
        refresh_cache_func=lambda _context: None,
        notify_func=lambda _context: None,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    assert manager.start("smart") is True
    manager._thread.join(timeout=3)

    assert manager._thread.is_alive() is False
    assert manager.get_status()["status"] == "failed"
