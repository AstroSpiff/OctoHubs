"""Lightweight Jellyseerr refresh for Latest Publications."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.latest_jellyseerr import refresh_latest_jellyseerr_requests


class _Backend:
    def __init__(self):
        self.saved = []

    def save_jellyseerr_requests(self, entries):
        self.saved.append(entries)
        return len(entries)


class LatestJellyseerrRefreshTests(unittest.TestCase):
    def test_refresh_latest_jellyseerr_requests_saves_latest_index_only(self):
        backend = _Backend()
        config = {
            "JELLYSEERR_URL": "http://jellyseerr.test",
            "JELLYSEERR_API_KEY": "secret",
        }
        requests_data = [
            {
                "id": 101,
                "type": "movie",
                "status": 5,
                "media": {"mediaType": "movie", "tmdbId": 277},
                "requestedBy": {"displayName": "Roy"},
            },
            {
                "id": 102,
                "type": "tv",
                "status": 2,
                "media": {"mediaType": "tv", "tmdbId": 1234},
                "seasonRequests": [{"seasonNumber": 2}],
            },
        ]

        with patch(
            "services.latest_jellyseerr.get_jellyseerr_requests",
            return_value=(requests_data, True),
        ), patch(
            "services.latest_jellyseerr._ensure_db_backend",
            return_value=backend,
        ), patch(
            "services.requests_summary._summarize_requests_for_dashboard",
            side_effect=AssertionError("dashboard summary must not run"),
        ):
            data, status_code = refresh_latest_jellyseerr_requests(config)

        self.assertEqual(200, status_code)
        self.assertTrue(data["success"])
        self.assertEqual({"total": 2, "movies": 1, "tv": 1}, data["counts"])
        self.assertEqual(1, len(backend.saved))
        self.assertEqual(["101", "102"], [entry["request_id"] for entry in backend.saved[0]])

    def test_refresh_latest_jellyseerr_requests_skips_when_not_configured(self):
        backend = _Backend()

        with patch(
            "services.latest_jellyseerr.get_jellyseerr_requests",
            side_effect=AssertionError("Jellyseerr API must not be called"),
        ), patch(
            "services.latest_jellyseerr._ensure_db_backend",
            return_value=backend,
        ):
            data, status_code = refresh_latest_jellyseerr_requests({})

        self.assertEqual(200, status_code)
        self.assertFalse(data["success"])
        self.assertEqual("skipped", data["status"])
        self.assertEqual([], backend.saved)


if __name__ == "__main__":
    unittest.main()
