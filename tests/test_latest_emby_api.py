"""Latest publications Emby API helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_latest.emby_api import _fetch_emby_episode_items, _fetch_emby_latest_items


class LatestEmbyApiTests(unittest.TestCase):
    def test_fetch_emby_episode_items_uses_series_episode_endpoint_and_filters_episode(self):
        calls = []

        def fake_call(server, path, params=None, method="GET"):
            calls.append((server, path, params or {}, method))
            return True, {
                "Items": [
                    {
                        "Id": "episode-6-a",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 6,
                    },
                    {
                        "Id": "episode-14",
                        "ParentIndexNumber": 1,
                        "IndexNumber": 14,
                    },
                    {
                        "Id": "episode-6-season-2",
                        "ParentIndexNumber": 2,
                        "IndexNumber": 6,
                    },
                    {
                        "Id": "episode-6-b",
                        "ParentIndexNumber": "1",
                        "IndexNumber": "6",
                    },
                ]
            }

        with patch("emby_latest.emby_api._call_emby_api", fake_call):
            items = _fetch_emby_episode_items({"id": "server-a"}, "series-1", 1, 6)

        self.assertEqual(["episode-6-a", "episode-6-b"], [item["Id"] for item in items])
        self.assertEqual("Shows/series-1/Episodes", calls[0][1])
        self.assertEqual(1, calls[0][2].get("Season"))

    def test_fetch_emby_latest_items_pages_until_stop_at_overlap_cutoff(self):
        calls = []
        pages = {
            0: [
                {"Id": "new-1", "DateCreated": "2026-07-16T10:00:00+00:00"},
                {"Id": "new-2", "DateCreated": "2026-07-16T09:00:00+00:00"},
            ],
            2: [
                {"Id": "overlap-edge", "DateCreated": "2026-07-15T10:00:00+00:00"},
                {"Id": "older", "DateCreated": "2026-07-15T09:59:59+00:00"},
            ],
        }

        def fake_call(server, path, params=None, method="GET"):
            calls.append((server, path, params or {}, method))
            start_index = int((params or {}).get("StartIndex") or 0)
            return True, {"Items": pages.get(start_index, [])}

        with patch("emby_latest.emby_api._call_emby_api", fake_call):
            items, error = _fetch_emby_latest_items(
                {"id": "server-a"},
                "Movie",
                10,
                stop_at="2026-07-15T10:00:00+00:00",
                page_size=2,
            )

        self.assertIsNone(error)
        self.assertEqual(["new-1", "new-2", "overlap-edge"], [item["Id"] for item in items])
        self.assertEqual([0, 2], [call[2].get("StartIndex") for call in calls])
        self.assertEqual([2, 2], [call[2].get("Limit") for call in calls])


if __name__ == "__main__":
    unittest.main()
