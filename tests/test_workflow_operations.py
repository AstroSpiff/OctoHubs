"""Workflow operations center integration."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from core.tasks import WorkflowManager


class _OperationTracker:
    def __init__(self):
        self.started = []
        self.updated = []
        self.finished = []
        self.failed = []
        self.interrupted = []

    def start(self, kind, title, summary="", details=None, total=None):
        operation = {
            "id": "operation-1",
            "kind": kind,
            "title": title,
            "summary": summary,
            "details": details or {},
            "total": total,
        }
        self.started.append(operation)
        return operation

    def update(self, operation_id, **kwargs):
        self.updated.append({"operation_id": operation_id, **kwargs})
        return {"id": operation_id, **kwargs}

    def finish(self, operation_id, message="Completato", result=None):
        self.finished.append({"operation_id": operation_id, "message": message, "result": result or {}})
        return {"id": operation_id, "status": "success"}

    def fail(self, operation_id, message, result=None):
        self.failed.append({"operation_id": operation_id, "message": message, "result": result or {}})
        return {"id": operation_id, "status": "error"}

    def interrupt(self, operation_id, message, result=None):
        self.interrupted.append({"operation_id": operation_id, "message": message, "result": result or {}})
        return {"id": operation_id, "status": "interrupted"}


class WorkflowOperationTests(unittest.TestCase):
    def test_workflow_creates_and_updates_global_operation(self):
        tracker = _OperationTracker()
        manager = WorkflowManager()
        manager.set_operation_tracker(tracker)
        manager.set_callbacks(
            trigger_scan_func=lambda _context: True,
            check_scan_func=lambda _context: True,
            trigger_probe_func=lambda _context: True,
            check_probe_func=lambda _context: True,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: None,
        )

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("smart", context={"scope": "test"}))
            manager._thread.join(timeout=3)

        self.assertFalse(manager._thread.is_alive())
        self.assertEqual(tracker.started[0]["kind"], "workflow")
        self.assertEqual(tracker.started[0]["title"], "Workflow aggiornamento")
        self.assertEqual(tracker.started[0]["summary"], "smart")
        self.assertEqual(tracker.started[0]["total"], 4)
        self.assertIn("workflow_steps", tracker.started[0]["details"])
        self.assertTrue(
            any((update.get("details") or {}).get("current_step_id") == "scan" for update in tracker.updated)
        )
        self.assertTrue(
            any((update.get("details") or {}).get("workflow_steps") for update in tracker.updated)
        )
        self.assertEqual(tracker.finished[-1]["operation_id"], "operation-1")
        self.assertFalse(tracker.failed)
        self.assertFalse(tracker.interrupted)

    def test_notify_callback_noop_completes_workflow(self):
        tracker = _OperationTracker()
        manager = WorkflowManager()
        manager.set_operation_tracker(tracker)
        manager.set_callbacks(
            trigger_scan_func=lambda _context: True,
            check_scan_func=lambda _context: True,
            trigger_probe_func=lambda _context: True,
            check_probe_func=lambda _context: True,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: {"success": False, "message": "Nessuna pubblicazione da notificare."},
        )

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("full"))
            manager._thread.join(timeout=3)

        self.assertFalse(manager._thread.is_alive())
        self.assertEqual("completed", manager.get_status()["status"])
        self.assertEqual("done", manager.get_status()["steps"][3]["status"])
        self.assertIn("Nessuna pubblicazione da notificare.", manager.get_status()["steps"][3]["details"])
        self.assertFalse(tracker.failed)
        self.assertTrue(tracker.finished)

    def test_notify_callback_real_failure_marks_workflow_failed(self):
        tracker = _OperationTracker()
        manager = WorkflowManager()
        manager.set_operation_tracker(tracker)
        manager.set_callbacks(
            trigger_scan_func=lambda _context: True,
            check_scan_func=lambda _context: True,
            trigger_probe_func=lambda _context: True,
            check_probe_func=lambda _context: True,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: {"success": False, "message": "Cache DB non disponibile", "errors": ["Cache DB non disponibile"]},
        )

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("full"))
            manager._thread.join(timeout=3)

        self.assertFalse(manager._thread.is_alive())
        self.assertEqual("failed", manager.get_status()["status"])
        self.assertEqual("failed", manager.get_status()["steps"][3]["status"])
        self.assertEqual(
            "Errore durante l'esecuzione del workflow",
            manager.get_status()["error"],
        )
        self.assertNotIn("Cache DB non disponibile", str(tracker.failed))
        self.assertTrue(tracker.failed)
        self.assertFalse(tracker.finished)

    def test_stop_during_probe_step_calls_probe_stop_callback(self):
        manager = WorkflowManager()
        probe_started = threading.Event()
        stopped_contexts = []

        def trigger_probe(_context):
            probe_started.set()
            return True

        manager.set_callbacks(
            trigger_scan_func=lambda _context: True,
            check_scan_func=lambda _context: True,
            trigger_probe_func=trigger_probe,
            check_probe_func=lambda _context: False,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: None,
        )
        manager._stop_probe_func = lambda context: stopped_contexts.append(dict(context))

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("smart", context={"server_id": "server-a"}))
            self.assertTrue(probe_started.wait(timeout=2))
            manager.stop()
            manager._thread.join(timeout=3)

        self.assertFalse(manager._thread.is_alive())
        self.assertEqual([{"server_id": "server-a"}], stopped_contexts)

    def test_start_is_rejected_until_stopping_thread_has_exited(self):
        manager = WorkflowManager()
        scan_started = threading.Event()
        release_scan = threading.Event()

        def trigger_scan(_context):
            scan_started.set()
            release_scan.wait(timeout=3)
            return True

        manager.set_callbacks(
            trigger_scan_func=trigger_scan,
            check_scan_func=lambda _context: True,
            trigger_probe_func=lambda _context: True,
            check_probe_func=lambda _context: True,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: None,
        )

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("full"))
            first_thread = manager._thread
            first_event = manager._stop_event
            first_workflow_id = manager.get_status()["workflow_id"]
            self.assertTrue(scan_started.wait(timeout=2))

            manager.stop()

            self.assertEqual("stopping", manager.get_status()["status"])
            self.assertFalse(manager.start("smart"))
            self.assertIs(first_thread, manager._thread)
            self.assertIs(first_event, manager._stop_event)
            self.assertEqual(first_workflow_id, manager.get_status()["workflow_id"])

            release_scan.set()
            first_thread.join(timeout=3)
            self.assertFalse(first_thread.is_alive())

            self.assertTrue(manager.start("smart"))
            second_thread = manager._thread
            second_event = manager._stop_event
            second_workflow_id = manager.get_status()["workflow_id"]
            second_thread.join(timeout=3)

        self.assertFalse(second_thread.is_alive())
        self.assertIsNot(first_event, second_event)
        self.assertFalse(second_event.is_set())
        self.assertNotEqual(first_workflow_id, second_workflow_id)
        self.assertEqual("completed", manager.get_status()["status"])

    def test_start_is_rejected_while_completed_thread_finishes_tracking(self):
        manager = WorkflowManager()
        completion_started = threading.Event()
        release_completion = threading.Event()
        manager.set_callbacks(
            trigger_scan_func=lambda _context: True,
            check_scan_func=lambda _context: True,
            trigger_probe_func=lambda _context: True,
            check_probe_func=lambda _context: True,
            refresh_cache_func=lambda _context: None,
            notify_func=lambda _context: None,
        )

        def block_completion(_completion_status, _message, _workflow_id=None):
            completion_started.set()
            release_completion.wait(timeout=3)

        manager._complete_workflow_operation = block_completion

        with patch("time.sleep", lambda _seconds: None):
            self.assertTrue(manager.start("full"))
            first_thread = manager._thread
            first_workflow_id = manager.get_status()["workflow_id"]
            self.assertTrue(completion_started.wait(timeout=2))

            self.assertEqual("completed", manager.get_status()["status"])
            self.assertTrue(first_thread.is_alive())
            self.assertTrue(manager.is_running())
            self.assertFalse(manager.start("smart"))
            self.assertEqual(first_workflow_id, manager.get_status()["workflow_id"])

            release_completion.set()
            first_thread.join(timeout=3)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(manager.is_running())

    def test_stale_workflow_generation_cannot_update_current_steps(self):
        manager = WorkflowManager()
        with manager._lock:
            manager._status["workflow_id"] = "current-workflow"
            manager._status["steps"] = manager._initialize_steps("full")

        updated = manager._update_step_status(
            0,
            "done",
            "Aggiornamento obsoleto",
            100,
            workflow_id="previous-workflow",
        )

        self.assertFalse(updated)
        self.assertEqual("pending", manager.get_status()["steps"][0]["status"])


if __name__ == "__main__":
    unittest.main()
