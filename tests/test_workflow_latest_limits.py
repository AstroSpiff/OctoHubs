"""Workflow latest-publications limits."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import workflows


class _RefreshManager:
    def __init__(self):
        self.calls = []
        self.progress_tracker = self
        self._refreshing = False

    def is_refreshing(self):
        return self._refreshing

    def refresh_full(self, limit, per_server_limit, **kwargs):
        self.calls.append((limit, per_server_limit, kwargs))

    def get_snapshot(self):
        return {}


class _ImmediateThread:
    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


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

        self.assertEqual(1, len(manager.calls))
        self.assertEqual((80, 40), manager.calls[0][:2])

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


if __name__ == "__main__":
    unittest.main()
