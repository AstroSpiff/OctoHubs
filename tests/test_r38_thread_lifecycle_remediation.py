"""Regression and class gates for failure-safe owned thread startup."""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from core.operations import OperationTracker
from core.auto_scheduler_workers import AutoSchedulerWorkerPool
from core.tasks import AutoScheduler, ScanManager, WorkflowManager
from core.thread_lifecycle import (
    join_owned_thread,
    start_owned_thread,
    stop_and_join_after_start_failure,
)
from emby_collections import scheduler as collection_scheduler
from emby_probe.queue_leases import ProbeClaimLost, run_with_claim_renewal
from emby_runtime.transcode_guard import TranscodeGuardService
from emby_runtime.transcode_guard_routes import _save_settings_and_apply_lifecycle
from emby_runtime.websocket_manager import EmbyWebSocketConnection, EmbyWebSocketManager
from emby_latest.operations import fail_latest_refresh_operation
from realtime.session_refresh_dispatcher import SessionRefreshDispatcher
from services.background_job_registry import BackgroundJobRegistry
from services.scheduler_occurrences import SchedulerOccurrenceClaim, SchedulerOccurrenceLease
from tests.workflow_test_support import attach_test_operation_tracker


pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)


class _Storage:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_key_value(self, key: str):
        return self.values.get(key)

    def set_key_value(self, key: str, value: object) -> None:
        self.values[key] = value


def _assignment_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Attribute):
        return {target.attr}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {
            name
            for item in target.elts
            for name in _assignment_names(item)
        }
    return set()


def _constructed_thread_receivers(tree: ast.Module) -> set[str]:
    subclass_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Attribute) and base.attr == "Thread")
            or (isinstance(base, ast.Name) and base.id == "Thread")
            for base in node.bases
        )
    }
    receivers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        constructor = value.func
        is_thread = (
            isinstance(constructor, ast.Attribute)
            and constructor.attr == "Thread"
        ) or (isinstance(constructor, ast.Name) and constructor.id in subclass_names | {"Thread"})
        if not is_thread:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            receivers.update(_assignment_names(target))
    return receivers


def _owned_thread_start_receiver(
    node: ast.AST,
    constructed_receivers: set[str],
) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr != "start":
        return None
    receiver = node.func.value
    if isinstance(receiver, ast.Name):
        receiver_name = receiver.id
    elif isinstance(receiver, ast.Attribute):
        receiver_name = receiver.attr
    else:
        return None
    if (
        receiver_name not in constructed_receivers
        and "thread" not in receiver_name.lower()
        and "worker" not in receiver_name.lower()
    ):
        return None
    return receiver_name


def _thread_subclass_self_starts(tree: ast.Module, relative: Path) -> list[str]:
    violations: list[str] = []
    classes = (node for node in tree.body if isinstance(node, ast.ClassDef))
    for class_node in classes:
        base_names = {
            base.attr if isinstance(base, ast.Attribute) else base.id
            for base in class_node.bases
            if isinstance(base, (ast.Attribute, ast.Name))
        }
        if "Thread" not in base_names:
            continue
        for node in ast.walk(class_node):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "start" or not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id == "self":
                violations.append(f"{relative}:{node.lineno}:Thread subclass self")
    return violations


_EXTERNALLY_ROLLED_BACK_START_CONTEXTS = {
    "automatic scheduler",
    "Probe lease renewal",
    "scheduler occurrence renewal",
    "session refresh dispatcher",
}


def _owned_helper_calls_without_rollback(tree: ast.Module) -> list[int]:
    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = function.id if isinstance(function, ast.Name) else None
        if name not in {"start_owned_thread", "start_owned_thread_confirmed"}:
            continue
        if any(keyword.arg == "rollback_unstarted" for keyword in node.keywords):
            continue
        context = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "context"),
            None,
        )
        if (
            isinstance(context, ast.Constant)
            and context.value in _EXTERNALLY_ROLLED_BACK_START_CONTEXTS
        ):
            continue
        violations.append(node.lineno)
    return violations


