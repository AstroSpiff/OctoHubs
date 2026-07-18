"""Latest publications Emby API helpers."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from emby_latest import emby_api
from emby_latest.emby_api import (
    _fetch_emby_episode_items,
    _fetch_emby_latest_items,
    _fetch_emby_latest_series_from_episodes,
    _hydrate_media_source_item_dates,
)


class LatestEmbyApiTests(unittest.TestCase):
    def setUp(self):
        for cache_name in ("_EMBY_ITEM_CACHE", "_EMBY_USER_CACHE", "_EMBY_USER_ITEM_CACHE"):
            cache = getattr(emby_api, cache_name, None)
            if isinstance(cache, dict):
                cache.clear()

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

    def test_hydrate_media_source_item_dates_fetches_dates_in_one_items_batch(self):
        calls = []
        item = {
            "Id": "movie-1",
            "Name": "Movie One",
            "MediaSources": [
                {"Id": "mediasource_496007", "Path": "/media/movie-1080p.mkv"},
                {"Id": "mediasource_496008", "Path": "/media/movie-2160p.mkv"},
                {"Id": "mediasource_489411", "Path": "/media/movie-old.mkv"},
            ],
        }

        def fake_call(server, path, params=None, method="GET"):
            calls.append((server, path, params or {}, method))
            if path != "Items":
                return False, "unexpected path"
            return True, {
                "Items": [
                    {"Id": "496007", "DateCreated": "2026-07-16T13:03:01+00:00"},
                    {"Id": "496008", "DateCreated": "2026-07-16T13:03:01+00:00"},
                    {"Id": "489411", "DateCreated": "2026-06-14T03:27:22+00:00"},
                ]
            }

        with patch("emby_latest.emby_api._call_emby_api", fake_call):
            hydrated = _hydrate_media_source_item_dates({"id": "server-a"}, item)

        self.assertEqual(["Items"], [call[1] for call in calls])
        self.assertEqual("496007,496008,489411", calls[0][2].get("Ids"))
        self.assertEqual(3, calls[0][2].get("Limit"))
        self.assertEqual(
            [
                "2026-07-16T13:03:01+00:00",
                "2026-07-16T13:03:01+00:00",
                "2026-06-14T03:27:22+00:00",
            ],
            [source.get("DateCreated") for source in hydrated["MediaSources"]],
        )

    def test_fetch_latest_series_from_episodes_fetches_series_details_concurrently(self):
        barrier = threading.Barrier(2)
        calls = []
        episodes = [
            {
                "Id": "episode-1",
                "SeriesId": "series-1",
                "SeriesName": "Series One",
                "SeriesProductionYear": 2026,
                "DateCreated": "2026-07-18T10:00:00+00:00",
            },
            {
                "Id": "episode-2",
                "SeriesId": "series-2",
                "SeriesName": "Series Two",
                "SeriesProductionYear": 2026,
                "DateCreated": "2026-07-18T10:01:00+00:00",
            },
        ]

        def fake_call(server, path, params=None, method="GET"):
            calls.append(path)
            if path.startswith("Items/series-"):
                try:
                    barrier.wait(timeout=0.5)
                except threading.BrokenBarrierError as exc:
                    raise AssertionError("Series detail fetches did not run concurrently") from exc
                series_id = path.split("/", 1)[1]
                return True, {"Id": series_id, "Name": series_id.title(), "Type": "Series"}
            return False, "Unexpected Emby API call"

        with patch("emby_latest.emby_api._call_emby_api", fake_call):
            entries, error = _fetch_emby_latest_series_from_episodes(
                {"id": "server-a"},
                2,
                episodes=episodes,
                parallel_workers=2,
            )

        self.assertIsNone(error)
        self.assertEqual(["series-1", "series-2"], [entry["Id"] for entry in entries])
        self.assertEqual(2, len([path for path in calls if path.startswith("Items/series-")]))


if __name__ == "__main__":
    unittest.main()
