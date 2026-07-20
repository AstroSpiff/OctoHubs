"""Refresh requests endpoint behavior."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from app_state import _JELLYSEERR_REFRESH_STATE
from services.manager import _build_refresh_requests_snapshot


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
            payload, status_code = _build_refresh_requests_snapshot()

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        self.assertIn("gia in corso", payload["message"])
        self.assertTrue(_JELLYSEERR_REFRESH_STATE["running"])


if __name__ == "__main__":
    unittest.main()