def test_start_rollback_preserves_primary_and_post_native_ownership(monkeypatch):
    rollback_calls: list[str] = []
    before_native = threading.Thread(target=lambda: None)

    def fail_before_native() -> None:
        raise SystemExit("primary")

    def fail_cleanup() -> None:
        rollback_calls.append("rollback")
        raise KeyboardInterrupt("secondary")

    monkeypatch.setattr(before_native, "start", fail_before_native)
    with pytest.raises(SystemExit, match="primary"):
        start_owned_thread(before_native, rollback_unstarted=fail_cleanup)
    assert rollback_calls == ["rollback"]
    assert join_owned_thread(before_native, 0) is True

    release = threading.Event()
    started = threading.Event()
    post_native = threading.Thread(target=lambda: (started.set(), release.wait()))
    real_start = post_native.start

    def start_then_signal() -> None:
        real_start()
        assert started.wait(1)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(post_native, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        start_owned_thread(
            post_native,
            rollback_unstarted=lambda: rollback_calls.append("wrong"),
        )
    assert rollback_calls == ["rollback"]
    stop_and_join_after_start_failure(
        post_native,
        release.set,
        KeyboardInterrupt("post-native"),
        timeout_seconds=1,
    )
    assert not post_native.is_alive()


def test_worker_pool_treats_ordinary_post_native_error_as_started(monkeypatch):
    pool = AutoSchedulerWorkerPool()
    real_start = threading.Thread.start
    entered = threading.Event()

    def start_then_fail(thread: threading.Thread) -> None:
        real_start(thread)
        assert entered.wait(1)
        raise RuntimeError("post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_fail)
    assert pool.start("canary", lambda stop: (entered.set(), stop.wait())[1]) is True
    assert pool.is_running("canary") is True
    pool.stop()
    assert pool.wait(1) is True


def test_dispatcher_partial_constructor_failure_reclaims_first_worker(monkeypatch):
    real_start = threading.Thread.start
    workers: list[threading.Thread] = []

    def fail_second(worker: threading.Thread) -> None:
        workers.append(worker)
        if len(workers) == 2:
            raise RuntimeError("second worker")
        real_start(worker)

    monkeypatch.setattr(threading.Thread, "start", fail_second)
    with pytest.raises(RuntimeError, match="second worker"):
        SessionRefreshDispatcher(lambda *_args: None, max_workers=2)

    assert len(workers) == 2
    assert not workers[0].is_alive()
    assert join_owned_thread(workers[1], 0) is True

    monkeypatch.setattr(threading.Thread, "start", real_start)
    replacement = SessionRefreshDispatcher(lambda *_args: None, max_workers=2)
    assert replacement.shutdown(1) is True


def test_dispatcher_callback_baseexception_does_not_wedge_server_queue():
    first = threading.Event()
    retried = threading.Event()
    calls = 0

    def callback(_server_id, _data):
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
            raise SystemExit("callback signal")
        retried.set()

    dispatcher = SessionRefreshDispatcher(callback, max_workers=1)
    try:
        assert dispatcher.submit("server", {"attempt": 1}) is True
        assert first.wait(1)
        assert dispatcher.submit("server", {"attempt": 2}) is True
        assert retried.wait(1)
    finally:
        assert dispatcher.shutdown(1) is True


def test_operation_heartbeat_start_failure_is_terminal_and_retryable(monkeypatch):
    storage = _Storage()
    tracker = OperationTracker(storage, heartbeat_interval_seconds=60)
    real_start = threading.Thread.start

    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("no native worker")),
    )
    with pytest.raises(RuntimeError, match="no native worker"):
        tracker.start("canary", "Canary")

    operations = storage.values[tracker.key]["operations"]  # type: ignore[index]
    assert [item["status"] for item in operations.values()] == ["error"]
    assert tracker.shutdown(interrupt_active=False) is True

    monkeypatch.setattr(threading.Thread, "start", real_start)
    tracker.initialize()
    operation = tracker.start("retry", "Retry")
    assert operation["status"] == "running"
    assert tracker.shutdown(timeout_seconds=1) is True


def test_operation_post_native_start_signal_terminalizes_but_keeps_worker_owned(monkeypatch):
    storage = _Storage()
    tracker = OperationTracker(storage, heartbeat_interval_seconds=60)
    real_start = threading.Thread.start

    def start_then_signal(thread: threading.Thread) -> None:
        real_start(thread)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        tracker.start("canary", "Canary")

    assert tracker.list_operations()[0]["status"] == "error"
    assert tracker._heartbeat_operation_ids == set()
    assert tracker._heartbeat_thread is not None
    assert tracker.shutdown(timeout_seconds=1, interrupt_active=False) is True


