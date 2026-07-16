"""Latest publications enrichment selectivity."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from emby_latest.enrichment import enrich_entry_with_tmdb, entry_needs_enrichment, has_missing_data


class LatestEnrichmentTests(unittest.TestCase):
    def test_enrich_fetches_tmdb_when_only_supported_image_field_is_missing(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_tmdb_images",
            return_value={
                "tmdb_poster_url": "",
                "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            },
        ) as fetch_tmdb, patch(
            "emby_latest.enrichment_sources._fetch_mdblist_ratings_by_imdb",
            return_value={},
        ) as fetch_mdblist, patch(
            "emby_latest.enrichment_sources._fetch_omdb_ratings",
            return_value={},
        ) as fetch_omdb, patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(entry, {"TMDB_API_KEY": "tmdb-key"})

        fetch_tmdb.assert_called_once()
        fetch_mdblist.assert_not_called()
        fetch_omdb.assert_not_called()
        fetch_trakt.assert_not_called()
        self.assertEqual("https://image.tmdb.org/t/p/w500/logo.png", enriched["tmdb_logo_url"])
        self.assertEqual("https://image.tmdb.org/t/p/w780/poster.jpg", enriched["tmdb_poster_url"])

    def test_enrich_series_uses_existing_imdb_id_for_missing_ratings_without_tmdb_fetch(self):
        entry = {
            "item_type": "Series",
            "title": "Series",
            "tmdb_id": "123",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
            "creators": ["Creator"],
            "imdb_rating": "",
            "imdb_votes": "",
            "metacritic_rating": "",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_tmdb_images",
            return_value={},
        ) as fetch_tmdb, patch(
            "emby_latest.enrichment_sources._fetch_mdblist_tv_series_with_seasons",
            return_value={"imdb_rating": "7.8", "imdb_votes": "1,000", "metacritic_rating": "70"},
        ) as fetch_mdblist, patch(
            "emby_latest.enrichment_sources._fetch_omdb_ratings",
            return_value={},
        ) as fetch_omdb, patch(
            "emby_latest.enrichment_sources._fetch_omdb_series_by_title",
            return_value={},
        ) as fetch_omdb_title, patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(entry, {"MDBLIST_API_KEYS": ["mdblist-key"]})

        fetch_tmdb.assert_not_called()
        fetch_mdblist.assert_called_once_with("tt123", ["mdblist-key"])
        fetch_omdb.assert_not_called()
        fetch_omdb_title.assert_not_called()
        fetch_trakt.assert_not_called()
        self.assertEqual("7.8", enriched["imdb_rating"])
        self.assertEqual("1,000", enriched["imdb_votes"])
        self.assertEqual("70", enriched["metacritic_rating"])

    def test_entry_needs_enrichment_ignores_absent_audio_language_fields(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
            "cast": ["Actor"],
            "directors": ["Director"],
            "imdb_rating": "7.5",
            "imdb_votes": "1,000",
            "metacritic_rating": "70",
            "trakt_rating": "7.8",
            "trakt_votes": "1000",
            "audio_ita": "Italiano AAC 5.1",
            "audio_eng": "",
            "audio_fra": "",
            "audio_spa": "",
            "audio_ger": "",
            "audio_jpn": "",
            "audio_langs": ["ita"],
        }

        self.assertFalse(
            entry_needs_enrichment(
                entry,
                {
                    "TMDB_API_KEY": "tmdb-key",
                    "MDBLIST_API_KEYS": ["mdblist-key"],
                    "TRAKT": {"CLIENT_ID": "trakt-client"},
                },
            )
        )

    def test_enrich_fetches_only_trakt_when_only_trakt_fields_are_missing(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
            "cast": ["Actor"],
            "directors": ["Director"],
            "imdb_rating": "7.5",
            "imdb_votes": "1,000",
            "metacritic_rating": "70",
            "trakt_rating": "",
            "trakt_votes": "",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_tmdb_images",
            return_value={},
        ) as fetch_tmdb, patch(
            "emby_latest.enrichment_sources._fetch_mdblist_ratings_by_imdb",
            return_value={},
        ) as fetch_mdblist, patch(
            "emby_latest.enrichment_sources._fetch_omdb_ratings",
            return_value={},
        ) as fetch_omdb, patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={"trakt_rating": "7.9", "trakt_votes": "2000"},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(
                entry,
                {
                    "TMDB_API_KEY": "tmdb-key",
                    "MDBLIST_API_KEYS": ["mdblist-key"],
                    "TRAKT": {"CLIENT_ID": "trakt-client"},
                },
            )

        fetch_tmdb.assert_not_called()
        fetch_mdblist.assert_not_called()
        fetch_omdb.assert_not_called()
        fetch_trakt.assert_called_once()
        self.assertEqual("7.9", enriched["trakt_rating"])
        self.assertEqual("2000", enriched["trakt_votes"])

    def test_enrich_records_trakt_fetch_even_when_no_rating_is_found(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "imdb_id": "tt123",
            "trakt_rating": "",
            "trakt_votes": "",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(entry, {"TRAKT": {"CLIENT_ID": "trakt-client"}})

        fetch_trakt.assert_called_once()
        self.assertTrue(enriched.get("trakt_fetched_at"))

    def test_entry_needs_enrichment_skips_recent_empty_trakt_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "trakt_rating": "",
            "trakt_votes": "",
            "trakt_fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        self.assertFalse(
            entry_needs_enrichment(
                entry,
                {"TRAKT": {"CLIENT_ID": "trakt-client"}},
                omdb_cache_hours=24,
            )
        )

    def test_enrich_skips_recent_empty_trakt_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "imdb_id": "tt123",
            "trakt_rating": "",
            "trakt_votes": "",
            "trakt_fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={"trakt_rating": "7.9", "trakt_votes": "2000"},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(
                entry,
                {"TRAKT": {"CLIENT_ID": "trakt-client"}},
                omdb_cache_hours=24,
            )

        fetch_trakt.assert_not_called()
        self.assertEqual("", enriched["trakt_rating"])
        self.assertEqual("", enriched["trakt_votes"])

    def test_entry_needs_enrichment_skips_verified_empty_trakt_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "trakt_rating": "",
            "trakt_votes": "",
            "trakt_fetched_at": "2025-01-01T00:00:00+00:00",
        }

        self.assertFalse(
            entry_needs_enrichment(
                entry,
                {"TRAKT": {"CLIENT_ID": "trakt-client"}},
                omdb_cache_hours=24,
            )
        )

    def test_enrich_skips_verified_empty_trakt_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "imdb_id": "tt123",
            "trakt_rating": "",
            "trakt_votes": "",
            "trakt_fetched_at": "2025-01-01T00:00:00+00:00",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_trakt_rating",
            return_value={"trakt_rating": "7.9", "trakt_votes": "2000"},
        ) as fetch_trakt:
            enriched = enrich_entry_with_tmdb(
                entry,
                {"TRAKT": {"CLIENT_ID": "trakt-client"}},
                omdb_cache_hours=24,
            )

        fetch_trakt.assert_not_called()
        self.assertEqual("", enriched["trakt_rating"])
        self.assertEqual("", enriched["trakt_votes"])

    def test_entry_needs_enrichment_skips_verified_empty_rating_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
            "cast": ["Actor"],
            "directors": ["Director"],
            "imdb_rating": "",
            "imdb_votes": "",
            "metacritic_rating": "",
            "omdb_fetched_at": "2025-01-01T00:00:00+00:00",
        }

        self.assertFalse(
            entry_needs_enrichment(
                entry,
                {"MDBLIST_API_KEYS": ["mdblist-key"], "OMDB_API_KEY": "omdb-key"},
                omdb_cache_hours=24,
            )
        )
        self.assertFalse(has_missing_data(entry, omdb_enabled=True, cache_hours=24))

    def test_enrich_skips_verified_empty_rating_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "imdb_id": "tt123",
            "imdb_rating": "",
            "imdb_votes": "",
            "metacritic_rating": "",
            "omdb_fetched_at": "2025-01-01T00:00:00+00:00",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_mdblist_ratings_by_imdb",
            return_value={"imdb_rating": "7.9", "imdb_votes": "2,000"},
        ) as fetch_mdblist, patch(
            "emby_latest.enrichment_sources._fetch_omdb_ratings",
            return_value={"imdb_rating": "8.1", "imdb_votes": "3,000"},
        ) as fetch_omdb:
            enriched = enrich_entry_with_tmdb(
                entry,
                {"MDBLIST_API_KEYS": ["mdblist-key"], "OMDB_API_KEY": "omdb-key"},
                omdb_cache_hours=24,
            )

        fetch_mdblist.assert_not_called()
        fetch_omdb.assert_not_called()
        self.assertEqual("", enriched["imdb_rating"])
        self.assertEqual("", enriched["imdb_votes"])

    def test_force_omdb_refreshes_verified_rating_lookup(self):
        entry = {
            "item_type": "Movie",
            "title": "Movie",
            "tmdb_id": "123",
            "imdb_id": "tt123",
            "imdb_rating": "",
            "imdb_votes": "",
            "metacritic_rating": "",
            "omdb_fetched_at": "2025-01-01T00:00:00+00:00",
        }

        with patch(
            "emby_latest.enrichment_sources._fetch_mdblist_ratings_by_imdb",
            return_value={"imdb_rating": "7.9", "imdb_votes": "2,000"},
        ) as fetch_mdblist:
            enriched = enrich_entry_with_tmdb(
                entry,
                {"MDBLIST_API_KEYS": ["mdblist-key"]},
                force_omdb=True,
                omdb_cache_hours=24,
            )

        fetch_mdblist.assert_called_once()
        self.assertEqual("7.9", enriched["imdb_rating"])
        self.assertEqual("2,000", enriched["imdb_votes"])


if __name__ == "__main__":
    unittest.main()
