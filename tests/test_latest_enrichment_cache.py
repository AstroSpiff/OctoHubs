"""Shared Latest enrichment cache behavior."""

from __future__ import annotations

import unittest

from emby_latest.enrichment_cache import SharedEnrichmentCache


class SharedEnrichmentCacheTests(unittest.TestCase):
    def test_applies_cached_common_fields_across_servers_by_imdb(self):
        cache = SharedEnrichmentCache(
            [
                {
                    "server_id": "server-a",
                    "item_type": "Movie",
                    "title": "Movie",
                    "year": 2026,
                    "imdb_id": "tt123",
                    "tmdb_id": "456",
                    "imdb_rating": "7.9",
                    "imdb_votes": "2,000",
                    "metacritic_rating": "71",
                    "trakt_rating": "7.8",
                    "trakt_votes": "1200",
                    "tmdb_poster_url": "https://image.tmdb.org/poster.jpg",
                    "omdb_fetched_at": "2026-07-18T10:00:00+00:00",
                    "trakt_fetched_at": "2026-07-18T10:01:00+00:00",
                    "library_name": "Movies A",
                    "server_name": "A",
                }
            ]
        )
        entry = {
            "server_id": "server-b",
            "item_type": "Movie",
            "title": "Movie",
            "year": 2026,
            "imdb_id": "tt123",
            "imdb_rating": "",
            "trakt_rating": "",
            "library_name": "Movies B",
            "server_name": "B",
        }

        cache.apply(entry)

        self.assertEqual("456", entry["tmdb_id"])
        self.assertEqual("7.9", entry["imdb_rating"])
        self.assertEqual("2,000", entry["imdb_votes"])
        self.assertEqual("71", entry["metacritic_rating"])
        self.assertEqual("7.8", entry["trakt_rating"])
        self.assertEqual("1200", entry["trakt_votes"])
        self.assertEqual("2026-07-18T10:00:00+00:00", entry["omdb_fetched_at"])
        self.assertEqual("2026-07-18T10:01:00+00:00", entry["trakt_fetched_at"])
        self.assertEqual("Movies B", entry["library_name"])
        self.assertEqual("B", entry["server_name"])

    def test_learns_resolved_ids_for_later_title_year_duplicate(self):
        cache = SharedEnrichmentCache()
        first = {
            "server_id": "server-a",
            "item_type": "Movie",
            "title": "Movie",
            "year": 2026,
            "tmdb_id": "456",
            "imdb_id": "tt123",
            "imdb_rating": "7.9",
            "omdb_fetched_at": "2026-07-18T10:00:00+00:00",
        }
        second = {
            "server_id": "server-b",
            "item_type": "Movie",
            "title": "Movie",
            "year": 2026,
            "tmdb_id": "",
            "imdb_id": "",
            "imdb_rating": "",
        }

        cache.remember(first)
        cache.apply(second)

        self.assertEqual("456", second["tmdb_id"])
        self.assertEqual("tt123", second["imdb_id"])
        self.assertEqual("7.9", second["imdb_rating"])
        self.assertEqual("2026-07-18T10:00:00+00:00", second["omdb_fetched_at"])


if __name__ == "__main__":
    unittest.main()
