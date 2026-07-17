"""STRM Probe manager stop semantics."""

from __future__ import annotations

import threading
import unittest

from emby_probe.constants import PROBE_SCOPE_LIBRARIES, PROBE_SCOPE_RECENT
from emby_probe.manager import EmbyProbeManager


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


if __name__ == "__main__":
    unittest.main()
