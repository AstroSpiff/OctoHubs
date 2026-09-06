"""Persistent workflow terminalization regressions."""

from __future__ import annotations

import threading
from unittest.mock import patch

from core.tasks import WorkflowManager


class _WorkflowStorage:
    def __init__(self):
        self.executions = {}
        self.execution_updates = []
        self.step_updates = []

    def create_workflow_execution(self, workflow_id, workflow_type, context):
        self.executions[workflow_id] = {
            "status": "running",
            "workflow_type": workflow_type,
            "context": context,
            "error": None,
        }

    def create_workflow_step(self, workflow_id, step_id, step_index):
        return None

    def update_workflow_step(self, workflow_id, step_id, status, progress, details):
        self.step_updates.append((workflow_id, step_id, status, progress, details))

    def update_workflow_execution(self, workflow_id, status, error=None):
        self.execution_updates.append((workflow_id, status, error))
        self.executions[workflow_id].update(status=status, error=error)


def _manager_with_storage(storage: _WorkflowStorage) -> WorkflowManager:
    manager = WorkflowManager()
    manager.set_db_storage(storage)
    manager.set_callbacks(
        trigger_scan_func=lambda _context: True,
        check_scan_func=lambda _context: True,
        trigger_probe_func=lambda _context: True,
        check_probe_func=lambda _context: True,
        refresh_cache_func=lambda _context: None,
        notify_func=lambda _context: None,
    )
    return manager


def _join_workflow(manager: WorkflowManager) -> None:
    manager._thread.join(timeout=3)
    assert manager._thread.is_alive() is False


def test_success_terminalizes_the_persisted_execution_once():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)

    with patch("time.sleep", lambda _seconds: None):
        assert manager.start("full") is True
        _join_workflow(manager)

    workflow_id = manager.get_status()["workflow_id"]
    assert manager.get_status()["status"] == "completed"
    assert storage.execution_updates == [(workflow_id, "completed", None)]
    assert storage.executions[workflow_id]["status"] == "completed"


def test_step_failure_terminalizes_the_persisted_execution_as_failed():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)
    manager._trigger_scan_func = lambda _context: False

    assert manager.start("full") is True
    _join_workflow(manager)

    workflow_id = manager.get_status()["workflow_id"]
    assert manager.get_status()["status"] == "failed"
    assert storage.execution_updates == [
        (workflow_id, "failed", "Errore durante l'esecuzione del workflow")
    ]
    assert storage.executions[workflow_id]["status"] == "failed"


def test_stop_terminalizes_scan_as_interrupted_instead_of_failed():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)
    scan_started = threading.Event()

    def trigger_scan(_context):
        scan_started.set()
        return True

    manager._trigger_scan_func = trigger_scan
    manager._check_scan_func = lambda _context: False

    assert manager.start("full") is True
    assert scan_started.wait(timeout=2)
    manager.stop()
    _join_workflow(manager)

    workflow_id = manager.get_status()["workflow_id"]
    assert manager.get_status()["status"] == "completed"
    assert manager.get_status()["error"] == "Workflow interrotto dall'utente"
    assert manager.get_status()["steps"][0]["status"] == "skipped"
    assert storage.execution_updates == [
        (workflow_id, "completed", "Workflow interrotto dall'utente")
    ]


def test_unexpected_loop_error_is_terminalized_by_finally():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)
    manager._get_steps = lambda _workflow_id=None: (_ for _ in ()).throw(RuntimeError("boom"))

    assert manager.start("full") is True
    _join_workflow(manager)

    workflow_id = manager.get_status()["workflow_id"]
    assert storage.execution_updates == [
        (workflow_id, "failed", "Errore durante l'esecuzione del workflow")
    ]


def test_thread_start_failure_terminalizes_the_created_execution():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)

    with patch("threading.Thread.start", side_effect=RuntimeError("thread unavailable")):
        assert manager.start("full") is False

    workflow_id = manager.get_status()["workflow_id"]
    expected_error = "Errore durante l'esecuzione del workflow"
    assert manager.get_status()["status"] == "failed"
    assert storage.execution_updates == [(workflow_id, "failed", expected_error)]


def test_terminalization_is_idempotent_for_the_same_workflow():
    storage = _WorkflowStorage()
    manager = _manager_with_storage(storage)

    with patch("time.sleep", lambda _seconds: None):
        assert manager.start("full") is True
        _join_workflow(manager)

    workflow_id = manager.get_status()["workflow_id"]
    assert manager._finalize_workflow(
        workflow_id,
        "failed",
        "late error",
        "error",
        "late error",
    ) is False
    assert storage.execution_updates == [(workflow_id, "completed", None)]
    assert manager.get_status()["status"] == "completed"
