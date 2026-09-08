import ast
import asyncio
import inspect
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from emby_libraries.tracker import LibraryScanTracker
from emby_probe.manager import EmbyProbeManager
from emby_runtime.transcode_guard import (
    TranscodeGuardLifecycleError,
    TranscodeGuardService,
)
from emby_runtime.transcode_guard_routes import _save_settings_and_apply_lifecycle
from core.tasks import WorkflowManager
from runtime import bootstrap
from services import workflows


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ORM_ENTITY_FACTORIES = frozenset({
    "create_user",
    "get_user_by_id",
    "get_user_by_username",
})


class _CurrentScopeVisitor(ast.NodeVisitor):
    """Visit one function scope without treating nested workers as local code."""

    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _nodes_in_current_scope(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    visitor = _CurrentScopeVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return visitor.nodes


def _call_name(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _assigned_orm_entities(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    entities: set[str] = set()
    for node in _nodes_in_current_scope(function):
        value = None
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Call)
            and _call_name(value) in _ORM_ENTITY_FACTORIES
        ):
            entities.add(target.id)
    return entities


def _thread_targets(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    targets: list[ast.AST] = []
    for node in _nodes_in_current_scope(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "submit" and node.args:
            targets.append(node.args[0])
        elif _call_name(node) == "Thread":
            targets.extend(
                keyword.value for keyword in node.keywords if keyword.arg == "target"
            )
    return targets


def _local_bindings(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    arguments = function.args
    bindings = {
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }
    if arguments.vararg:
        bindings.add(arguments.vararg.arg)
    if arguments.kwarg:
        bindings.add(arguments.kwarg.arg)
    if isinstance(function, ast.Lambda):
        body = [function.body]
    else:
        body = function.body
    module = ast.Module(body=body, type_ignores=[])
    bindings.update(
        node.id for node in ast.walk(module) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    return bindings


def _concurrent_orm_dereferences(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for owner in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        orm_entities = _assigned_orm_entities(owner)
        if not orm_entities:
            continue
        nested_workers = {
            node.name: node
            for statement in owner.body
            for node in [statement]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for target in _thread_targets(owner):
            worker = nested_workers.get(target.id) if isinstance(target, ast.Name) else target
            if not isinstance(worker, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            captured = orm_entities - _local_bindings(worker)
            for node in ast.walk(worker):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in captured:
                    violations.append(f"{filename}:{node.lineno}: {node.value.id}.{node.attr}")
    return violations


class _BlockedTranscodeGuard(TranscodeGuardService):
    def __init__(self) -> None:
        super().__init__(storage_provider=lambda: None)
        self.settings = {"enabled": True, "poll_interval_seconds": 2}
        self.first_check_entered = threading.Event()
        self.release_first_check = threading.Event()
        self.replacement_entered = threading.Event()
        self._check_count = 0

    def load_settings(self):
        return dict(self.settings)

    def save_settings(self, payload):
        self.settings.update(payload)
        return dict(self.settings)

    def check_once(self):
        self._check_count += 1
        if self._check_count == 1:
            self.first_check_entered.set()
            self.release_first_check.wait(2)
            return
        self.replacement_entered.set()
        self._stop_event.wait(2)


def _wait_until_stopped(service: TranscodeGuardService) -> None:
    deadline = time.monotonic() + 1
    while service._thread and service._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.005)


def test_transcode_guard_stop_start_reaps_old_owner_before_persisting_enabled():
    service = _BlockedTranscodeGuard()
    assert service.start() is True
    assert service.first_check_entered.wait(0.5)
    assert service.stop() is True

    with ThreadPoolExecutor(1) as executor:
        restart = executor.submit(
            _save_settings_and_apply_lifecycle,
            service,
            {"enabled": True},
        )
        assert not restart.done()
        service.release_first_check.set()
        settings, started = restart.result(timeout=1)

    assert started is True
    assert settings["enabled"] is True
    assert service.replacement_entered.wait(0.5)
    assert service.is_running() is True
    assert service.shutdown(0.5) is True


def test_transcode_guard_failed_drain_fences_next_lifespan_until_late_exit():
    service = _BlockedTranscodeGuard()
    assert service.start() is True
    assert service.first_check_entered.wait(0.5)

    assert service.shutdown(0.01) is False
    assert service.start_accepting(0.01) is False
    with pytest.raises(TranscodeGuardLifecycleError, match="arresto"):
        service.start(0.01)

    service.release_first_check.set()
    _wait_until_stopped(service)
    assert service.start_accepting(0.5) is True
    assert service.start() is True
    assert service.replacement_entered.wait(0.5)
    assert service.shutdown(0.5) is True


def test_transcode_guard_restart_timeout_compensates_persisted_enabled_state():
    service = _BlockedTranscodeGuard()
    assert service.start() is True
    assert service.first_check_entered.wait(0.5)
    assert service.stop() is True
    start_with_short_deadline = service.start
    service.start = lambda: start_with_short_deadline(0.01)  # type: ignore[method-assign]

    with pytest.raises(TranscodeGuardLifecycleError, match="ancora in arresto"):
        _save_settings_and_apply_lifecycle(service, {"enabled": True})

    assert service.settings["enabled"] is False
    assert service.is_running() is False
    service.release_first_check.set()
    _wait_until_stopped(service)


def test_bootstrap_rejects_an_undrained_transcode_guard_owner(monkeypatch):
    class Guard:
        def start_accepting(self):
            return False

        def start(self):
            raise AssertionError("start must not run before the old owner drains")

    monkeypatch.setattr(
        "emby_runtime.transcode_guard.get_transcode_guard_service",
        lambda: Guard(),
    )

    with pytest.raises(TranscodeGuardLifecycleError, match="ancora in arresto"):
        bootstrap._initialize_transcode_guard_monitor()


def test_library_scan_tracker_terminalizes_and_fences_the_old_generation():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    old_job = tracker.create_job("server-a", ["library-a"])
    tracker.update_job(old_job, status="active")

    assert tracker.begin_shutdown() == 1
    interrupted = tracker.get_job(old_job)
    assert interrupted is not None
    assert interrupted["status"] == "error"
    assert interrupted["completed_at"] is not None
    assert interrupted["library_status"]["library-a"]["status"] == "error"

    tracker.update_library_status(old_job, "library-a", "completed", 1.0)
    assert tracker.get_job(old_job) == interrupted
    with pytest.raises(RuntimeError, match="arresto"):
        tracker.create_job("server-a", ["library-a"])

    assert tracker.reopen() == 0
    new_job, conflicts = tracker.create_job_unless_active("server-a", ["library-a"])
    assert new_job is not None and new_job != old_job
    assert conflicts == []

    tracker.update_library_status(old_job, "library-a", "completed", 1.0)
    assert tracker.get_job(old_job) == interrupted
    new_snapshot = tracker.get_job(new_job)
    assert new_snapshot is not None
    assert new_snapshot["status"] == "queued"


def test_library_tracker_shutdown_fences_broadcast_queued_after_mutation():
    mutation_finished = threading.Event()
    release_dispatch = threading.Event()
    broadcasts: list[tuple] = []

    class PausedDispatchTracker(LibraryScanTracker):
        def _dispatch_current_broadcasts(self, *args, **kwargs):
            mutation_finished.set()
            assert release_dispatch.wait(1)
            return super()._dispatch_current_broadcasts(*args, **kwargs)

        def _broadcast_scan_progress(self, *args, **kwargs):
            broadcasts.append((args, kwargs))

    tracker = PausedDispatchTracker(lambda: None, lambda _message: None)
    job_id = tracker.create_job("server-a", ["library-a"])
    with ThreadPoolExecutor(1) as executor:
        update = executor.submit(
            tracker.update_library_status,
            job_id,
            "library-a",
            "active",
            0.5,
        )
        assert mutation_finished.wait(0.5)
        assert tracker.begin_shutdown() == 1
        release_dispatch.set()
        update.result(timeout=1)

    assert broadcasts == []


def test_runtime_wires_tracker_and_transcode_guard_lifecycle_boundaries():
    startup_source = inspect.getsource(bootstrap.register_runtime_event_loop)
    helper_source = inspect.getsource(bootstrap._initialize_transcode_guard_monitor)
    initialize_source = inspect.getsource(bootstrap.initialize_runtime_services)
    shutdown_source = inspect.getsource(bootstrap.shutdown_runtime_services)

    assert "_LIBRARY_SCAN_TRACKER.reopen()" in startup_source
    assert "transcode_guard.start_accepting()" in helper_source
    assert "except TranscodeGuardLifecycleError:" in initialize_source
    assert shutdown_source.index("_LIBRARY_SCAN_TRACKER.begin_shutdown()") < shutdown_source.index(
        "worker_steps ="
    )


def test_tracker_generation_is_not_exposed_in_public_job_snapshots():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    job_id = tracker.create_job("server-a", ["library-a"])

    snapshot = tracker.get_job(job_id)
    assert snapshot is not None
    assert "generation" not in snapshot
    assert all("generation" not in job for job in tracker.get_all_jobs())


@pytest.mark.anyio
async def test_tracker_second_lifespan_does_not_reuse_interrupted_job():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    old_job = tracker.create_job("server-a", ["library-a"])
    tracker.update_job(old_job, status="active")
    tracker.begin_shutdown()

    await asyncio.sleep(0)
    tracker.reopen()
    new_job, conflicts = tracker.create_job_unless_active("server-a", ["library-a"])

    assert new_job is not None and new_job != old_job
    assert conflicts == []
    old_snapshot = tracker.get_job(old_job)
    assert old_snapshot is not None
    assert old_snapshot["status"] == "error"


def test_concurrent_test_workers_do_not_dereference_captured_orm_entities():
    violations = []
    for path in (PROJECT_ROOT / "tests").rglob("*.py"):
        violations.extend(
            _concurrent_orm_dereferences(
                path.read_text(encoding="utf-8"),
                filename=str(path.relative_to(PROJECT_ROOT)),
            )
        )

    assert violations == []


def test_concurrent_orm_owner_gate_catches_closures_but_allows_scalar_handoffs():
    unsafe = """
def test_race(auth, executor):
    user = auth.create_user('name', 'password')
    def save():
        return auth.save_preferences(user.id, {})
    executor.submit(save)
    threading.Thread(target=lambda: auth.save_order(user.id, [])).start()
"""
    safe = """
def test_race(auth, executor):
    user = auth.create_user('name', 'password')
    user_id = int(user.id)
    def save():
        return auth.save_preferences(user_id, {})
    executor.submit(save)
    threading.Thread(target=lambda: auth.save_order(user_id, [])).start()
"""

    assert _concurrent_orm_dereferences(unsafe, filename="unsafe.py") == [
        "unsafe.py:5: user.id",
        "unsafe.py:7: user.id",
    ]
    assert _concurrent_orm_dereferences(safe, filename="safe.py") == []


def test_probe_targeted_stop_sets_only_flags_owned_by_the_expected_run():
    manager = EmbyProbeManager()
    x_combo = threading.Event()
    x_child = threading.Event()
    y_combo = threading.Event()
    y_child = threading.Event()
    with manager._lock:
        manager._status = {
            "server-x": {
                "combo_recent": {"run_id": "run-x", "running": True},
                "recent_discovery": {"run_id": "run-x", "running": True},
            },
            "server-y": {
                "combo_recent": {"run_id": "run-y", "running": True},
                "recent_processing": {"run_id": "run-y", "running": True},
            },
        }
        manager._stop_flags = {
            "server-x": {
                "combo_recent": x_combo,
                "recent_discovery": x_child,
            },
            "server-y": {
                "combo_recent": y_combo,
                "recent_processing": y_child,
            },
        }

    assert manager.stop_combo_workflow_all_servers(
        scope="recent",
        expected_run_id="run-x",
    ) is True
    assert x_combo.is_set() is True
    assert x_child.is_set() is True
    assert y_combo.is_set() is False
    assert y_child.is_set() is False


def test_probe_targeted_stop_before_start_cancels_that_run_reservation():
    manager = EmbyProbeManager()

    assert manager.stop_combo_workflow_all_servers(
        scope="recent",
        expected_run_id="run-x",
    ) is False
    assert manager.start_combo_workflow_all_servers(
        [{"id": "server-a", "enabled": True}],
        scope="recent",
        run_id="run-x",
    ) is False
    assert manager._workers == {}


def test_workflow_stop_delayed_by_persistence_cannot_stop_replacement_probe(monkeypatch):
    persistence_entered = threading.Event()
    release_persistence = threading.Event()

    class BlockingStorage:
        def request_active_workflow_stop(self, workflow_id):
            assert workflow_id == "workflow-x"
            persistence_entered.set()
            assert release_persistence.wait(1)
            return True

    probe_manager = EmbyProbeManager()
    replacement_flag = threading.Event()
    with probe_manager._lock:
        probe_manager._status = {
            "server-a": {
                "combo_recent": {"run_id": "run-y", "running": True},
            }
        }
        probe_manager._stop_flags = {
            "server-a": {"combo_recent": replacement_flag}
        }

    workflow_manager = WorkflowManager()
    workflow_manager._db_storage = BlockingStorage()
    workflow_manager._stop_probe_func = workflows._wf_stop_probe
    with workflow_manager._lock:
        workflow_manager._active_probe_run_id = "run-x"
        workflow_manager._status = {
            "status": "running",
            "workflow_type": "full",
            "workflow_id": "workflow-x",
            "operation_id": "operation-x",
            "current_step_index": 0,
            "steps": [{"id": "probe", "label": "Probe", "status": "running"}],
            "workflow_job_ids": [],
            "context": {},
            "error": None,
        }

    monkeypatch.setattr(workflows, "get_probe_manager", lambda: probe_manager)
    with ThreadPoolExecutor(1) as executor:
        stop_result = executor.submit(workflow_manager.stop, "operation-x")
        assert persistence_entered.wait(0.5)
        with workflow_manager._lock:
            workflow_manager._active_probe_run_id = "run-y"
            workflow_manager._status = {
                "status": "running",
                "workflow_type": "full",
                "workflow_id": "workflow-y",
                "operation_id": "operation-y",
                "current_step_index": 0,
                "steps": [{"id": "probe", "label": "Probe", "status": "running"}],
                "workflow_job_ids": [],
                "context": {},
                "error": None,
            }
        release_persistence.set()
        assert stop_result.result(timeout=1) == "stop_requested"

    assert replacement_flag.is_set() is False