def test_operation_heartbeat_survives_baseexception_and_retries(monkeypatch):
    tracker = OperationTracker(_Storage(), heartbeat_interval_seconds=0.01)
    retried = threading.Event()
    calls = 0

    def flaky_heartbeat():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemExit("heartbeat signal")
        retried.set()
        return 1

    monkeypatch.setattr(tracker, "_heartbeat_owned_operations", flaky_heartbeat)
    tracker.start("canary", "Canary")
    assert retried.wait(1)
    assert tracker.shutdown(timeout_seconds=1, interrupt_active=False) is True


def test_workflow_ordinary_post_native_start_failure_stops_before_finalization(monkeypatch):
    class Storage:
        lease = object()

        def __init__(self) -> None:
            self.finalized = 0
            self.released = 0

        def acquire_workflow_lease(self):
            return self.lease

        def try_start_workflow_execution(self, **_kwargs):
            return True

        def finalize_workflow_execution(self, **_kwargs):
            assert exited.is_set()
            self.finalized += 1
            return True

        def release_workflow_lease(self, lease):
            assert lease is self.lease
            self.released += 1

    entered = threading.Event()
    exited = threading.Event()
    real_start = threading.Thread.start
    manager = WorkflowManager()
    attach_test_operation_tracker(manager)
    storage = Storage()
    manager._db_storage = storage

    def blocked_worker(_context, _workflow_id, stop_event, _completion_callback):
        entered.set()
        assert stop_event.wait(1)
        exited.set()

    def start_then_fail(thread: threading.Thread) -> None:
        real_start(thread)
        assert entered.wait(1)
        raise RuntimeError("post-native")

    monkeypatch.setattr(manager, "_run_workflow_and_notify", blocked_worker)
    monkeypatch.setattr(threading.Thread, "start", start_then_fail)
    assert manager.start("full") is False
    assert exited.is_set()
    assert manager._thread is not None and not manager._thread.is_alive()
    assert manager._status["status"] == "failed"
    assert storage.finalized == 1
    assert storage.released == 1

    monkeypatch.setattr(threading.Thread, "start", real_start)
    manager._db_storage = None
    assert manager.start("full") is True
    assert manager.wait(2) is True


def test_service_and_websocket_pre_native_failures_leave_no_dead_owner(monkeypatch):
    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError("no native worker")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    service = TranscodeGuardService(storage_provider=lambda: None)
    with pytest.raises(RuntimeError, match="no native worker"):
        service.start()
    assert service.is_running() is False
    assert service.shutdown(0) is True

    manager = EmbyWebSocketManager()
    with pytest.raises(RuntimeError, match="no native worker"):
        manager.add_server("server", "http://example.invalid", "secret")
    assert manager.connections == {}
    assert manager.stop_all(0) is True


def test_background_registry_baseexception_rolls_back_and_reopens(monkeypatch):
    registry = BackgroundJobRegistry()
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(KeyboardInterrupt("signal")),
    )
    with pytest.raises(KeyboardInterrupt, match="signal"):
        registry.start("job", lambda: {"id": "one"}, lambda _stop: None)
    assert registry._jobs == {}
    assert registry.shutdown(0) is True
    registry.initialize()


def test_tracked_background_job_terminalizes_baseexception_start(monkeypatch):
    import app_state
    from services.background_job_registry import background_job_registry
    from services.background_jobs import start_tracked_background_job

    storage = _Storage()
    tracker = OperationTracker(storage, heartbeat_interval_seconds=0)
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(KeyboardInterrupt("signal")),
    )
    background_job_registry.initialize()
    try:
        with pytest.raises(KeyboardInterrupt, match="signal"):
            start_tracked_background_job(
                kind="canary",
                title="Canary",
                work=lambda _context: {},
            )
        assert tracker.list_operations()[0]["status"] == "error"
        assert background_job_registry.has_active_jobs() is False
    finally:
        assert background_job_registry.shutdown(0) is True
        background_job_registry.initialize()


