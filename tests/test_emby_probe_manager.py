"""STRM Probe manager stop semantics."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from emby_probe.constants import PROBE_SCOPE_LIBRARIES, PROBE_SCOPE_RECENT
from emby_probe.manager import EmbyProbeManager


class _NoWaitStopFlag:
    def __init__(self):
        self._flag = False

    def is_set(self):
        return self._flag

    def set(self):
        self._flag = True

    def wait(self, timeout=None):
        return self._flag


class _ParallelProbeDB:
    def __init__(self, *, parallelism=3, item_count=4):
        self._lock = threading.Lock()
        self.parallelism = parallelism
        self.queue = [
            {
                "item_id": f"item-{index}",
                "media_source_id": f"source-{index}",
                "name": f"Item {index}",
                "library_id": "lib-1",
                "library_name": "Movies",
            }
            for index in range(1, item_count + 1)
        ]
        self.history = []

    def get_recent_scan_config(self, server_id):
        return {"probe_parallelism": self.parallelism}

    def get_probe_queue(self, server_id, library_ids=None, scope="libraries"):
        with self._lock:
            return list(self.queue)

    def load_probe_blacklist(self, server_id, scope="libraries"):
        return {}

    def remove_from_probe_queue(self, server_id, item_id, media_source_id, scope="libraries"):
        with self._lock:
            self.queue = [
                item for item in self.queue
                if not (
                    item.get("item_id") == item_id
                    and item.get("media_source_id") == media_source_id
                )
            ]

    def remove_from_probe_blacklist(self, server_id, item_id, media_source_id, scope="libraries"):
        return None

    def update_probe_blacklist(self, *args, **kwargs):
        return 1

    def add_probe_history(self, row):
        with self._lock:
            self.history.append(row)

    def add_to_probe_queue(self, items):
        with self._lock:
            self.queue.extend(items)


class _ParallelProbeManager(EmbyProbeManager):
    def __init__(self):
        super().__init__()
        self._probe_lock = threading.Lock()
        self.active_probe_count = 0
        self.max_active_probe_count = 0

    def _probe_item(self, server, item_id, item_name, media_source_id=None):
        with self._probe_lock:
            self.active_probe_count += 1
            self.max_active_probe_count = max(self.max_active_probe_count, self.active_probe_count)
        threading.Event().wait(0.05)
        with self._probe_lock:
            self.active_probe_count -= 1
        return True

    def _verify_probe_metadata(self, server, item_id, media_source_id=None, max_retries=2):
        return True, None


class _ContinuousProbeManager(_ParallelProbeManager):
    def __init__(self):
        super().__init__()
        self.started_at = {}
        self.finished_at = {}

    def _probe_item(self, server, item_id, item_name, media_source_id=None):
        with self._probe_lock:
            self.active_probe_count += 1
            self.max_active_probe_count = max(self.max_active_probe_count, self.active_probe_count)
            self.started_at[item_id] = time.monotonic()
        wait_time = 0.15 if item_id == "item-1" else 0.02
        threading.Event().wait(wait_time)
        with self._probe_lock:
            self.finished_at[item_id] = time.monotonic()
            self.active_probe_count -= 1
        return True


class EmbyProbeManagerStopTests(unittest.TestCase):
    def test_stop_recent_combo_stops_child_workers_for_server(self):
        manager = EmbyProbeManager()
        manager._stop_flags["server-a"] = {
            "combo_recent": threading.Event(),
            "recent_discovery": threading.Event(),
            "recent_processing": threading.Event(),
        }

        self.assertTrue(manager.stop_combo_workflow("server-a", scope=PROBE_SCOPE_RECENT))

        self.assertTrue(manager._stop_flags["server-a"]["combo_recent"].is_set())
        self.assertTrue(manager._stop_flags["server-a"]["recent_discovery"].is_set())
        self.assertTrue(manager._stop_flags["server-a"]["recent_processing"].is_set())

    def test_stop_libraries_combo_stops_child_workers_for_server(self):
        manager = EmbyProbeManager()
        manager._stop_flags["server-a"] = {
            "combo_libraries": threading.Event(),
            "discovery": threading.Event(),
            "processing": threading.Event(),
        }

        self.assertTrue(manager.stop_combo_workflow("server-a", scope=PROBE_SCOPE_LIBRARIES))

        self.assertTrue(manager._stop_flags["server-a"]["combo_libraries"].is_set())
        self.assertTrue(manager._stop_flags["server-a"]["discovery"].is_set())
        self.assertTrue(manager._stop_flags["server-a"]["processing"].is_set())

    def test_stop_recent_combo_all_stops_global_and_child_workers(self):
        manager = EmbyProbeManager()
        manager._global_stop_flags["combo_all_recent"] = threading.Event()
        manager._global_stop_flags["recent_discovery_all"] = threading.Event()
        manager._global_stop_flags["recent_processing_all"] = threading.Event()
        manager._stop_flags["server-a"] = {
            "combo_recent": threading.Event(),
            "recent_discovery": threading.Event(),
            "recent_processing": threading.Event(),
        }
        manager._stop_flags["server-b"] = {
            "combo_recent": threading.Event(),
            "recent_discovery": threading.Event(),
            "recent_processing": threading.Event(),
        }

        self.assertTrue(manager.stop_combo_workflow_all_servers(scope=PROBE_SCOPE_RECENT))

        self.assertTrue(manager._global_stop_flags["combo_all_recent"].is_set())
        self.assertTrue(manager._global_stop_flags["recent_discovery_all"].is_set())
        self.assertTrue(manager._global_stop_flags["recent_processing_all"].is_set())
        for server_id in ("server-a", "server-b"):
            self.assertTrue(manager._stop_flags[server_id]["combo_recent"].is_set())
            self.assertTrue(manager._stop_flags[server_id]["recent_discovery"].is_set())
            self.assertTrue(manager._stop_flags[server_id]["recent_processing"].is_set())


class EmbyProbeManagerParallelismTests(unittest.TestCase):
    def test_processing_worker_uses_per_server_probe_parallelism(self):
        db = _ParallelProbeDB()
        manager = _ParallelProbeManager()
        manager.configure(lambda: db)
        server = {"id": "server-a", "name": "Alpha", "enabled": True, "probe_parallelism": 3}

        with patch("emby_probe.libraries.time.sleep", lambda _seconds: None):
            manager._processing_worker(
                server,
                "server-a",
                "forced",
                _NoWaitStopFlag(),
                None,
                PROBE_SCOPE_RECENT,
                "recent_processing",
            )

        self.assertGreaterEqual(manager.max_active_probe_count, 2)
        self.assertEqual(4, len(db.history))
        self.assertFalse(db.queue)

    def test_processing_worker_keeps_parallel_slots_filled_while_one_probe_is_slow(self):
        db = _ParallelProbeDB(parallelism=2, item_count=3)
        manager = _ContinuousProbeManager()
        manager.configure(lambda: db)
        server = {"id": "server-a", "name": "Alpha", "enabled": True, "probe_parallelism": 2}

        with patch("emby_probe.libraries.time.sleep", lambda _seconds: None):
            manager._processing_worker(
                server,
                "server-a",
                "forced",
                _NoWaitStopFlag(),
                None,
                PROBE_SCOPE_RECENT,
                "recent_processing",
            )

        self.assertIn("item-3", manager.started_at)
        self.assertLess(manager.started_at["item-3"], manager.finished_at["item-1"])
        self.assertEqual(3, len(db.history))
        self.assertFalse(db.queue)


if __name__ == "__main__":
    unittest.main()
