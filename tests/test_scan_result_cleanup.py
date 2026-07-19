"""Scan result cleanup behavior."""

from __future__ import annotations

import unittest


class ScanResultCleanupTests(unittest.TestCase):
    def _payload(self):
        return {
            "generated_at": "2026-07-19T10:00:00+00:00",
            "checked_requests": 3,
            "found": 2,
            "items": [
                {
                    "request_id": "10",
                    "title": "Movie",
                    "media_type": "movie",
                    "season": None,
                    "results_found": 4,
                    "is_stale": False,
                },
                {
                    "request_id": "20",
                    "title": "Show",
                    "media_type": "tv",
                    "season": 1,
                    "results_found": 2,
                    "is_stale": True,
                },
                {
                    "request_id": "30",
                    "title": "Still Pending",
                    "media_type": "tv",
                    "season": 2,
                    "results_found": 0,
                    "is_stale": False,
                },
            ],
        }

    def test_cleanup_single_result_removes_only_matching_request_and_season(self):
        from services.scan_result_cleanup import clean_scan_results_payload

        result = clean_scan_results_payload(
            self._payload(),
            mode="single",
            request_id="20",
            season=1,
        )

        self.assertEqual(1, result["removed"])
        self.assertEqual(["10", "30"], [item["request_id"] for item in result["payload"]["items"]])
        self.assertEqual(1, result["payload"]["found"])
        self.assertEqual(2, result["payload"]["checked_requests"])
        self.assertEqual(0, result["payload"]["stale_count"])

    def test_cleanup_resolved_removes_available_request_ids(self):
        from services.scan_result_cleanup import clean_scan_results_payload

        result = clean_scan_results_payload(
            self._payload(),
            mode="resolved",
            available_ids={"10", "20"},
        )

        self.assertEqual(2, result["removed"])
        self.assertEqual(["30"], [item["request_id"] for item in result["payload"]["items"]])
        self.assertEqual(0, result["payload"]["found"])
        self.assertEqual(1, result["payload"]["checked_requests"])

    def test_cleanup_all_clears_visible_summary_payload(self):
        from services.scan_result_cleanup import clean_scan_results_payload

        result = clean_scan_results_payload(self._payload(), mode="all")

        self.assertEqual(3, result["removed"])
        self.assertEqual([], result["payload"]["items"])
        self.assertEqual(0, result["payload"]["found"])
        self.assertEqual(0, result["payload"]["checked_requests"])


if __name__ == "__main__":
    unittest.main()