def test_jellyseerr_already_cancelled_worker_always_clears_published_state(monkeypatch):
    import app_state
    from services import research_request_actions
    from services.background_job_registry import background_job_registry

    class Tracker:
        def start(self, *_args, **_kwargs):
            return {"id": "refresh-operation"}

        def fail(self, *_args, **_kwargs):
            raise KeyboardInterrupt("tracker unavailable")

    state = {"running": False}

    def run_already_cancelled(_key, operation_factory, target):
        operation = operation_factory()
        stop_event = threading.Event()
        stop_event.set()
        target(stop_event)
        return operation, True

    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: Tracker())
    monkeypatch.setattr(app_state, "_JELLYSEERR_REFRESH_STATE", state)
    monkeypatch.setattr(background_job_registry, "start", run_already_cancelled)

    payload, status = research_request_actions.start_background_refresh()
    assert status == 202
    assert payload["operation_id"] == "refresh-operation"
    assert state["running"] is False
    assert "operation_id" not in state


def test_background_worker_terminalizes_when_diagnostics_raise(monkeypatch):
    import app_state
    import core.thread_lifecycle as lifecycle
    from services.background_job_registry import background_job_registry
    from services.background_jobs import start_tracked_background_job

    storage = _Storage()
    tracker = OperationTracker(storage, heartbeat_interval_seconds=0)
    failed = threading.Event()
    real_fail = tracker.fail

    def record_failure(*args, **kwargs):
        result = real_fail(*args, **kwargs)
        failed.set()
        return result

    monkeypatch.setattr(tracker, "fail", record_failure)
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(
        lifecycle,
        "format_exception_for_log",
        lambda _error: (_ for _ in ()).throw(SystemExit("diagnostic")),
    )
    background_job_registry.initialize()
    try:
        start_tracked_background_job(
            kind="canary",
            title="Canary",
            work=lambda _context: (_ for _ in ()).throw(KeyboardInterrupt("primary")),
        )
        assert failed.wait(1)
        assert tracker.list_operations()[0]["status"] == "error"
    finally:
        assert background_job_registry.shutdown(1) is True
        background_job_registry.initialize()


def test_latest_pre_native_signal_releases_worker_and_request(monkeypatch):
    import emby_latest.api_handlers as latest

    latest.start_accepting_latest_refresh()
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(KeyboardInterrupt("signal")),
    )
    latest._latest_refresh_request_reserved = True
    latest._latest_refresh_thread = None
    latest._latest_refresh_stop_event = None
    with pytest.raises(KeyboardInterrupt, match="signal"):
        latest._start_latest_refresh_worker(lambda _stop: None)
    assert latest._latest_refresh_request_reserved is False
    assert latest._latest_refresh_thread is None
    assert latest.shutdown_latest_refresh(0) is True


def test_latest_worker_terminalizes_when_diagnostics_raise(monkeypatch):
    import app_state
    import core.thread_lifecycle as lifecycle
    import emby_latest
    import emby_latest.api_handlers as latest

    latest.start_accepting_latest_refresh()

    class Manager:
        progress_tracker = None

        def is_refreshing(self):
            return False

        def refresh_incremental(self, *_args, **_kwargs):
            raise KeyboardInterrupt("primary")

    storage = _Storage()
    tracker = OperationTracker(storage, heartbeat_interval_seconds=0)
    failed = threading.Event()
    real_fail = tracker.fail

    def record_failure(*args, **kwargs):
        result = real_fail(*args, **kwargs)
        failed.set()
        return result

    monkeypatch.setattr(tracker, "fail", record_failure)
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(emby_latest, "get_manager", lambda: Manager())
    monkeypatch.setattr(
        lifecycle,
        "format_exception_for_log",
        lambda _error: (_ for _ in ()).throw(SystemExit("diagnostic")),
    )
    latest._latest_refresh_request_reserved = False
    latest._latest_refresh_thread = None
    latest._latest_refresh_stop_event = None
    payload, status = latest.build_latest_refresh_payload(10, 5, False)
    assert status == 202
    assert payload["success"] is True
    assert failed.wait(1)
    assert latest.shutdown_latest_refresh(1) is True
    assert tracker.list_operations()[0]["status"] == "error"


def test_latest_failure_does_not_stringify_untrusted_error_before_terminalizing():
    failed: list[str] = []

    class HostileError:
        def __str__(self) -> str:
            raise KeyboardInterrupt("hostile diagnostic")

    class Tracker:
        def fail(self, operation_id, _message):
            failed.append(operation_id)

    fail_latest_refresh_operation(Tracker(), "operation", HostileError())
    assert failed == ["operation"]


