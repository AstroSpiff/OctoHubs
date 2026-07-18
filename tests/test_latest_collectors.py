"""Latest publications collector state behavior."""

from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import threading
import unittest
from unittest.mock import patch

from emby_latest.collectors import collect_entries


class _RecordingCache:
    def __init__(self, payload=None):
        self.payload = deepcopy(payload) if payload is not None else {"movies": [], "series": [], "errors": []}
        self.saved = []

    def load_cache(self, _mode):
        return {"payload": deepcopy(self.payload)}

    def save_cache(self, mode, payload, limit, per_server_limit):
        self.saved.append((mode, payload, limit, per_server_limit))

    def merge_with_db(self, new_payload, existing_payload):
        from emby_latest.db_cache import merge_with_db

        return merge_with_db(new_payload, existing_payload)


class _RecordingState:
    def __init__(self, state):
        self.state = deepcopy(state)
        self.saved = []

    def load_state(self):
        return deepcopy(self.state)

    def save_state(self, state):
        self.saved.append(deepcopy(state))
        self.state = deepcopy(state)


class LatestCollectorStateTests(unittest.TestCase):
    def test_collect_entries_reuses_enrichment_for_same_movie_across_servers(self):
        db_state = _RecordingState(
            {
                "server-a": {"movies": {"items": {}}, "series": {"items": {}}},
                "server-b": {"movies": {"items": {}}, "series": {"items": {}}},
            }
        )
        db_cache = _RecordingCache()
        config = {
            "DATABASE": {"ENABLED": True},
            "TMDB_API_KEY": "tmdb-key",
            "MDBLIST_API_KEYS": ["mdblist-key"],
            "TRAKT": {"CLIENT_ID": "trakt-client"},
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "name": "Server A"},
                    {"id": "server-b", "name": "Server B"},
                ]
            },
        }
        servers = [
            {"id": "server-a", "name": "Server A"},
            {"id": "server-b", "name": "Server B"},
        ]
        movie_a = {
            "Id": "movie-a",
            "Name": "Shared Movie",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-18T10:05:00+00:00",
            "ProviderIds": {"Imdb": "tt123"},
            "MediaSources": [{"Id": "source-a", "Path": "/a/shared.mkv", "Size": 1000}],
        }
        movie_b = {
            "Id": "movie-b",
            "Name": "Shared Movie",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-18T10:06:00+00:00",
            "ProviderIds": {"Imdb": "tt123"},
            "MediaSources": [{"Id": "source-b", "Path": "/b/shared.mkv", "Size": 2000}],
        }
        enrich_calls = []

        def fake_fetch(server, item_type, _limit, fields=None, **_kwargs):
            if item_type != "Movie":
                return [], None
            return [movie_a if server.get("id") == "server-a" else movie_b], None

        def fake_enrich(entry, _config, force_omdb=False, omdb_cache_hours=None):
            enrich_calls.append((entry.get("server_id"), entry.get("item_id")))
            enriched = dict(entry)
            enriched.update(
                {
                    "tmdb_id": "456",
                    "imdb_id": "tt123",
                    "tvdb_id": "tv123",
                    "tmdb_poster_url": "https://image.tmdb.org/poster.jpg",
                    "tmdb_backdrop_url": "https://image.tmdb.org/backdrop.jpg",
                    "tmdb_logo_url": "https://image.tmdb.org/logo.png",
                    "tmdb_banner_url": "https://image.tmdb.org/banner.jpg",
                    "tmdb_thumb_url": "https://image.tmdb.org/thumb.jpg",
                    "tmdb_rating": "7.6",
                    "tmdb_votes": "100",
                    "cast": ["Actor"],
                    "directors": ["Director"],
                    "imdb_rating": "7.9",
                    "imdb_votes": "2,000",
                    "trakt_rating": "7.8",
                    "trakt_votes": "1200",
                    "omdb_fetched_at": "2026-07-18T10:00:00+00:00",
                    "trakt_fetched_at": "2026-07-18T10:01:00+00:00",
                }
            )
            return enriched

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=servers), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                    "parallelism": {"server_workers": 1, "requests_per_server": 1},
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_items_by_signature",
            return_value=[],
        ), patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=([], None)), patch(
            "emby_latest.builders._resolve_emby_library_for_item",
            return_value=("lib-a", "Movies"),
        ), patch("emby_latest.collectors.enrich_entry_with_tmdb", side_effect=fake_enrich), patch(
            "emby_latest.collectors._sync_jellyseerr_to_db",
            return_value=None,
        ), patch("emby_latest.collectors._apply_jellyseerr_request_info", return_value=None):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                enrich=True,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertEqual(1, len(enrich_calls))
        self.assertEqual(2, len(payload["movies"]))
        for movie in payload["movies"]:
            self.assertEqual("456", movie["tmdb_id"])
            self.assertEqual("7.9", movie["imdb_rating"])
            self.assertEqual("7.8", movie["trakt_rating"])

    def test_collect_entries_fetches_latest_items_from_servers_concurrently(self):
        db_state = _RecordingState(
            {
                "server-a": {"movies": {"items": {}}, "series": {"items": {}}},
                "server-b": {"movies": {"items": {}}, "series": {"items": {}}},
            }
        )
        db_cache = _RecordingCache()
        config = {
            "DATABASE": {"ENABLED": True},
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "name": "Server A"},
                    {"id": "server-b", "name": "Server B"},
                ]
            },
        }
        servers = [
            {"id": "server-a", "name": "Server A"},
            {"id": "server-b", "name": "Server B"},
        ]
        movie_barrier = threading.Barrier(2)

        def fake_fetch(server, item_type, _limit, fields=None, **_kwargs):
            if item_type == "Movie":
                try:
                    movie_barrier.wait(timeout=0.5)
                except threading.BrokenBarrierError as exc:
                    raise AssertionError("Movie latest fetches did not run concurrently") from exc
            return [], None

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=servers), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                    "parallelism": {
                        "server_workers": 2,
                        "requests_per_server": 2,
                    },
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_latest_series_from_episodes",
            return_value=([], None),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                enrich=False,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertEqual([], payload["movies"])
        self.assertEqual([], payload["series"])

    def test_collect_entries_preserves_movie_notification_destinations(self):
        existing_destinations = {
            "bot-a:chat-a": {
                "bot_id": "bot-a",
                "chat_id": "chat-a",
                "notified_at": "2026-07-15T10:02:00+00:00",
            }
        }
        existing_publications = {
            "server-a:movie:20260715100000:20260715100000": {
                "notified": True,
                "notified_at": "2026-07-15T10:02:00+00:00",
                "notified_destinations": existing_destinations,
            }
        }
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {
                        "items": {
                            "tmdb:1": {
                                "item_id": "movie-1",
                                "signature": "tmdb:1",
                                "title": "Movie One",
                                "year": 2026,
                                "last_seen_at": "2026-07-15T10:00:00+00:00",
                                "media_source_keys": ["source-a"],
                                "notified": False,
                                "notified_at": "",
                                "notified_destinations": existing_destinations,
                                "notified_publications": existing_publications,
                            }
                        }
                    },
                    "series": {"items": {}},
                }
            }
        )
        db_cache = _RecordingCache()
        movie = {
            "Id": "movie-1",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-15T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-a",
                    "Path": "/media/movie-one.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        config = {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}

        def fake_fetch(_server, item_type, _limit, fields=None, **_kwargs):
            if item_type == "Movie":
                return [movie], None
            return [], None

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_items_by_signature",
            return_value=[],
        ), patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=([], None)), patch(
            "emby_latest.builders._resolve_emby_library_for_item",
            return_value=("lib-a", "Movies"),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                enrich=False,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertTrue(db_state.saved)
        saved_movie = db_state.saved[-1]["server-a"]["movies"]["items"]["tmdb:1"]
        self.assertEqual(existing_destinations, saved_movie.get("notified_destinations"))
        self.assertEqual(existing_publications, saved_movie.get("notified_publications"))

    def test_collect_entries_saves_mediainfo_state_for_movie_versions(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        movie = {
            "Id": "movie-1",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-15T10:05:00+00:00",
            "RunTimeTicks": 7_200_000_000,
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-a",
                    "Path": "/media/movie-one.mkv",
                    "RunTimeTicks": 7_200_000_000,
                    "Container": "mkv",
                    "Size": 1000,
                    "MediaStreams": [
                        {"Type": "Video", "Codec": "hevc", "Width": 3840, "Height": 2160},
                        {"Type": "Audio", "Codec": "aac", "Language": "ita", "Channels": 6},
                    ],
                }
            ],
        }
        config = {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}

        def fake_fetch(_server, item_type, _limit, fields=None, **_kwargs):
            if item_type == "Movie":
                return [movie], None
            return [], None

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_items_by_signature",
            return_value=[],
        ), patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=([], None)), patch(
            "emby_latest.builders._resolve_emby_library_for_item",
            return_value=("lib-a", "Movies"),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                enrich=False,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        change = payload["movies"][0]["changes"][0]
        self.assertTrue(change["mediainfo_available"])
        saved_movie = db_state.saved[-1]["server-a"]["movies"]["items"]["tmdb:1"]
        self.assertTrue(saved_movie["mediainfo_complete"])
        self.assertEqual(saved_movie["media_source_keys"], saved_movie["mediainfo_source_keys"])

    def test_incremental_collect_detects_new_movie_version_even_when_metadata_is_complete(self):
        existing_payload = {
            "movies": [
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "item_type": "Movie",
                    "title": "Movie One",
                    "overview": "Cached overview",
                    "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
                    "tmdb_rating": 8.0,
                    "tmdb_votes": 100,
                    "batch_id": "server-a:movie:20260715100000:20260715100000",
                    "changes": [],
                }
            ],
            "series": [],
            "errors": [],
        }
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {
                        "items": {
                            "tmdb:1": {
                                "item_id": "movie-1",
                                "signature": "tmdb:1",
                                "title": "Movie One",
                                "year": 2026,
                                "last_seen_at": "2026-07-15T10:00:00+00:00",
                                "media_source_keys": ["old-source-key"],
                                "mediainfo_complete": True,
                                "mediainfo_source_keys": ["old-source-key"],
                                "notified": True,
                                "notified_at": "2026-07-15T10:02:00+00:00",
                            }
                        }
                    },
                    "series": {"items": {}},
                }
            }
        )
        db_cache = _RecordingCache()
        movie = {
            "Id": "movie-1",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "RunTimeTicks": 7_200_000_000,
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/movie-one-new-version.mkv",
                    "RunTimeTicks": 7_200_000_000,
                    "Container": "mkv",
                    "Size": 2000,
                    "MediaStreams": [
                        {"Type": "Video", "Codec": "hevc", "Width": 3840, "Height": 2160},
                        {"Type": "Audio", "Codec": "aac", "Language": "ita", "Channels": 6},
                    ],
                }
            ],
        }
        config = {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}

        def fake_fetch(_server, item_type, _limit, fields=None, **_kwargs):
            if item_type == "Movie":
                return [movie], None
            return [], None

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_items_by_signature",
            return_value=[],
        ) as fetch_by_signature, patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=([], None)), patch(
            "emby_latest.builders._resolve_emby_library_for_item",
            return_value=("lib-a", "Movies"),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                skip_existing_complete=True,
                existing_db_payload=existing_payload,
                enrich=False,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        fetch_by_signature.assert_not_called()
        self.assertTrue(payload["movies"])
        movie_entry = next(
            movie
            for movie in payload["movies"]
            if movie.get("signature") == "tmdb:1" and movie.get("update_type") == "update"
        )
        self.assertEqual("update", movie_entry.get("update_type"))
        self.assertEqual("Nuova versione", movie_entry.get("update_label"))
        self.assertTrue(any(
            change.get("path") == "/media/movie-one-new-version.mkv"
            for change in (movie_entry.get("changes") or [])
        ))
        saved_movie = db_state.saved[-1]["server-a"]["movies"]["items"]["tmdb:1"]
        self.assertTrue(saved_movie["mediainfo_complete"])
        self.assertIn("old-source-key", saved_movie["mediainfo_source_keys"])
        self.assertEqual(set(saved_movie["media_source_keys"]), set(saved_movie["mediainfo_source_keys"]))

    def test_incremental_collect_passes_overlap_cutoff_from_state_to_emby_fetches(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {
                        "items": {
                            "tmdb:1": {
                                "item_id": "movie-1",
                                "signature": "tmdb:1",
                                "title": "Movie One",
                                "last_seen_at": "2026-07-16T10:00:00+00:00",
                                "media_source_keys": ["source-a"],
                            }
                        }
                    },
                    "series": {
                        "items": {
                            "series-1": {
                                "series_id": "series-1",
                                "title": "Series One",
                                "last_seen_at": "2026-07-16T09:30:00+00:00",
                                "episodes": {},
                            }
                        }
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        config = {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}
        fetch_calls = []

        def fake_fetch(_server, item_type, _limit, fields=None, **kwargs):
            fetch_calls.append((item_type, kwargs.get("stop_at")))
            return [], None

        with patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_latest_series_from_episodes",
            return_value=([], None),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ):
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                skip_existing_complete=True,
                existing_db_payload={"movies": [], "series": [], "errors": []},
                enrich=False,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertEqual({"movies": [], "series": [], "errors": []}, payload)
        self.assertEqual(
            [
                ("Movie", "2026-07-15T10:00:00+00:00"),
                ("Episode", "2026-07-15T09:30:00+00:00"),
            ],
            fetch_calls,
        )

    def test_collect_entries_skips_external_enrichment_for_complete_cached_entry(self):
        complete_movie = {
            "server_id": "server-a",
            "item_id": "movie-1",
            "signature": "tmdb:1",
            "item_type": "Movie",
            "title": "Movie One",
            "overview": "Cached overview",
            "tmdb_id": "1",
            "tmdb_poster_url": "https://image.tmdb.org/t/p/w780/poster.jpg",
            "tmdb_backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
            "tmdb_logo_url": "https://image.tmdb.org/t/p/w500/logo.png",
            "tmdb_banner_url": "https://image.tmdb.org/t/p/w1280/banner.jpg",
            "tmdb_thumb_url": "https://image.tmdb.org/t/p/w1280/thumb.jpg",
            "tmdb_rating": "8.0",
            "tmdb_votes": "100",
            "imdb_id": "tt123",
            "tvdb_id": "tv123",
            "imdb_rating": "7.8",
            "imdb_votes": "1,000",
            "metacritic_rating": "70",
            "cast": ["Actor"],
            "directors": ["Director"],
        }
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache({"movies": [complete_movie], "series": [], "errors": []})
        movie = {
            "Id": "movie-1",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-15T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1", "Imdb": "tt123", "Tvdb": "tv123"},
            "MediaSources": [
                {
                    "Id": "source-a",
                    "Path": "/media/movie-one.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        config = {
            "DATABASE": {"ENABLED": True},
            "TMDB_API_KEY": "tmdb-key",
            "MDBLIST_API_KEYS": ["mdblist-key"],
            "EMBY": {"SERVERS": [{"id": "server-a"}]},
        }

        def fake_fetch(_server, item_type, _limit, fields=None):
            if item_type == "Movie":
                return [movie], None
            return [], None

        output = io.StringIO()
        with redirect_stdout(output), patch("core.config_manager.load_config", return_value=(config, True)), patch(
            "core.config_manager._db_enabled",
            return_value=True,
        ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
            "emby_latest.collectors._load_latest_settings",
            return_value={
                "SETTINGS": {
                    "batch_gap_minutes": 180,
                    "max_movies": 10,
                    "max_series": 10,
                    "retention_days": 90,
                    "max_versions": 6,
                    "batch_fetch_limit": 100,
                }
            },
        ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
            "emby_latest.collectors._fetch_emby_items_by_signature",
            return_value=[],
        ), patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=([], None)), patch(
            "emby_latest.builders._resolve_emby_library_for_item",
            return_value=("lib-a", "Movies"),
        ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
            "emby_latest.collectors._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.collectors.enrich_entry_with_tmdb") as enrich_entry:
            payload, error = collect_entries(
                limit=10,
                per_server_limit=10,
                enrich=True,
                db_cache=db_cache,
                db_state=db_state,
            )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        enrich_entry.assert_not_called()
        self.assertIn("Arricchimento: 0 elementi da aggiornare su 1 totali", output.getvalue())


if __name__ == "__main__":
    unittest.main()
