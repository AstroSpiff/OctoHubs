"""Latest publications DB cache merge behavior."""

from __future__ import annotations

import unittest

from emby_latest import db_cache
from emby_latest.db_cache import merge_cached_entry, merge_with_db


class _ExplicitCacheStorage:
    def __init__(self):
        self.calls = []

    def load_latest_cache(self, cache_kind):
        self.calls.append(("load_latest_cache", cache_kind))
        return {
            "payload": {
                "movies": [{"title": "Cached movie"}],
                "series": [],
                "errors": [],
            }
        }


class LatestDbCacheTests(unittest.TestCase):
    def test_load_cache_can_use_explicit_storage_without_global_backend(self):
        storage = _ExplicitCacheStorage()

        data = db_cache.load_cache("batch", db_storage=storage)

        self.assertEqual("Cached movie", data["payload"]["movies"][0]["title"])
        self.assertEqual([("load_latest_cache", "batch")], storage.calls)

    def test_merge_cached_entry_preserves_movie_rating_runtime_and_external_ratings(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "community_rating": None,
            "runtime_minutes": None,
            "imdb_rating": "",
            "metacritic_rating": "",
        }
        cached = {
            "community_rating": 8.4,
            "runtime_minutes": 126,
            "imdb_rating": "7.9",
            "metacritic_rating": "74",
        }

        merged = merge_cached_entry(entry, cached)

        self.assertEqual(8.4, merged["community_rating"])
        self.assertEqual(126, merged["runtime_minutes"])
        self.assertEqual("7.9", merged["imdb_rating"])
        self.assertEqual("74", merged["metacritic_rating"])

    def test_merge_cached_entry_keeps_supported_tmdb_logo_token(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
        }
        cached = {
            "overview": "Cached overview",
        }

        merged = merge_cached_entry(entry, cached)

        self.assertEqual(
            "https://image.tmdb.org/t/p/w500/logo.png",
            merged["tmdb_logo_url"],
        )

    def test_merge_with_db_replaces_matching_movie_batch_without_duplicate(self):
        db_payload = {
            "movies": [
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "batch_id": "batch-old",
                    "title": "Movie old",
                    "overview": "Cached old overview",
                },
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "batch_id": "batch-new",
                    "title": "Movie new",
                    "overview": "Cached new overview",
                },
            ],
            "series": [],
            "errors": [],
        }
        new_payload = {
            "movies": [
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "batch_id": "batch-old",
                    "title": "Movie old refreshed",
                    "overview": "",
                }
            ],
            "series": [],
            "errors": [],
        }

        merged = merge_with_db(new_payload, db_payload)

        self.assertEqual(2, len(merged["movies"]))
        self.assertEqual(
            ["batch-old", "batch-new"],
            [movie["batch_id"] for movie in merged["movies"]],
        )
        self.assertEqual("Movie old refreshed", merged["movies"][0]["title"])
        self.assertEqual("Cached old overview", merged["movies"][0]["overview"])

    def test_merge_with_db_replaces_matching_series_batch_without_duplicate(self):
        db_payload = {
            "movies": [],
            "series": [
                {
                    "server_id": "server-a",
                    "item_id": "series-1",
                    "batch_id": "batch-old",
                    "title": "Series old",
                    "overview": "Cached old overview",
                },
                {
                    "server_id": "server-a",
                    "item_id": "series-1",
                    "batch_id": "batch-new",
                    "title": "Series new",
                    "overview": "Cached new overview",
                },
            ],
            "errors": [],
        }
        new_payload = {
            "movies": [],
            "series": [
                {
                    "server_id": "server-a",
                    "item_id": "series-1",
                    "batch_id": "batch-old",
                    "title": "Series old refreshed",
                    "overview": "",
                }
            ],
            "errors": [],
        }

        merged = merge_with_db(new_payload, db_payload)

        self.assertEqual(2, len(merged["series"]))
        self.assertEqual(
            ["batch-old", "batch-new"],
            [series["batch_id"] for series in merged["series"]],
        )
        self.assertEqual("Series old refreshed", merged["series"][0]["title"])
        self.assertEqual("Cached old overview", merged["series"][0]["overview"])


if __name__ == "__main__":
    unittest.main()