def test_probe_renewal_post_native_signal_is_stopped_and_joined(monkeypatch):
    real_start = threading.Thread.start
    workers: list[threading.Thread] = []

    def start_then_signal(worker: threading.Thread) -> None:
        workers.append(worker)
        real_start(worker)
        raise KeyboardInterrupt("signal")

    class Database:
        def renew_probe_queue_claim(self, *_identity) -> bool:
            return True

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="signal"):
        run_with_claim_renewal(
            Database(),
            {"id": 1, "claim_token": "token"},
            lambda: pytest.fail("callback must not run"),
            interval_seconds=60,
        )
    assert len(workers) == 1
    assert not workers[0].is_alive()


def test_probe_renewal_baseexception_fences_callback():
    lost = threading.Event()

    class Database:
        def renew_probe_queue_claim(self, *_identity):
            raise SystemExit("renew signal")

    with pytest.raises(ProbeClaimLost):
        run_with_claim_renewal(
            Database(),
            {"id": 1, "claim_token": "token"},
            lambda: lost.wait(1),
            interval_seconds=0.01,
            on_claim_lost=lost.set,
        )
    assert lost.is_set()


def test_scheduler_occurrence_renewal_baseexception_invokes_loss_fence():
    lost = threading.Event()

    class Coordinator:
        def renew(self, _claim):
            raise KeyboardInterrupt("renew signal")

    lease = SchedulerOccurrenceLease(
        Coordinator(),  # type: ignore[arg-type]
        SchedulerOccurrenceClaim("scan", "token", "owner", "scheduled"),
        on_lost=lost.set,
        interval_seconds=0.01,
    )
    lease.start()
    assert lost.wait(1)
    assert lease.stop_renewing(1) is True


def test_collection_refresher_factory_publishes_before_ambiguous_start(monkeypatch):
    real_start = threading.Thread.start
    collection_scheduler._REFRESHER = None

    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda _thread: (_ for _ in ()).throw(RuntimeError("pre-native")),
    )
    with pytest.raises(RuntimeError, match="pre-native"):
        collection_scheduler.start_collection_auto_refresher()
    assert collection_scheduler._REFRESHER is None

    def start_then_signal(thread: threading.Thread) -> None:
        real_start(thread)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        collection_scheduler.start_collection_auto_refresher()
    assert collection_scheduler._REFRESHER is not None
    assert collection_scheduler.shutdown_collection_auto_refresher(1) is True
    assert collection_scheduler._REFRESHER is None


def test_transcode_settings_follow_runtime_when_start_fails():
    class Service:
        def __init__(self) -> None:
            self.settings = {"enabled": False, "rules": []}

        def save_settings(self, payload):
            self.settings.update(payload)
            return dict(self.settings)

        def start(self):
            raise RuntimeError("start failed")

        def stop(self):
            return False

        def is_running(self):
            return False

    service = Service()
    with pytest.raises(RuntimeError, match="start failed"):
        _save_settings_and_apply_lifecycle(service, {"enabled": True})
    assert service.settings["enabled"] is False


def test_all_direct_thread_starts_use_the_canonical_primitive():
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    ignored_parts = {"tests", "venv", ".venv", "node_modules"}

    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if any(part in ignored_parts for part in relative.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        constructed_receivers = _constructed_thread_receivers(tree)
        violations.extend(_thread_subclass_self_starts(tree, relative))
        if relative.as_posix() != "core/thread_lifecycle.py":
            violations.extend(
                f"{relative}:{line}:missing rollback_unstarted"
                for line in _owned_helper_calls_without_rollback(tree)
            )
        for node in ast.walk(tree):
            receiver_name = _owned_thread_start_receiver(node, constructed_receivers)
            if receiver_name is None:
                continue
            if receiver_name == "_worker_pool" and relative.as_posix() == "core/tasks.py":
                continue
            if relative.as_posix() == "core/thread_lifecycle.py":
                continue
            violations.append(f"{relative}:{node.lineno}:{receiver_name}")

    assert violations == []


def test_thread_start_gate_detects_neutral_receiver_names_and_subclasses():
    tree = ast.parse(
        "import threading\n"
        "class Refresher(threading.Thread):\n"
        "    pass\n"
        "runner = threading.Thread()\n"
        "runner.start()\n"
        "refresher = Refresher()\n"
        "refresher.start()\n"
    )
    receivers = _constructed_thread_receivers(tree)
    detected = {
        receiver
        for node in ast.walk(tree)
        if (receiver := _owned_thread_start_receiver(node, receivers)) is not None
    }
    assert detected == {"runner", "refresher"}

    published_without_rollback = ast.parse(
        "import threading\n"
        "from core.thread_lifecycle import start_owned_thread\n"
        "class Owner:\n"
        "    def start(self):\n"
        "        self._thread = threading.Thread()\n"
        "        start_owned_thread(self._thread)\n"
    )
    assert _owned_helper_calls_without_rollback(published_without_rollback) == [6]


def test_scan_baseexception_reports_failure_and_releases_running_state():
    manager = ScanManager()
    outcomes: list[bool] = []
    manager._process_requests_func = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        SystemExit("scan signal")
    )
    with pytest.raises(SystemExit, match="scan signal"):
        manager._run_scan({}, completion_callback=outcomes.append)
    assert outcomes == [False]
    assert manager.is_running() is False
    assert manager.get_status()["message"] == "Ricerca non riuscita"


