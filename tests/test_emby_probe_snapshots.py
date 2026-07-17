"""STRM Probe snapshot handlers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_probe import snapshots


def _config():
    return {
        "EMBY": {
            "SERVERS": [
                {"id": "server-a", "name": "Alpha", "enabled": True},
                {"id": "server-b", "name": "Beta", "enabled": False},
            ]
        }
    }


class _Backend:
    def __init__(self):
        self.calls = []
        self.saved_config = None

    def get_recent_scan_config(self, server_id):
        self.calls.append(("get_recent_scan_config", server_id))
        return {
            "window_size": 9000,
            "window_threshold": "95%",
            "max_days": 1,
            "max_items": 99999,
            "safety_margin_days": 0,
        }

    def save_recent_scan_config(self, server_id, config):
        self.calls.append(("save_recent_scan_config", server_id, config))
        self.saved_config = config

    def get_probe_queue(self, server_id, scope="libraries"):
        self.calls.append(("get_probe_queue", server_id, scope))
        return [{"item_id": "item-1", "media_source_id": None, "name": "Queued"}]

    def remove_from_probe_queue(self, server_id, item_id, media_source_id, scope="libraries"):
        self.calls.append(("remove_from_probe_queue", server_id, item_id, media_source_id, scope))

    def clear_probe_queue(self, server_id, scope="libraries"):
        self.calls.append(("clear_probe_queue", server_id, scope))

    def get_probe_history(self, server_id, limit, scope="libraries"):
        self.calls.append(("get_probe_history", server_id, limit, scope))
        return [{"item_id": "item-1"}]

    def clear_probe_history(self, server_id, scope="libraries"):
        self.calls.append(("clear_probe_history", server_id, scope))

    def get_probe_blacklist(self, server_id, min_retry_count=3, error_type=None, scope="libraries"):
        self.calls.append(("get_probe_blacklist", server_id, min_retry_count, error_type, scope))
        return [{"item_id": "item-1"}]

    def remove_from_probe_blacklist(self, server_id, item_id, media_source_id, scope="libraries"):
        self.calls.append(("remove_from_probe_blacklist", server_id, item_id, media_source_id, scope))

    def clear_probe_blacklist(self, server_id, error_type=None, scope="libraries"):
        self.calls.append(("clear_probe_blacklist", server_id, error_type, scope))


class _ProbeManager:
    def __init__(self):
        self.calls = []

    def start_recent_discovery_sequence(self, servers, limit):
        self.calls.append(("start_recent_discovery_sequence", [server["id"] for server in servers], limit))
        return True

    def start_combo_workflow(self, server, server_id, mode="smart", scope="recent", target_libraries=None):
        self.calls.append(("start_combo_workflow", server_id, mode, scope, target_libraries))
        return True

    def stop_combo_workflow(self, server_id, scope="recent"):
        self.calls.append(("stop_combo_workflow", server_id, scope))
        return True

    def stop_combo_workflow_all_servers(self, scope="recent"):
        self.calls.append(("stop_combo_workflow_all_servers", scope))
        return True

    def stop_recent_discovery_sequence(self):
        self.calls.append(("stop_recent_discovery_sequence",))
        return True

    def stop_recent_processing_sequence(self):
        self.calls.append(("stop_recent_processing_sequence",))
        return True

    def stop_recent_discovery(self, server_id):
        self.calls.append(("stop_recent_discovery", server_id))
        return True

    def stop_recent_processing(self, server_id):
        self.calls.append(("stop_recent_processing", server_id))
        return True

    def stop_discovery(self, server_id):
        self.calls.append(("stop_discovery", server_id))
        return True

    def stop_processing(self, server_id):
        self.calls.append(("stop_processing", server_id))
        return True

    def get_status(self, server_id):
        self.calls.append(("get_status", server_id))
        return {"discovery": {"library_totals": {"lib-1": 4}}}

    def retry_item(self, server, server_id, item_id, media_source_id, scope="libraries"):
        self.calls.append(("retry_item", server_id, item_id, media_source_id, scope))
        return True, "queued"


class EmbyProbeSnapshotTests(unittest.TestCase):
    def test_recent_config_get_and_save_normalize_values(self):
        backend = _Backend()
        with patch("emby_probe.snapshots.load_config", return_value=(_config(), True)), patch(
            "emby_probe.snapshots._ensure_db_backend",
            return_value=backend,
        ):
            payload, status = snapshots._probe_recent_config_get_snapshot("server-a")
            self.assertEqual(200, status)
            self.assertEqual(
                {
                    "window_size": 2000,
                    "window_threshold": 0.95,
                    "max_days": 7,
                    "max_items": 10000,
                    "safety_margin_days": 1,
                },
                payload["config"],
            )

            payload, status = snapshots._probe_recent_config_save_snapshot({
                "server_id": "server-a",
                "config": {
                    "window_size": 250,
                    "window_threshold": "87%",
                    "max_days": 30,
                    "max_items": 1500,
                    "safety_margin_days": 3,
                },
            })

        self.assertEqual(200, status)
        self.assertEqual(0.87, payload["config"]["window_threshold"])
        self.assertEqual(payload["config"], backend.saved_config)

    def test_recent_start_all_filters_enabled_servers_and_coerces_limit(self):
        manager = _ProbeManager()
        with patch("emby_probe.snapshots.load_config", return_value=(_config(), True)), patch(
            "emby_probe.snapshots.get_probe_manager",
            return_value=manager,
        ):
            payload, status = snapshots._probe_recent_start_all_snapshot({"limit": 9999})

        self.assertEqual(200, status)
        self.assertEqual(["server-a"], payload["started"])
        self.assertEqual([("start_recent_discovery_sequence", ["server-a"], 1000)], manager.calls)

    def test_libraries_combo_start_passes_selected_libraries(self):
        manager = _ProbeManager()
        with patch("emby_probe.snapshots.load_config", return_value=(_config(), True)), patch(
            "emby_probe.snapshots.get_probe_manager",
            return_value=manager,
        ):
            payload, status = snapshots._probe_libraries_combo_start_snapshot({
                "server_id": "server-a",
                "mode": "forced",
                "libraries": ["lib-1", "lib-2"],
            })

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(
            [("start_combo_workflow", "server-a", "forced", "libraries", ["lib-1", "lib-2"])],
            manager.calls,
        )

    def test_recent_combo_stop_all_stops_global_and_per_server_workers(self):
        manager = _ProbeManager()
        with patch("emby_probe.snapshots.load_config", return_value=(_config(), True)), patch(
            "emby_probe.snapshots.get_probe_manager",
            return_value=manager,
        ):
            payload, status = snapshots._probe_recent_combo_stop_all_snapshot()

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertIn(("stop_combo_workflow_all_servers", "recent"), manager.calls)
        self.assertIn(("stop_recent_discovery_sequence",), manager.calls)
        self.assertIn(("stop_recent_processing_sequence",), manager.calls)
        self.assertIn(("stop_recent_discovery", "server-a"), manager.calls)
        self.assertIn(("stop_recent_processing", "server-a"), manager.calls)

    def test_libraries_combo_stop_stops_combo_discovery_and_processing(self):
        manager = _ProbeManager()
        with patch("emby_probe.snapshots.get_probe_manager", return_value=manager):
            payload, status = snapshots._probe_libraries_combo_stop_snapshot({"server_id": "server-a"})

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(
            [
                ("stop_combo_workflow", "server-a", "libraries"),
                ("stop_discovery", "server-a"),
                ("stop_processing", "server-a"),
            ],
            manager.calls,
        )

    def test_queue_history_blacklist_and_retry_keep_scope(self):
        backend = _Backend()
        manager = _ProbeManager()
        with patch("emby_probe.snapshots._ensure_db_backend", return_value=backend), patch(
            "emby_probe.snapshots.get_probe_manager",
            return_value=manager,
        ), patch(
            "emby_probe.snapshots.load_config",
            return_value=(_config(), True),
        ):
            snapshots._probe_queue_get_snapshot("server-a", "recent")
            snapshots._probe_queue_delete_snapshot("server-a", None, None, "recent")
            snapshots._probe_history_get_snapshot("server-a", "25", "recent")
            snapshots._probe_history_delete_snapshot("server-a", "recent")
            snapshots._probe_blacklist_get_snapshot("server-a", "2", "incomplete", "recent")
            snapshots._probe_blacklist_delete_snapshot("server-a", None, None, "incomplete", "recent")
            snapshots._probe_retry_snapshot({
                "server_id": "server-a",
                "item_id": "item-1",
                "media_source_id": "source-1",
                "scope": "recent",
            })

        self.assertIn(("get_probe_queue", "server-a", "recent"), backend.calls)
        self.assertIn(("clear_probe_queue", "server-a", "recent"), backend.calls)
        self.assertIn(("get_probe_history", "server-a", 25, "recent"), backend.calls)
        self.assertIn(("clear_probe_history", "server-a", "recent"), backend.calls)
        self.assertIn(("get_probe_blacklist", "server-a", 2, "incomplete", "recent"), backend.calls)
        self.assertIn(("clear_probe_blacklist", "server-a", "incomplete", "recent"), backend.calls)
        self.assertIn(("retry_item", "server-a", "item-1", "source-1", "recent"), manager.calls)


if __name__ == "__main__":
    unittest.main()
