"""Workflow operations center integration."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