def test_scheduler_supervisor_survives_baseexception_cycle():
    scheduler = AutoScheduler.__new__(AutoScheduler)
    scheduler._stop = threading.Event()
    scheduler._wake = threading.Event()
    calls: list[int] = []

    def evaluate():
        calls.append(1)
        if len(calls) == 1:
            raise SystemExit("occurrence signal")
        scheduler._stop.set()
        return 0

    scheduler._evaluate_tasks = evaluate
    scheduler._worker()
    assert len(calls) == 2


def test_workflow_completion_callback_runs_after_baseexception():
    manager = WorkflowManager.__new__(WorkflowManager)
    manager._lock = threading.RLock()
    manager._status = {"workflow_id": "workflow", "status": "running", "error": None}
    manager._run_workflow = lambda *_args: (_ for _ in ()).throw(
        KeyboardInterrupt("workflow signal")
    )
    manager._is_current_workflow_locked = lambda workflow_id: workflow_id == "workflow"
    outcomes: list[bool] = []
    with pytest.raises(KeyboardInterrupt, match="workflow signal"):
        manager._run_workflow_and_notify(
            {}, "workflow", threading.Event(), outcomes.append
        )
    assert outcomes == [False]


def test_workflow_late_heartbeat_start_signal_has_generation_fenced_caretaker(
    monkeypatch,
):
    import core.tasks as tasks_module

    entered = threading.Event()
    release = threading.Event()

    class Storage:
        lease = object()

        def __init__(self):
            self.finalized = threading.Event()
            self.release_done = threading.Event()
            self.release_calls = 0

        def acquire_workflow_lease(self):
            return self.lease

        def try_start_workflow_execution(self, **_kwargs):
            return True

        def heartbeat_workflow_execution(self, *_args):
            entered.set()
            release.wait(1)
            return True

        def finalize_workflow_execution(self, **_kwargs):
            self.finalized.set()
            return True

        def release_workflow_lease(self, lease):
            assert lease is self.lease
            self.release_calls += 1
            self.release_done.set()

    manager = WorkflowManager()
    attach_test_operation_tracker(manager)
    storage = Storage()
    manager._db_storage = storage
    monkeypatch.setattr(tasks_module, "_WORKFLOW_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    real_cleanup = tasks_module.stop_and_join_after_start_failure

    def bounded_cleanup(thread, stop, primary_error, **kwargs):
        kwargs["timeout_seconds"] = 0.01
        return real_cleanup(thread, stop, primary_error, **kwargs)

    monkeypatch.setattr(
        tasks_module, "stop_and_join_after_start_failure", bounded_cleanup
    )
    real_start = threading.Thread.start

    def start_then_signal(thread):
        real_start(thread)
        assert entered.wait(1)
        raise KeyboardInterrupt("heartbeat post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="heartbeat post-native"):
        manager.start("full")
    assert manager._workflow_lease is storage.lease
    assert manager._workflow_heartbeat_thread is not None
    release.set()
    assert storage.finalized.wait(1)
    assert storage.release_done.wait(1)
    assert storage.release_calls == 1
    deadline = time.monotonic() + 1
    while manager.get_status()["status"] != "idle" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.get_status()["status"] == "idle"
    assert manager._workflow_lease is None

    monkeypatch.setattr(threading.Thread, "start", real_start)
    manager._db_storage = None
    assert manager.start("full") is True
    assert manager.wait(2) is True


def test_workflow_caller_does_not_release_lease_already_cleaned_by_caretaker(
    monkeypatch,
):
    class Storage:
        lease = object()

        def __init__(self):
            self.release_calls = 0

        def acquire_workflow_lease(self):
            return self.lease

        def try_start_workflow_execution(self, **_kwargs):
            return True

        def release_workflow_lease(self, lease):
            assert lease is self.lease
            self.release_calls += 1

    storage = Storage()
    manager = WorkflowManager()
    manager._db_storage = storage

    def caretaker_finishes_first(_workflow_id):
        storage.release_workflow_lease(storage.lease)
        manager._workflow_lease = None
        raise RuntimeError("late heartbeat cleanup")

    monkeypatch.setattr(
        manager,
        "_start_workflow_heartbeat_locked",
        caretaker_finishes_first,
    )
    assert manager.start("full") is False
    assert storage.release_calls == 1


def test_long_lived_workers_retry_after_baseexception(monkeypatch):
    guard = TranscodeGuardService(storage_provider=lambda: None)
    guard_calls: list[int] = []

    def load_guard_settings():
        guard_calls.append(1)
        if len(guard_calls) == 1:
            raise SystemExit("guard signal")
        guard._stop_event.set()
        return {"enabled": False}

    monkeypatch.setattr(guard, "load_settings", load_guard_settings)
    monkeypatch.setattr(guard, "_wait_for_next_cycle", lambda _delay: None)
    guard._run_loop()
    assert len(guard_calls) == 2

    refresher = collection_scheduler.CollectionAutoRefresher()
    refresh_calls: list[int] = []

    def load_collection_settings():
        refresh_calls.append(1)
        if len(refresh_calls) == 1:
            raise KeyboardInterrupt("collection signal")
        refresher._stop_event.set()
        return {"AUTO_REFRESH_ENABLED": False}

    monkeypatch.setattr(refresher, "_get_collection_settings", load_collection_settings)
    refresher.run()
    assert len(refresh_calls) == 2

    connection = EmbyWebSocketConnection.__new__(EmbyWebSocketConnection)
    connection.server_id = "server"
    connection.should_reconnect = True
    connection.state = connection.STATE_DISCONNECTED
    connection._connect = lambda: (_ for _ in ()).throw(SystemExit("ws signal"))
    connection._handle_reconnect = lambda: setattr(
        connection, "should_reconnect", False
    )
    connection._run()
    assert connection.should_reconnect is False


def test_background_job_post_native_signal_retains_ownership_until_completion(monkeypatch):
    import app_state
    from services.background_job_registry import background_job_registry
    from services.background_jobs import start_tracked_background_job

    tracker = OperationTracker(_Storage(), heartbeat_interval_seconds=0)
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    background_job_registry.initialize()
    entered = threading.Event()
    release = threading.Event()
    real_start = threading.Thread.start

    def start_then_signal(worker):
        real_start(worker)
        assert entered.wait(1)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        start_tracked_background_job(
            kind="post-native-canary",
            title="Canary",
            work=lambda _context: (entered.set(), release.wait(1), {"success": True})[2],
        )
    assert tracker.list_operations()[0]["status"] == "running"
    assert background_job_registry.has_active_jobs() is True
    release.set()
    deadline = time.monotonic() + 1
    while background_job_registry.has_active_jobs() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert background_job_registry.shutdown(1) is True
    assert tracker.list_operations()[0]["status"] == "success"
    background_job_registry.initialize()


def test_jellyseerr_post_native_signal_retains_state_until_worker_finishes(monkeypatch):
    import app_state
    from services import research_request_actions
    from services.background_job_registry import background_job_registry

    tracker = OperationTracker(_Storage(), heartbeat_interval_seconds=0)
    state = {"running": False}
    entered = threading.Event()
    release = threading.Event()
    real_start = threading.Thread.start

    def refresh_requests(**_kwargs):
        entered.set()
        release.wait(1)
        return {"success": True, "message": "ok"}, 200

    def start_then_signal(worker):
        real_start(worker)
        assert entered.wait(1)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(app_state, "_JELLYSEERR_REFRESH_STATE", state)
    monkeypatch.setattr(research_request_actions, "refresh_requests", refresh_requests)
    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    background_job_registry.initialize()
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        research_request_actions.start_background_refresh()
    assert state["running"] is True
    assert tracker.list_operations()[0]["status"] == "running"
    release.set()
    deadline = time.monotonic() + 1
    while background_job_registry.has_active_jobs() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert background_job_registry.shutdown(1) is True
    assert state["running"] is False
    assert "operation_id" not in state
    assert tracker.list_operations()[0]["status"] == "success"
    background_job_registry.initialize()


def test_probe_monitor_post_native_signal_retains_operation_and_retries_projection(
    monkeypatch,
):
    import app_state
    import emby_probe
    from emby_probe.operation_monitor_registry import ProbeOperationMonitorRegistry
    from emby_probe.operations import ProbeWorkerOperation, start_probe_worker_operation

    tracker = OperationTracker(_Storage(), heartbeat_interval_seconds=0)
    registry = ProbeOperationMonitorRegistry()
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    active = True
    real_update = tracker.update
    real_finish = tracker.finish
    update_calls = 0

    def update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            entered.set()
            release.wait(1)
            raise SystemExit("projection signal")
        return real_update(*args, **kwargs)

    def finish(*args, **kwargs):
        result = real_finish(*args, **kwargs)
        completed.set()
        return result

    class Manager:
        def start_operation_monitor(self, callback, *, owner_token=None):
            registry.start(callback, owner_token=owner_token)

        def owns_operation_monitor(self, owner_token):
            return registry.owns(owner_token)

        def is_worker_running(self, *_args, **_kwargs):
            nonlocal active
            if update_calls > 1:
                active = False
            return active

        def get_status(self, _server_id):
            return {"discovery": {"last_log": "Worker completato"}}

    manager = Manager()
    monkeypatch.setattr(tracker, "update", update)
    monkeypatch.setattr(tracker, "finish", finish)
    monkeypatch.setattr(app_state, "get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(emby_probe, "get_probe_manager", lambda: manager)
    real_start = threading.Thread.start

    def start_then_signal(worker):
        real_start(worker)
        assert entered.wait(1)
        raise KeyboardInterrupt("post-native")

    monkeypatch.setattr(threading.Thread, "start", start_then_signal)
    with pytest.raises(KeyboardInterrupt, match="post-native"):
        start_probe_worker_operation(
            worker=ProbeWorkerOperation("discovery", "Discovery", "libraries"),
            server_ids=["server"],
        )
    assert tracker.list_operations()[0]["status"] == "running"
    release.set()
    assert completed.wait(3)
    assert tracker.list_operations()[0]["status"] == "success"
    assert registry.shutdown(1) is True


def test_probe_library_workers_publish_failure_before_propagating_baseexception():
    from emby_probe.library_discovery import LibraryDiscoveryWorker
    from emby_probe.library_processing import LibraryProcessingWorker

    class Manager:
        def __init__(self):
            self._lock = threading.RLock()
            self._status = {
                "server": {
                    "discovery": {"running": True},
                    "processing": {"running": True},
                }
            }

        def _update_status(self, server_id, key, **changes):
            self._status[server_id][key].update(changes)

    manager = Manager()
    discovery = LibraryDiscoveryWorker.__new__(LibraryDiscoveryWorker)
    discovery.manager = manager
    discovery.server_id = "server"
    discovery.server = {"id": "server"}
    discovery.stop_flag = threading.Event()
    discovery._run = lambda: (_ for _ in ()).throw(SystemExit("discovery"))
    with pytest.raises(SystemExit, match="discovery"):
        discovery.run()
    assert manager._status["server"]["discovery"]["running"] is False
    assert "Errore critico" in manager._status["server"]["discovery"]["last_log"]

    processing = LibraryProcessingWorker.__new__(LibraryProcessingWorker)
    processing.manager = manager
    processing.server_id = "server"
    processing.server = {"id": "server"}
    processing.status_key = "processing"
    processing.scope = "libraries"
    processing.stop_flag = threading.Event()
    processing._run = lambda: (_ for _ in ()).throw(
        KeyboardInterrupt("processing")
    )
    with pytest.raises(KeyboardInterrupt, match="processing"):
        processing.run()
    assert manager._status["server"]["processing"]["running"] is False
    assert "Errore critico" in manager._status["server"]["processing"]["last_log"]
