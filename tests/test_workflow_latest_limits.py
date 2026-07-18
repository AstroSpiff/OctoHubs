"""Workflow latest-publications limits."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import workflows


class _RefreshManager:
    def __init__(self):
        self.calls = []
        self.incremental_calls = []
        self.progress_tracker = self
        self._refreshing = False
        self.snapshot = {"payload": {"movies": [], "series": [], "errors": []}}

    def is_refreshing(self):
        return self._refreshing

    def refresh_full(self, limit, per_server_limit, **kwargs):
        self.calls.append((limit, per_server_limit, kwargs))
        return self.snapshot["payload"], None

    def refresh_incremental(self, limit, per_server_limit, **kwargs):
        self.incremental_calls.append((limit, per_server_limit, kwargs))
        return self.snapshot["payload"], None

    def get_snapshot(self, mode="batch"):
        return self.snapshot


class _FailingRefreshManager(_RefreshManager):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def refresh_full(self, limit, per_server_limit, **kwargs):
        self.calls.append((limit, per_server_limit, kwargs))
        return None, self.error

    def refresh_incremental(self, limit, per_server_limit, **kwargs):
        self.incremental_calls.append((limit, per_server_limit, kwargs))
        return None, self.error


class _MissingCacheRefreshManager(_RefreshManager):
    def __init__(self):
        super().__init__()
        self.snapshot = {"payload": None}


class _SlowPollingRefreshManager(_RefreshManager):
    def __init__(self, refreshing_polls):
        super().__init__()
        self.refreshing_polls = refreshing_polls
        self.is_refreshing_calls = 0

    def is_refreshing(self):
        self.is_refreshing_calls += 1
        if self.is_refreshing_calls == 1:
            return False
        return self.is_refreshing_calls <= self.refreshing_polls


class _ImmediateThread:
    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class _ProbeManager:
    def __init__(self):
        self.calls = []

    def stop_combo_workflow_all_servers(self, scope="recent"):
        self.calls.append(("stop_combo_workflow_all_servers", scope))
        return True

    def stop_recent_discovery_sequence(self):
        self.calls.append(("stop_recent_discovery_sequence",))
        return True

    def stop_recent_processing_sequence(self):
        self.calls.append(("stop_recent_processing_sequence",))
        return True

    def stop_combo_workflow(self, server_id, scope="recent"):
        self.calls.append(("stop_combo_workflow", server_id, scope))
        return True

    def stop_recent_discovery(self, server_id):
        self.calls.append(("stop_recent_discovery", server_id))
        return True

    def stop_recent_processing(self, server_id):
        self.calls.append(("stop_recent_processing", server_id))
        return True


class WorkflowLatestLimitsTests(unittest.TestCase):
    def test_refresh_cache_uses_latest_workflow_limits(self):
        manager = _RefreshManager()
        config = {
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "enabled": True},
                    {"id": "server-b", "enabled": True},
                ]
            }
        }

        with patch("emby_latest.settings._load_latest_settings", return_value={"SETTINGS": {"max_movies": 40, "max_series": 10}}), patch(
            "services.workflows.load_config",
            return_value=(config, True),
        ), patch("services.workflows.get_emby_latest_manager", return_value=manager), patch(
            "services.manager._build_refresh_requests_snapshot",
            return_value=None,
        ), patch(
            "threading.Thread",
            side_effect=lambda target, daemon=True: _ImmediateThread(target, daemon=daemon),
        ), patch(
            "time.sleep",
            return_value=None,
        ):
            workflows._wf_refresh_cache({})

        self.assertEqual([], manager.calls)
        self.assertEqual(1, len(manager.incremental_calls))
        self.assertEqual((80, 40), manager.incremental_calls[0][:2])

    def test_refresh_cache_waits_longer_than_five_minutes_for_running_refresh(self):
        manager = _SlowPollingRefreshManager(refreshing_polls=170)
        time_value = {"now": 0}

        def fake_time():
            time_value["now"] += 2
            return time_value["now"]

        with patch("emby_latest.settings._load_latest_settings", return_value={"SETTINGS": {"max_movies": 10, "max_series": 10}}), patch(
            "services.workflows.load_config",
            return_value=({"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}, True),
        ), patch("services.workflows.get_emby_latest_manager", return_value=manager), patch(
            "services.manager._build_refresh_requests_snapshot",
            return_value=None,
        ), patch(
            "threading.Thread",
            side_effect=lambda target, daemon=True: _ImmediateThread(target, daemon=daemon),
        ), patch(
            "time.time",
            side_effect=fake_time,
        ), patch(
            "time.sleep",
            return_value=None,
        ):
            workflows._wf_refresh_cache({})

        self.assertGreater(time_value["now"], 300)

    def test_refresh_cache_raises_refresh_error_from_background_thread(self):
        manager = _FailingRefreshManager("forced refresh failure")

        with patch("emby_latest.settings._load_latest_settings", return_value={"SETTINGS": {"max_movies": 10, "max_series": 10}}), patch(
            "services.workflows.load_config",
            return_value=({"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}, True),
        ), patch("services.workflows.get_emby_latest_manager", return_value=manager), patch(
            "services.manager._build_refresh_requests_snapshot",
            return_value=None,
        ), patch(
            "threading.Thread",
            side_effect=lambda target, daemon=True: _ImmediateThread(target, daemon=daemon),
        ), patch(
            "time.sleep",
            return_value=None,
        ):
            with self.assertRaisesRegex(RuntimeError, "forced refresh failure"):
                workflows._wf_refresh_cache({})

    def test_refresh_cache_raises_when_completed_refresh_does_not_write_batch_cache(self):
        manager = _MissingCacheRefreshManager()

        with patch("emby_latest.settings._load_latest_settings", return_value={"SETTINGS": {"max_movies": 10, "max_series": 10}}), patch(
            "services.workflows.load_config",
            return_value=({"EMBY": {"SERVERS": [{"id": "server-a", "enabled": True}]}}, True),
        ), patch("services.workflows.get_emby_latest_manager", return_value=manager), patch(
            "services.manager._build_refresh_requests_snapshot",
            return_value=None,
        ), patch(
            "threading.Thread",
            side_effect=lambda target, daemon=True: _ImmediateThread(target, daemon=daemon),
        ), patch(
            "time.sleep",
            return_value=None,
        ):
            with self.assertRaisesRegex(RuntimeError, "Cache DB non disponibile"):
                workflows._wf_refresh_cache({})

    def test_notify_uses_latest_workflow_limits(self):
        calls = []
        config = {
            "DATABASE": {"ENABLED": True},
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "enabled": True},
                    {"id": "server-b", "enabled": True},
                ]
            },
        }

        def fake_send_notifications(per_server_limit, server_filter, **kwargs):
            calls.append((per_server_limit, server_filter, kwargs))
            return {"success": False, "message": "Nessuna pubblicazione da notificare."}

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflows._db_enabled",
            return_value=True,
        ), patch(
            "emby_latest.settings._load_latest_settings",
            return_value={"SETTINGS": {"max_movies": 20, "max_series": 25}},
        ), patch(
            "emby_latest.notifications.send_notifications",
            side_effect=fake_send_notifications,
        ), patch(
            "services.workflows._ensure_db_backend",
            return_value="db",
        ):
            workflows._wf_notify({"server_id": "server-a"})

        self.assertEqual(1, len(calls))
        self.assertEqual((25, "server-a"), calls[0][:2])

    def test_stop_probe_stops_recent_combo_and_processing_workers(self):
        manager = _ProbeManager()
        config = {
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "enabled": True},
                    {"id": "server-b", "enabled": True},
                ]
            }
        }

        with patch("services.workflows.load_config", return_value=(config, True)), patch(
            "services.workflows.get_probe_manager",
            return_value=manager,
        ):
            stopped = workflows._wf_stop_probe({"server_id": "server-a"})

        self.assertTrue(stopped)
        self.assertIn(("stop_combo_workflow_all_servers", "recent"), manager.calls)
        self.assertIn(("stop_recent_discovery_sequence",), manager.calls)
        self.assertIn(("stop_recent_processing_sequence",), manager.calls)
        self.assertIn(("stop_combo_workflow", "server-a", "recent"), manager.calls)
        self.assertIn(("stop_recent_discovery", "server-a"), manager.calls)
        self.assertIn(("stop_recent_processing", "server-a"), manager.calls)
        self.assertNotIn(("stop_recent_processing", "server-b"), manager.calls)


if __name__ == "__main__":
    unittest.main()
