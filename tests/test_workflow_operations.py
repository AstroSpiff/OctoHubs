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
        self.assertIn("Cache DB non disponibile", manager.get_status()["error"])
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


if __name__ == "__main__":
    unittest.main()
