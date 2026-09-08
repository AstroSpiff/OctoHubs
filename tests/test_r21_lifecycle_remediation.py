"""Regression coverage for R21 worker lifecycle and finalization fixes."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from core.tasks import ScanManager, WorkflowManager
from tests.workflow_test_support import attach_test_operation_tracker


def test_scan_manager_rejects_late_start_until_next_lifespan():
    manager = ScanManager()
    manager.begin_shutdown()

    assert manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: {}) is False

    manager.start_accepting()
    assert manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: {}) is True
    assert manager.wait(1) is True


def test_workflow_start_is_joinable_before_shutdown_can_observe_it():
    entered_start = threading.Event()
    release_start = threading.Event()
    real_thread = threading.Thread

    class PausedStartThread(real_thread):
        def start(self):
            entered_start.set()
            assert release_start.wait(timeout=2)
            return super().start()

    manager = WorkflowManager()
    attach_test_operation_tracker(manager)
    start_result = []
    shutdown_result = []
    shutdown_error = []

    def launch():
        start_result.append(manager.start("full"))

    def shutdown():
        try:
            shutdown_result.append(manager.shutdown(1))
        except Exception as exc:  # pragma: no cover - regression evidence
            shutdown_error.append(exc)

    with patch("core.tasks.threading.Thread", PausedStartThread):
        starter = real_thread(target=launch)
        starter.start()
        assert entered_start.wait(timeout=1)
        stopper = real_thread(target=shutdown)
        stopper.start()
        time.sleep(0.02)
        assert stopper.is_alive() is True
        release_start.set()
        starter.join(timeout=2)
        stopper.join(timeout=2)

    assert shutdown_error == []
    assert start_result == [True]
    assert shutdown_result == [True]


def test_workflow_finalization_retries_before_publishing_success():
    class Storage:
        def __init__(self):
            self.finalize_calls = 0
            self.release_calls = 0

        def finalize_workflow_execution(self, **_kwargs):
            self.finalize_calls += 1
            if self.finalize_calls == 1:
                raise RuntimeError("temporary database outage")
            return True

        def release_workflow_lease(self, _lease):
            self.release_calls += 1

    storage = Storage()
    manager = WorkflowManager()
    manager._db_storage = storage
    manager._workflow_lease = object()
    manager._status.update({"workflow_id": "wf-r21", "status": "running", "error": None})

    assert manager._finalize_workflow(
        "wf-r21",
        "completed",
        None,
        "success",
        "Completato",
    ) is True

    assert storage.finalize_calls == 2
    assert storage.release_calls == 1
    assert manager._status["status"] == "completed"
    assert manager._finalized_workflow_id == "wf-r21"


def test_workflow_finalization_reports_failure_when_commit_never_succeeds():
    class Storage:
        def __init__(self):
            self.finalize_calls = 0

        def finalize_workflow_execution(self, **_kwargs):
            self.finalize_calls += 1
            return False

        def release_workflow_lease(self, _lease):
            return None

    storage = Storage()
    manager = WorkflowManager()
    manager._db_storage = storage
    manager._workflow_lease = object()
    manager._status.update({"workflow_id": "wf-r21", "status": "running", "error": None})

    assert manager._finalize_workflow(
        "wf-r21",
        "completed",
        None,
        "success",
        "Completato",
    ) is False

    assert storage.finalize_calls == 3
    assert manager._status["status"] == "failed"
    assert manager._status["error"] == "Finalizzazione workflow non persistita"
    assert manager._finalized_workflow_id is None
