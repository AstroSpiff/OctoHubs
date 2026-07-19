"""Dashboard request overview behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from search.availability import is_request_available, normalize_request_availability
from services.requests_summary import _summarize_requests_for_dashboard


def _config() -> dict:
    return {
        "SEARCH_RULES": {
            "skip_available_content": True,
            "skip_unreleased_content": False,
        },
        "REQUEST_RULES": {},
    }


class RequestsSummaryTests(unittest.TestCase):
    def test_tv_request_with_all_requested_seasons_available_is_marked_available(self):
        request = {
            "id": 451,
            "type": "tv",
            "title": "CIA",
            "firstAirDate": "2026-01-01",
            "media": {"mediaType": "tv", "status": 3},
            "seasons": [
                {
                    "seasonNumber": 1,
                    "episodes": [
                        {"episodeNumber": 1, "status": 5},
                        {"episodeNumber": 2, "status": 5},
                    ],
                }
            ],
        }

        with patch("services.requests_summary._log_justwatch_status"), patch(
            "services.requests_summary.fetch_request_details",
            return_value=None,
        ):
            summary = _summarize_requests_for_dashboard(_config(), requests_data=[request])

        self.assertEqual(1, len(summary))
        self.assertTrue(summary[0]["is_available"])
        self.assertTrue(summary[0]["will_skip"])

    def test_tv_request_already_available_does_not_fetch_jellyseerr_details(self):
        request = {
            "id": 452,
            "type": "tv",
            "title": "Ready Show",
            "media": {"mediaType": "tv", "status": 5},
            "seasons": [{"seasonNumber": 1}],
        }

        with patch("services.requests_summary._log_justwatch_status"), patch(
            "services.requests_summary.fetch_request_details",
            side_effect=AssertionError("available requests should not fetch details"),
        ):
            summary = _summarize_requests_for_dashboard(_config(), requests_data=[request])

        self.assertEqual(1, len(summary))
        self.assertTrue(summary[0]["is_available"])
        self.assertTrue(summary[0]["will_skip"])

    def test_cached_summary_season_status_is_used_for_availability(self):
        request = {
            "id": 453,
            "media_type": "tv",
            "status": 3,
            "is_available": False,
            "season_status": [{"season": 1, "status": "available"}],
        }

        self.assertTrue(is_request_available(request))
        normalized = normalize_request_availability([request])
        self.assertTrue(normalized[0]["is_available"])
        self.assertFalse(request["is_available"])


if __name__ == "__main__":
    unittest.main()
