"""Persistent operation status tracking."""

from __future__ import annotations

import unittest

from core.operations import OperationTracker


class _Storage:
    def __init__(self):
        self.values = {}

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value


class _Clock:
    def __init__(self):
        self.index = 0

    def __call__(self):
        self.index += 1
        return f"2026-07-15T10:00:{self.index:02d}+00:00"


class OperationTrackerTests(unittest.TestCase):
    def test_operation_tracker_records_running_progress_and_completion(self):
        tracker = OperationTracker(_Storage(), now=_Clock())

        operation = tracker.start("clone", "Clona a_test", summary="a_test -> Server B", total=4)
        running = tracker.update(
            operation["id"],
            message="Creo utente di destinazione",
            current=1,
            total=4,
            details={"target": "Server B"},
        )
        done = tracker.finish(operation["id"], message="Clonazione completata", result={"ok": True})

        self.assertEqual(running["status"], "running")
        self.assertEqual(running["progress"], 25)
        self.assertEqual(running["message"], "Creo utente di destinazione")
        self.assertEqual(done["status"], "success")
        self.assertEqual(done["progress"], 100)
        self.assertEqual(done["result"], {"ok": True})

    def test_list_operations_returns_active_first_then_recent(self):
        tracker = OperationTracker(_Storage(), now=_Clock())
        clone = tracker.start("clone", "Clona a_test")
        apply = tracker.start("settings_apply", "Applica impostazioni")
        create = tracker.start("create_user", "Crea utente")

        tracker.finish(clone["id"])
        tracker.finish(create["id"])

        operations = tracker.list_operations()

        self.assertEqual([item["id"] for item in operations], [apply["id"], create["id"], clone["id"]])
        self.assertEqual(operations[0]["status"], "running")
        self.assertEqual(operations[1]["status"], "success")

    def test_clear_completed_keeps_running_operations(self):
        storage = _Storage()
        tracker = OperationTracker(storage, now=_Clock())
        running = tracker.start("group_sync", "Sync gruppo")
        completed = tracker.start("create_user", "Crea utente")
        tracker.finish(completed["id"])

        removed = tracker.clear_completed()
        remaining = tracker.list_operations()

        self.assertEqual(removed, 1)
        self.assertEqual([item["id"] for item in remaining], [running["id"]])

    def test_interrupt_marks_operation_terminal_without_losing_progress(self):
        tracker = OperationTracker(_Storage(), now=_Clock())
        operation = tracker.start("workflow", "Aggiornamento completo", total=4)
        tracker.update(
            operation["id"],
            message="Scansione File Librerie",
            current=1,
            total=4,
            details={"current_step_id": "scan"},
        )

        interrupted = tracker.interrupt(operation["id"], message="Workflow interrotto dall'utente")

        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["progress"], 25)
        self.assertEqual(interrupted["message"], "Workflow interrotto dall'utente")
        self.assertIsNotNone(interrupted["finished_at"])
        self.assertEqual(tracker.active_count(), 0)


if __name__ == "__main__":
    unittest.main()
