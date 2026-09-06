"""Refresh requests endpoint behavior."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock, patch

from app_state import _JELLYSEERR_REFRESH_STATE
from services.research_request_actions import refresh_requests


class RefreshRequestsSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._original_state = copy.deepcopy(_JELLYSEERR_REFRESH_STATE)

    def tearDown(self):
        _JELLYSEERR_REFRESH_STATE.clear()
        _JELLYSEERR_REFRESH_STATE.update(self._original_state)

    def test_running_refresh_is_not_started_twice(self):
        _JELLYSEERR_REFRESH_STATE.update({
            "running": True,
            "last_status": None,
            "last_error": None,
        })

        with patch(
            "emby_runtime.api_clients.get_jellyseerr_requests",
            side_effect=AssertionError("refresh should not call Jellyseerr twice"),
        ):
            payload, status_code = refresh_requests()

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        self.assertIn("gia in corso", payload["message"])
        self.assertTrue(_JELLYSEERR_REFRESH_STATE["running"])

    def test_refresh_publishes_overview_and_latest_index_through_atomic_writer(self):
        backend = Mock()
        requests_data = [{"id": 7}]
        overview = [{"request_id": "7", "media_type": "movie"}]
        entries = [{"request_id": "7", "tmdb_id": 42}]

        with patch("core.config_manager.load_config", return_value=({"JELLYSEERR": {}}, True)), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ), patch(
            "emby_runtime.api_clients.get_jellyseerr_requests",
            return_value=(requests_data, True),
        ), patch(
            "services.request_refresh_snapshot._summarize_requests_for_dashboard",
            return_value=overview,
        ), patch(
            "services.request_refresh_snapshot.latest_jellyseerr.build_request_entries",
            return_value=entries,
        ):
            payload, status_code = refresh_requests()

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        backend.save_request_refresh_snapshot.assert_called_once_with(overview, entries)
        self.assertEqual("success", _JELLYSEERR_REFRESH_STATE["last_status"])

    def test_refresh_fails_closed_when_atomic_projection_publish_fails(self):
        backend = Mock()
        backend.save_request_refresh_snapshot.side_effect = RuntimeError("write failed")

        with patch("core.config_manager.load_config", return_value=({"JELLYSEERR": {}}, True)), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ), patch(
            "emby_runtime.api_clients.get_jellyseerr_requests",
            return_value=([{"id": 7}], True),
        ), patch(
            "services.request_refresh_snapshot._summarize_requests_for_dashboard",
            return_value=[{"request_id": "7", "media_type": "movie"}],
        ), patch(
            "services.request_refresh_snapshot.latest_jellyseerr.build_request_entries",
            return_value=[{"request_id": "7"}],
        ):
            payload, status_code = refresh_requests()

        self.assertEqual(500, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("error", _JELLYSEERR_REFRESH_STATE["last_status"])
        self.assertFalse(_JELLYSEERR_REFRESH_STATE["running"])


if __name__ == "__main__":
    unittest.main()
