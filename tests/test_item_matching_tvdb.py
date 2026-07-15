from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_users.api_client_items import _fetch_emby_items_by_provider_ids
from emby_users.item_matching import get_item_sync_keys, is_provider_key


def _episode_with_series_tvdb() -> dict:
    return {
        "Id": "episode-source",
        "Name": "Episode 2",
        "SeriesName": "Shared Series",
        "Type": "Episode",
        "ParentIndexNumber": 1,
        "IndexNumber": 2,
        "ProviderIds": {},
        "SeriesProviderIds": {"Tvdb": "777"},
        "UserData": {"Played": True},
    }


def _episode_with_series_tmdb_and_tvdb() -> dict:
    item = _episode_with_series_tvdb()
    item["SeriesProviderIds"] = {"Tmdb": "12345", "Tvdb": "777", "Imdb": "tt999"}
    return item


class ItemMatchingTvdbTests(unittest.TestCase):
    def test_episode_with_series_tmdb_prefers_tmdb_over_tvdb_aliases(self):
        keys = get_item_sync_keys(_episode_with_series_tmdb_and_tvdb())

        self.assertEqual(["series-tmdb:12345:s1:e2"], keys)
        self.assertTrue(is_provider_key(keys[0]))

    def test_episode_with_series_tvdb_gets_provider_sync_key(self):
        keys = get_item_sync_keys(_episode_with_series_tvdb())

        self.assertEqual(["series-tvdb:777:s1:e2"], keys)
        self.assertTrue(is_provider_key(keys[0]))

    def test_series_with_tmdb_prefers_tmdb_over_tvdb_aliases(self):
        keys = get_item_sync_keys(
            {
                "Id": "series-source",
                "Name": "Shared Series",
                "Type": "Series",
                "ProviderIds": {"Tmdb": "12345", "Tvdb": "777", "Imdb": "tt999"},
            }
        )

        self.assertEqual(["tmdb:12345"], keys)
        self.assertTrue(is_provider_key(keys[0]))

    def test_series_with_tvdb_gets_provider_sync_key(self):
        keys = get_item_sync_keys(
            {
                "Id": "series-source",
                "Name": "Shared Series",
                "Type": "Series",
                "ProviderIds": {"Tvdb": "777"},
            }
        )

        self.assertEqual(["tvdb:777"], keys)
        self.assertTrue(is_provider_key(keys[0]))

    def test_provider_lookup_resolves_tvdb_series_episode_on_target(self):
        calls = []

        def fake_call(_server, path, method="GET", params=None, json_payload=None):
            params = params or {}
            calls.append((path, dict(params)))
            if (
                path == "Users/target-user/Items"
                and params.get("IncludeItemTypes") == "Series"
                and params.get("AnyProviderIdEquals") == "tvdb.777"
            ):
                return True, {
                    "Items": [{"Id": "target-series", "Name": "Shared Series", "Type": "Series"}],
                    "TotalRecordCount": 1,
                }
            if path == "Shows/target-series/Episodes":
                return True, {
                    "Items": [
                        {
                            "Id": "target-episode",
                            "Name": "Episode 2",
                            "SeriesName": "Shared Series",
                            "Type": "Episode",
                            "ParentIndexNumber": 1,
                            "IndexNumber": 2,
                            "ProviderIds": {},
                            "UserData": {"Played": False},
                        }
                    ]
                }
            return True, {"Items": [], "TotalRecordCount": 0}

        with patch("emby_users.api_client_items._call_emby_api", fake_call):
            items, err = _fetch_emby_items_by_provider_ids(
                {"id": "target"},
                "target-user",
                ["series-tvdb:777:s1:e2"],
                include_played=True,
            )

        self.assertIsNone(err)
        self.assertEqual(["target-episode"], [item["Id"] for item in items])
        self.assertEqual({"tvdb": "777"}, items[0].get("SeriesProviderIds"))
        self.assertIn(
            (
                "Users/target-user/Items",
                {
                    "Recursive": "true",
                    "Fields": "ProviderIds,Name,SortName",
                    "IncludeItemTypes": "Series",
                    "AnyProviderIdEquals": "tvdb.777",
                    "StartIndex": 0,
                    "Limit": 200,
                },
            ),
            calls,
        )


if __name__ == "__main__":
    unittest.main()
