"""R43 regressors for full-ASGI stream ownership and atomic workflow start."""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from core.tasks import WorkflowManager
from core.operation_identity import (
    MAX_PUBLIC_OPERATION_ID_LENGTH,
    PUBLIC_OPERATION_ID_PATTERN,
    is_valid_public_operation_id,
)
from web.owned_streaming_response import OwnedStreamingResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASGI_SCOPE = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.4"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/api/r43-stream-canary",
    "raw_path": b"/api/r43-stream-canary",
    "query_string": b"",
    "headers": [],
    "client": ("127.0.0.1", 12345),
    "server": ("127.0.0.1", 5050),
}


class _CountingLease:
    def __init__(self) -> None:
        self.release_calls = 0

    def release(self) -> None:
        self.release_calls += 1


async def _receive() -> dict[str, object]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _realtime_response(monkeypatch, endpoint: str):
    from realtime import routes
    from realtime.subscribers import sse_subscribers

    lease = _CountingLease()
    sse_subscribers.close_all()
    routes.init_realtime_routes(lambda _request: SimpleNamespace(id=4301))
    monkeypatch.setattr(routes, "acquire_connection", lambda *_args: lease)

    revalidations = 0

    async def revalidate(*_args):
        nonlocal revalidations
        revalidations += 1
        return endpoint == "status" and revalidations == 1

    real_sleep = asyncio.sleep

    async def immediate_sleep(_seconds):
        await real_sleep(0)

    async def status_snapshot(_builder):
        return {"status": "idle"}

    monkeypatch.setattr(routes, "_revalidate_subject", revalidate)
    monkeypatch.setattr(routes, "shared_status_snapshot", status_snapshot)
    monkeypatch.setattr(routes.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(routes.workflow_manager, "get_status", lambda: {"status": "idle"})

    request = SimpleNamespace()
    builders = {
        "events": routes.emby_events_stream_api,
        "status": routes.emby_status_stream_api,
        "workflow": routes.workflow_events,
    }
    response = await builders[endpoint](cast(Any, request))
    assert isinstance(response, OwnedStreamingResponse)
    return response, lease, sse_subscribers


def _stream_send_for_outcome(outcome, lease, body_send_started, never, releases):
    async def send(message):
        if outcome == "response-start" and message["type"] == "http.response.start":
            raise RuntimeError("R43 response-start failure")
        if message["type"] != "http.response.body":
            return
        if not message.get("more_body"):
            releases.append(lease.release_calls)
        if outcome == "first-body":
            raise RuntimeError("R43 first-body failure")
        if outcome == "cancel" and message.get("more_body"):
            body_send_started.set()
            await never.wait()

    return send


@pytest.mark.anyio
@pytest.mark.parametrize("endpoint", ["events", "status", "workflow"])
@pytest.mark.parametrize("outcome", ["response-start", "first-body", "cancel", "normal"])
async def test_every_sse_endpoint_releases_its_lease_for_every_asgi_exit(
    monkeypatch,
    endpoint,
    outcome,
):
    response, lease, subscribers = await _realtime_response(monkeypatch, endpoint)
    body_send_started = asyncio.Event()
    never = asyncio.Event()
    releases_seen_at_terminal_body = []
    send = _stream_send_for_outcome(
        outcome,
        lease,
        body_send_started,
        never,
        releases_seen_at_terminal_body,
    )

    if outcome in {"response-start", "first-body"}:
        with pytest.raises(RuntimeError, match="R43"):
            await response(ASGI_SCOPE, _receive, send)
    elif outcome == "cancel":
        task = asyncio.create_task(response(ASGI_SCOPE, _receive, send))
        await asyncio.wait_for(body_send_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await asyncio.wait_for(response(ASGI_SCOPE, _receive, send), timeout=1)

    assert lease.release_calls == 1
    if outcome == "normal":
        assert releases_seen_at_terminal_body == [0]
    if endpoint == "events":
        assert subscribers._subscribers == []


def test_realtime_sse_routes_use_only_the_full_asgi_owner_factory():
    source = (PROJECT_ROOT / "realtime" / "routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stream_factories = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "lease_owned_streaming_response"
    ]

    assert len(stream_factories) == 3
    assert "StreamingResponse" not in source
    assert "LeaseBoundAsyncIterator" not in source


class _WorkflowStorage:
    def __init__(self) -> None:
        self.lease = object()
        self.finalize_calls = 0
        self.release_calls = 0
        self.release_attempts = []

    def acquire_workflow_lease(self):
        return self.lease

    def try_start_workflow_execution(self, **_kwargs):
        return True

    def finalize_workflow_execution(self, **_kwargs):
        self.finalize_calls += 1
        return True

    def release_workflow_lease(self, lease):
        self.release_attempts.append(lease)
        assert lease is self.lease
        self.release_calls += 1


class _WorkflowTracker:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def start(self, *_args, **_kwargs):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    "tracker_outcome",
    [
        RuntimeError("tracker unavailable"),
        None,
        {},
        {"id": ""},
        {"id": "x" * 129},
        {"id": "operation\nforged"},
    ],
    ids=["raises", "none", "missing-id", "empty-id", "oversized-id", "control-id"],
)
def test_workflow_tracker_failure_compensates_before_worker_start(
    monkeypatch,
    tracker_outcome,
):
    manager = WorkflowManager()
    storage = _WorkflowStorage()
    manager.set_db_storage(storage)
    manager.set_operation_tracker(_WorkflowTracker(tracker_outcome))
    monkeypatch.setattr(
        manager,
        "_start_workflow_thread_locked",
        lambda *_args: pytest.fail(
            "worker must not start before a valid public operation ID exists"
        ),
    )

    assert manager.start("full") is False
    assert storage.finalize_calls == 1
    assert storage.release_calls == 1
    assert storage.release_attempts == [storage.lease]
    assert manager.get_status()["status"] == "idle"
    assert manager.get_status()["operation_id"] is None
    assert manager._thread is None
    assert manager._workflow_lease is None
    assert manager._workflow_heartbeat_stop is None
    assert manager._workflow_heartbeat_thread is None


def test_every_workflow_manager_fails_closed_without_tracker(monkeypatch):
    manager = WorkflowManager()
    storage = _WorkflowStorage()
    manager.set_db_storage(storage)
    monkeypatch.setattr(
        manager,
        "_start_workflow_thread_locked",
        lambda *_args: pytest.fail(
            "worker must not start without the configured tracker"
        ),
    )

    assert manager.start("full") is False
    assert storage.finalize_calls == 1
    assert storage.release_calls == 1
    assert manager.get_status()["status"] == "idle"


def test_never_configured_workflow_manager_cannot_start_an_untracked_worker(
    monkeypatch,
):
    manager = WorkflowManager()
    monkeypatch.setattr(
        manager,
        "_start_workflow_thread_locked",
        lambda *_args: pytest.fail("an untracked worker must never be created"),
    )

    assert manager.start("full") is False
    assert manager.get_status()["status"] == "idle"
    assert manager.get_status()["operation_id"] is None
    assert manager._thread is None


def test_workflow_valid_tracker_id_exists_before_worker_and_binds_stop_target(monkeypatch):
    manager = WorkflowManager()
    manager.set_operation_tracker(_WorkflowTracker({"id": "operation-r43"}))
    captured = []

    def capture_thread_start(*_args):
        captured.append(manager.get_status()["operation_id"])
        return None

    monkeypatch.setattr(manager, "_start_workflow_thread_locked", capture_thread_start)

    assert manager.start("full") is True
    assert captured == ["operation-r43"]
    assert manager.stop("operation-stale") == "target_changed"
    assert manager.get_status()["status"] == "running"
    assert manager.stop("operation-r43") == "stop_requested"
    assert manager.get_status()["status"] == "stopping"


def test_runtime_bootstrap_explicitly_configures_workflow_tracking():
    source = (PROJECT_ROOT / "runtime" / "bootstrap.py").read_text(encoding="utf-8")

    assert "workflow_manager.set_operation_tracker(initialize_operation_tracker())" in source
    assert "workflow_manager.set_operation_tracker(None)" in source
    tracking_source = inspect.getsource(WorkflowManager._start_operation_tracking_locked)
    assert "if not self._operation_tracker:" in tracking_source
    assert 'raise RuntimeError("Operation tracker workflow non disponibile")' in tracking_source
    assert "return None" not in tracking_source


def test_workflow_stop_contract_uses_the_canonical_operation_identity_policy():
    from services.workflow_api_models import WorkflowStopRequest

    schema = WorkflowStopRequest.model_json_schema()["properties"]["operation_id"]
    assert schema["maxLength"] == MAX_PUBLIC_OPERATION_ID_LENGTH
    assert schema["pattern"] == PUBLIC_OPERATION_ID_PATTERN
    assert is_valid_public_operation_id("operation-r43") is True
    assert is_valid_public_operation_id("x" * (MAX_PUBLIC_OPERATION_ID_LENGTH + 1)) is False
    assert is_valid_public_operation_id("operation\nforged") is False
