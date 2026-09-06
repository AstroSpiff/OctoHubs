"""Persistent operation status tracking."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
import unittest

from core.operations import OperationTracker


class _Storage:
    def __init__(self):
        self.values = {}

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value


class _AtomicStorage(_Storage):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.update_calls = 0

    def update_key_value(self, key, updater):
        with self._lock:
            self.update_calls += 1
            updated = updater(deepcopy(self.values.get(key)))
            self.values[key] = deepcopy(updated)
            return deepcopy(updated)


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

    def test_failure_never_persists_raw_exception_details(self):
        storage = _Storage()
        tracker = OperationTracker(storage, now=_Clock())
        operation = tracker.start("clone", "Clona utente")
        canary = "postgresql://admin:CANARY_PASSWORD@db.internal/octohubs"

        failed = tracker.fail(
            operation["id"],
            f"Clonazione utente non riuscita: {canary}",
            result={"error": canary},
        )

        self.assertEqual(failed["message"], "Operazione non riuscita")
        self.assertEqual(failed["error"], "Operazione non riuscita")
        self.assertEqual(failed["result"], {})
        self.assertNotIn("CANARY_PASSWORD", str(storage.values))

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

    def test_interrupt_active_marks_orphaned_running_operations_after_restart(self):
        tracker = OperationTracker(_Storage(), now=_Clock())
        running = tracker.start("workflow", "Workflow", total=4)
        tracker.update(running["id"], current=2, total=4)
        completed = tracker.start("latest_refresh", "Pubblicazioni")
        tracker.finish(completed["id"])

        interrupted = tracker.interrupt_active("Interrotta da riavvio OctoHubs")
        operations = tracker.list_operations()

        self.assertEqual(interrupted, 1)
        by_id = {item["id"]: item for item in operations}
        self.assertEqual(by_id[running["id"]]["status"], "interrupted")
        self.assertEqual(by_id[running["id"]]["progress"], 50)
        self.assertEqual(by_id[running["id"]]["message"], "Interrotta da riavvio OctoHubs")
        self.assertEqual(by_id[completed["id"]]["status"], "success")
        self.assertEqual(tracker.active_count(), 0)

    def test_operation_tracker_ignores_removed_octohub_storage_key(self):
        storage = _Storage()
        storage.set_key_value(
            "octohub_operations:v1",
            {
                "version": 1,
                "operations": {
                    "old-op": {
                        "id": "old-op",
                        "status": "running",
                        "updated_at": "2026-07-15T10:00:00+00:00",
                    }
                },
            },
        )
        tracker = OperationTracker(storage, now=_Clock())

        operations = tracker.list_operations()

        self.assertEqual(operations, [])

    def test_two_trackers_keep_both_concurrent_operations(self):
        storage = _AtomicStorage()
        first_tracker = OperationTracker(storage, now=_Clock())
        second_tracker = OperationTracker(storage, now=_Clock())
        barrier = threading.Barrier(2)
        created = []

        def start(tracker, kind):
            barrier.wait(timeout=3)
            created.append(tracker.start(kind, kind))

        first = threading.Thread(target=start, args=(first_tracker, "first"))
        second = threading.Thread(target=start, args=(second_tracker, "second"))
        first.start()
        second.start()
        first.join(timeout=3)
        second.join(timeout=3)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(storage.update_calls, 2)
        self.assertEqual(
            {operation["id"] for operation in created},
            {operation["id"] for operation in first_tracker.list_operations()},
        )

    def test_second_process_cannot_update_or_interrupt_a_fresh_foreign_operation(self):
        storage = _AtomicStorage()
        def now():
            return datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

        first_tracker = OperationTracker(storage, now=now, owner_id="process-a")
        second_tracker = OperationTracker(storage, now=now, owner_id="process-b")
        operation = first_tracker.start("workflow", "Live workflow")

        self.assertIsNone(second_tracker.update(operation["id"], message="foreign update"))
        self.assertEqual(second_tracker.interrupt_active(), 0)
        self.assertEqual(second_tracker.interrupt_stale(stale_after_seconds=60), 0)
        current = first_tracker.list_operations()[0]
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["message"], "Avvio operazione")

    def test_new_process_interrupts_only_a_genuinely_stale_heartbeat(self):
        storage = _AtomicStorage()
        first_tracker = OperationTracker(
            storage,
            now=lambda: datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc),
            owner_id="process-a",
        )
        operation = first_tracker.start("workflow", "Crashed workflow")
        second_tracker = OperationTracker(
            storage,
            now=lambda: datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
            owner_id="process-b",
        )

        self.assertEqual(second_tracker.interrupt_stale(stale_after_seconds=60), 1)
        current = {item["id"]: item for item in second_tracker.list_operations()}[operation["id"]]
        self.assertEqual(current["status"], "interrupted")
        self.assertIsNone(first_tracker.finish(operation["id"]))
        current = {item["id"]: item for item in second_tracker.list_operations()}[operation["id"]]
        self.assertEqual(current["status"], "interrupted")

    def test_periodic_heartbeat_renews_a_blocked_operation_without_progress(self):
        storage = _AtomicStorage()
        clock_lock = threading.Lock()
        current_time = [datetime(2026, 9, 1, 11, 0, tzinfo=timezone.utc)]

        def now():
            with clock_lock:
                return current_time[0]

        tracker = OperationTracker(
            storage,
            now=now,
            owner_id="process-a",
            heartbeat_interval_seconds=0.01,
        )
        operation = tracker.start("workflow", "Blocked workflow")
        with clock_lock:
            current_time[0] = datetime(2026, 9, 1, 11, 20, tzinfo=timezone.utc)

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            raw = storage.get_key_value(tracker.key)
            heartbeat = raw["operations"][operation["id"]]["_heartbeat_at"]
            if heartbeat.startswith("2026-09-01T11:20"):
                break
            time.sleep(0.01)
        else:
            self.fail("Periodic heartbeat did not renew the operation")

        recovery = OperationTracker(
            storage,
            now=lambda: datetime(2026, 9, 1, 11, 20, 30, tzinfo=timezone.utc),
            owner_id="process-b",
        )
        self.assertEqual(recovery.interrupt_stale(stale_after_seconds=60), 0)
        self.assertIsNotNone(tracker.finish(operation["id"]))
        self.assertTrue(tracker.shutdown())

    def test_heartbeat_sweeper_batches_all_owned_operations_in_one_write(self):
        storage = _AtomicStorage()
        tracker = OperationTracker(storage, now=_Clock())
        operations = [tracker.start("test", f"Operation {index}") for index in range(20)]
        writes_after_start = storage.update_calls

        self.assertEqual(tracker._heartbeat_owned_operations(), 20)

        self.assertEqual(storage.update_calls, writes_after_start + 1)
        for operation in operations:
            tracker.finish(operation["id"])
        self.assertTrue(tracker.shutdown())

    def test_heartbeat_sweeper_has_one_thread_and_is_lifecycle_owned(self):
        storage = _AtomicStorage()
        tracker = OperationTracker(storage, heartbeat_interval_seconds=0.01)
        operations = [tracker.start("test", f"Operation {index}") for index in range(20)]
        deadline = time.monotonic() + 1
        while storage.update_calls == len(operations) and time.monotonic() < deadline:
            time.sleep(0.01)

        heartbeat_thread = tracker._heartbeat_thread
        self.assertIsNotNone(heartbeat_thread)
        assert heartbeat_thread is not None
        self.assertTrue(heartbeat_thread.is_alive())
        self.assertEqual(
            sum(thread is heartbeat_thread for thread in threading.enumerate()),
            1,
        )
        self.assertTrue(tracker.shutdown())
        writes_after_shutdown = storage.update_calls
        time.sleep(0.03)
        self.assertEqual(storage.update_calls, writes_after_shutdown)
        self.assertEqual(tracker.active_count(), 0)
        with self.assertRaisesRegex(RuntimeError, "shutdown"):
            tracker.start("test", "Late operation")

        tracker.initialize()
        restarted = tracker.start("test", "New lifespan")
        self.assertIsNotNone(tracker.finish(restarted["id"]))
        self.assertTrue(tracker.shutdown())


if __name__ == "__main__":
    unittest.main()
