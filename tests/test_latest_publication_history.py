"""Latest publications historical classification behavior."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from core.utils import _parse_date_value
from emby_latest.collectors import collect_entries
from emby_latest.notifications import send_notifications
from emby_latest.publication_history import notification_snapshot, update_history_entry


class _RecordingCache:
    def __init__(self, payload=None):
        self.payload = deepcopy(payload) if payload is not None else {"movies": [], "series": [], "errors": []}
        self.saved = []

    def load_cache(self, _mode):
        return {"payload": deepcopy(self.payload)}

    def save_cache(self, mode, payload, limit, per_server_limit):
        self.saved.append((mode, deepcopy(payload), limit, per_server_limit))

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


def _latest_settings():
    return {
        "SETTINGS": {
            "batch_gap_minutes": 180,
            "max_movies": 10,
            "max_series": 10,
            "retention_days": 90,
            "max_versions": 6,
            "batch_fetch_limit": 100,
        }
    }


def _base_config():
    return {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}


def _collect_with_mocks(
    db_state,
    db_cache,
    movie_items=None,
    movie_catalog_items=None,
    episode_items=None,
    series_entries=None,
    episode_catalog_items=None,
):
    movie_items = list(movie_items or [])
    movie_catalog_items = list(movie_catalog_items or [])
    episode_items = list(episode_items or [])
    series_entries = list(series_entries or [])
    episode_catalog_items = list(episode_catalog_items or [])

    def fake_fetch(_server, item_type, _limit, fields=None):
        if item_type == "Movie":
            return movie_items, None
        if item_type == "Episode":
            return episode_items, None
        return [], None

    with patch("core.config_manager.load_config", return_value=(_base_config(), True)), patch(
        "core.config_manager._db_enabled",
        return_value=True,
    ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
        "emby_latest.collectors._load_latest_settings",
        return_value=_latest_settings(),
    ), patch("emby_latest.collectors._fetch_emby_latest_items", side_effect=fake_fetch), patch(
        "emby_latest.collectors._fetch_emby_items_by_signature",
        return_value=movie_catalog_items,
    ), patch(
        "emby_latest.collectors._fetch_emby_episode_items",
        return_value=episode_catalog_items,
    ), patch("emby_latest.collectors._fetch_emby_latest_series_from_episodes", return_value=(series_entries, None)), patch(
        "emby_latest.collectors._fetch_emby_oldest_episode_date",
        return_value=_parse_date_value("2026-06-01T10:00:00+00:00"),
    ), patch(
        "emby_latest.builders._resolve_emby_library_for_item",
        return_value=("lib-a", "Library"),
    ), patch("emby_latest.collectors._sync_jellyseerr_to_db", return_value=None), patch(
        "emby_latest.collectors._apply_jellyseerr_request_info",
        return_value=None,
    ):
        return collect_entries(
            limit=10,
            per_server_limit=10,
            enrich=False,
            db_cache=db_cache,
            db_state=db_state,
        )


class LatestPublicationHistoryTests(unittest.TestCase):
    def test_notification_snapshot_prefers_completed_notification_over_partial_state(self):
        partial = {
            "notified": False,
            "notified_destinations": {
                "bot-a:chat-a": {
                    "bot_id": "bot-a",
                    "chat_id": "chat-a",
                    "notified_at": "2026-07-16T10:00:00+00:00",
                }
            },
        }
        completed = {
            "notified": True,
            "notified_at": "2026-07-16T10:05:00+00:00",
            "notified_destinations": {
                "bot-a:chat-a": {
                    "bot_id": "bot-a",
                    "chat_id": "chat-a",
                    "notified_at": "2026-07-16T10:00:00+00:00",
                },
                "bot-b:chat-b": {
                    "bot_id": "bot-b",
                    "chat_id": "chat-b",
                    "notified_at": "2026-07-16T10:05:00+00:00",
                },
            },
        }

        snapshot = notification_snapshot(partial, completed)

        self.assertTrue(snapshot["notified"])
        self.assertEqual("2026-07-16T10:05:00+00:00", snapshot["notified_at"])

    def test_history_entry_merges_series_seasons(self):
        history = {"series": {"series-1": {"seasons": [1, 2]}}}

        update_history_entry(history, "series", "series-1", {"seasons": [2, 3]})

        self.assertEqual([1, 2, 3], history["series"]["series-1"]["seasons"])

    def test_movie_history_classifies_pruned_notified_item_as_new_version(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "movies": {
                            "tmdb:1": {
                                "item_id": "movie-1",
                                "signature": "tmdb:1",
                                "media_source_keys": ["old-version-key"],
                                "notified": True,
                                "notified_at": "2026-06-15T10:00:00+00:00",
                            }
                        }
                    },
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
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/movie-one-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }

        payload, error = _collect_with_mocks(db_state, db_cache, movie_items=[movie])

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual("new_version", payload["movies"][0]["changes"][0].get("kind"))
        saved_history = db_state.saved[-1]["server-a"]["history"]["movies"]["tmdb:1"]
        self.assertTrue(saved_history["notified"])
        self.assertIn("old-version-key", saved_history["media_source_keys"])
        self.assertGreaterEqual(len(saved_history["media_source_keys"]), 2)

    def test_movie_catalog_baseline_classifies_first_seen_existing_emby_movie_as_new_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1-new",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/movie-one-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        old_movie = {
            "Id": "movie-1-old",
            "Name": "Movie One",
            "Type": "Movie",
            "ProductionYear": 2026,
            "DateCreated": "2026-06-01T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-old",
                    "Path": "/media/movie-one-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie],
            movie_catalog_items=[current_movie, old_movie],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual("new_version", payload["movies"][0]["changes"][0].get("kind"))

    def test_movie_with_old_and_new_versions_in_latest_batch_is_new_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1-new",
            "Name": "Malvagi",
            "Type": "Movie",
            "ProductionYear": 2019,
            "DateCreated": "2026-07-08T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/malvagi-1080p-new.mkv",
                    "Container": "mkv",
                    "Size": 7220000000,
                }
            ],
        }
        old_movie = {
            "Id": "movie-1-old",
            "Name": "Malvagi",
            "Type": "Movie",
            "ProductionYear": 2019,
            "DateCreated": "2025-11-09T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-old",
                    "Path": "/media/malvagi-1080p-old.mkv",
                    "Container": "mkv",
                    "Size": 8140000000,
                }
            ],
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie, old_movie],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual(["/media/malvagi-1080p-new.mkv"], [change.get("path") for change in payload["movies"][0]["changes"]])

    def test_movie_with_old_and_new_media_sources_on_same_emby_item_is_new_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Underworld: La ribellione dei Lycans",
            "Type": "Movie",
            "ProductionYear": 2009,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "12437"},
            "MediaSources": [
                {
                    "Id": "source-1080",
                    "Path": "/media/underworld-rise-of-the-lycans-1080p.mkv",
                    "Container": "mkv",
                    "Size": 12510000000,
                    "DateCreated": "2026-07-16T10:05:00+00:00",
                    "Video3DFormat": None,
                },
                {
                    "Id": "source-2160",
                    "Path": "/media/underworld-rise-of-the-lycans-2160p.mkv",
                    "Container": "mkv",
                    "Size": 23720000000,
                    "DateCreated": "2026-07-16T10:07:00+00:00",
                    "Video3DFormat": None,
                },
                {
                    "Id": "source-720",
                    "Path": "/media/underworld-rise-of-the-lycans-720p.mkv",
                    "Container": "mkv",
                    "Size": 1700000000,
                    "DateCreated": "2025-11-09T10:05:00+00:00",
                    "Video3DFormat": None,
                },
            ],
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie],
            movie_catalog_items=[current_movie],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual(
            {
                "/media/underworld-rise-of-the-lycans-1080p.mkv",
                "/media/underworld-rise-of-the-lycans-2160p.mkv",
            },
            {change.get("path") for change in payload["movies"][0]["changes"]},
        )

    def test_episode_history_classifies_pruned_notified_episode_as_new_version(self):
        episode_key = "series-1:S1:E2"
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "series": {
                            "series-1": {
                                "series_id": "series-1",
                                "seasons": [1],
                                "notified": True,
                                "notified_at": "2026-06-15T10:00:00+00:00",
                            }
                        },
                        "episodes": {
                            episode_key: {
                                "series_id": "series-1",
                                "season": 1,
                                "episode": 2,
                                "media_source_keys": ["old-episode-key"],
                                "notified": True,
                                "notified_at": "2026-06-15T10:00:00+00:00",
                            }
                        },
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        episode = {
            "Id": "episode-2",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/series-one/s01e02-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[episode],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual("new_version", payload["series"][0]["changes"][0].get("kind"))
        saved_history = db_state.saved[-1]["server-a"]["history"]["episodes"][episode_key]
        self.assertTrue(saved_history["notified"])
        self.assertIn("old-episode-key", saved_history["media_source_keys"])
        self.assertGreaterEqual(len(saved_history["media_source_keys"]), 2)

    def test_unnotified_existing_episode_keeps_new_episode_classification_for_new_versions(self):
        episode_key = "series-1:S1:E2"
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {
                        "items": {
                            "series-1": {
                                "series_id": "series-1",
                                "item_id": "series-1",
                                "title": "Series One",
                                "seasons": [1],
                                "episodes": {
                                    episode_key: {
                                        "season": 1,
                                        "episode": 2,
                                        "media_source_keys": ["old-episode-key"],
                                        "notified": False,
                                    }
                                },
                                "notified": False,
                                "notified_at": "",
                            }
                        }
                    },
                    "history": {
                        "episodes": {
                            episode_key: {
                                "series_id": "series-1",
                                "season": 1,
                                "episode": 2,
                                "media_source_keys": ["old-episode-key"],
                                "notified": False,
                            }
                        }
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        episode = {
            "Id": "episode-2",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/series-one/s01e02-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[episode],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuovi episodi", payload["series"][0].get("update_label"))
        self.assertEqual("new_episode", payload["series"][0]["changes"][0].get("kind"))

    def test_episode_catalog_baseline_classifies_first_seen_existing_emby_episode_as_new_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-2-new",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-new",
                    "Path": "/media/series-one/s01e02-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        old_episode = {
            "Id": "episode-2-old",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-06-01T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-old",
                    "Path": "/media/series-one/s01e02-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode, old_episode],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual("new_version", payload["series"][0]["changes"][0].get("kind"))

    def test_episode_with_old_and_new_media_sources_on_same_emby_item_is_new_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-2",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e02-1080",
                    "Path": "/media/series-one/s01e02-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                    "DateCreated": "2026-07-16T10:05:00+00:00",
                },
                {
                    "Id": "source-s01e02-2160",
                    "Path": "/media/series-one/s01e02-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                    "DateCreated": "2026-07-16T10:07:00+00:00",
                },
                {
                    "Id": "source-s01e02-720",
                    "Path": "/media/series-one/s01e02-720p.mkv",
                    "Container": "mkv",
                    "Size": 700,
                    "DateCreated": "2025-11-09T10:05:00+00:00",
                },
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["series"][0]["changes"]])
        self.assertEqual(
            {
                "/media/series-one/s01e02-1080p.mkv",
                "/media/series-one/s01e02-2160p.mkv",
            },
            {change.get("path") for change in payload["series"][0]["changes"]},
        )

    def test_episode_catalog_baseline_keeps_older_versions_as_new_episode(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-3-1080",
            "Name": "Episode Three",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 3,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e03-1080",
                    "Path": "/media/series-one/s01e03-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        older_episode_version = {
            "Id": "episode-3-2160",
            "Name": "Episode Three",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 3,
            "DateCreated": "2026-06-30T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e03-2160",
                    "Path": "/media/series-one/s01e03-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode, older_episode_version],
            series_entries=[series],
        )

        self.assertIsNone(error)
        labels_by_path = {
            change.get("path"): (entry.get("update_label"), change.get("kind"))
            for entry in payload["series"]
            for change in entry.get("changes", [])
        }
        self.assertEqual(
            ("Nuova versione", "new_version"),
            labels_by_path.get("/media/series-one/s01e03-1080p.mkv"),
        )
        self.assertEqual(
            ("Nuovi episodi", "new_episode"),
            labels_by_path.get("/media/series-one/s01e03-2160p.mkv"),
        )

    def test_episode_catalog_baseline_does_not_duplicate_latest_batch_versions(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-3-1080",
            "Name": "Episode Three",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 3,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e03-1080",
                    "Path": "/media/series-one/s01e03-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        older_episode_version = {
            "Id": "episode-3-2160",
            "Name": "Episode Three",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 3,
            "DateCreated": "2026-06-30T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e03-2160",
                    "Path": "/media/series-one/s01e03-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:05:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode, older_episode_version],
            episode_catalog_items=[current_episode, older_episode_version],
            series_entries=[series],
        )

        self.assertIsNone(error)
        paths = [
            change.get("path")
            for entry in payload["series"]
            for change in entry.get("changes", [])
        ]
        self.assertEqual(1, paths.count("/media/series-one/s01e03-1080p.mkv"))
        self.assertEqual(1, paths.count("/media/series-one/s01e03-2160p.mkv"))

    def test_episode_catalog_versions_ignore_other_episodes_returned_by_emby(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-6-1080",
            "Name": "Episode Six",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 6,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e06-1080",
                    "Path": "/media/series-one/s01e06-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        matching_episode_version = {
            "Id": "episode-6-2160",
            "Name": "Episode Six",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 6,
            "DateCreated": "2026-07-16T10:06:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e06-2160",
                    "Path": "/media/series-one/s01e06-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        unrelated_episode = {
            "Id": "episode-14-720",
            "Name": "Episode Fourteen",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 14,
            "DateCreated": "2026-07-16T10:07:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e14-720",
                    "Path": "/media/series-one/s01e14-720p.mkv",
                    "Container": "mkv",
                    "Size": 3000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:07:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode, matching_episode_version, unrelated_episode],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        paths = [change.get("path") for change in payload["series"][0]["changes"]]
        self.assertIn("/media/series-one/s01e06-1080p.mkv", paths)
        self.assertIn("/media/series-one/s01e06-2160p.mkv", paths)
        self.assertNotIn("/media/series-one/s01e14-720p.mkv", paths)
        self.assertEqual({6}, {change.get("episode_number") for change in payload["series"][0]["changes"]})

    def test_multiple_latest_items_for_same_episode_are_reported_once_per_version(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        episode_1080 = {
            "Id": "episode-6-1080",
            "Name": "Episode Six",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 6,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e06-1080",
                    "Path": "/media/series-one/s01e06-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        episode_2160 = {
            "Id": "episode-6-2160",
            "Name": "Episode Six",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 6,
            "DateCreated": "2026-07-16T10:06:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e06-2160",
                    "Path": "/media/series-one/s01e06-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                }
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:06:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[episode_1080, episode_2160],
            episode_catalog_items=[episode_1080, episode_2160],
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        paths = [change.get("path") for change in payload["series"][0]["changes"]]
        self.assertEqual(
            ["/media/series-one/s01e06-2160p.mkv", "/media/series-one/s01e06-1080p.mkv"],
            paths,
        )

    def test_series_changes_are_sorted_by_season_and_episode(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()

        def episode(episode_number, added_at):
            return {
                "Id": f"episode-{episode_number}",
                "Name": f"Episode {episode_number}",
                "Type": "Episode",
                "SeriesId": "series-1",
                "SeriesName": "Series One",
                "SeriesProductionYear": 2026,
                "ParentIndexNumber": 1,
                "IndexNumber": episode_number,
                "DateCreated": added_at,
                "MediaSources": [
                    {
                        "Id": f"source-s01e{episode_number:02d}",
                        "Path": f"/media/series-one/s01e{episode_number:02d}.mkv",
                        "Container": "mkv",
                        "Size": episode_number * 1000,
                    }
                ],
            }

        episode_items = [
            episode(4, "2026-07-16T10:04:00+00:00"),
            episode(1, "2026-07-16T10:03:00+00:00"),
            episode(3, "2026-07-16T10:02:00+00:00"),
            episode(2, "2026-07-16T10:01:00+00:00"),
        ]
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T10:04:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=episode_items,
            series_entries=[series],
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual(
            [1, 2, 3, 4],
            [change.get("episode_number") for change in payload["series"][0]["changes"]],
        )

    def test_send_notifications_marks_series_episode_history_as_notified(self):
        saved_states = []
        episode_key = "series-1:S1:E2"
        latest_state = {
            "server-a": {
                "movies": {"items": {}},
                "series": {
                    "items": {
                        "series-1": {
                            "series_id": "series-1",
                            "item_id": "series-1",
                            "title": "Series One",
                            "seasons": [1],
                            "episodes": {
                                episode_key: {
                                    "season": 1,
                                    "episode": 2,
                                    "media_source_keys": ["episode-version-key"],
                                    "notified": False,
                                }
                            },
                            "notified": False,
                            "notified_at": "",
                        }
                    }
                },
                "history": {
                    "episodes": {
                        episode_key: {
                            "series_id": "series-1",
                            "season": 1,
                            "episode": 2,
                            "media_source_keys": ["episode-version-key"],
                            "notified": False,
                        }
                    }
                },
            }
        }
        cache_payload = {
            "payload": {
                "movies": [],
                "series": [
                    {
                        "server_id": "server-a",
                        "item_id": "series-1",
                        "item_type": "series",
                        "title": "Series One",
                        "year": 2026,
                        "added_at": "2026-07-16T10:05:00+00:00",
                        "batch_id": "server-a:series:series-1:202607161005",
                        "changes": [
                            {
                                "kind": "new_episode",
                                "season_number": 1,
                                "episode_number": 2,
                                "episode_title": "Episode Two",
                                "added_at": "2026-07-16T10:05:00+00:00",
                            }
                        ],
                    }
                ],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                }
            ],
        }
        telegram_settings = {
            "PRESETS": [
                {
                    "id": "telegram-a",
                    "name": "Telegram",
                    "bot_ids": ["bot-a"],
                    "group_ids": ["group-a"],
                    "channel_ids": [],
                }
            ],
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value=deepcopy(latest_state),
        ), patch("emby_latest.db_state.save_state", side_effect=lambda state: saved_states.append(deepcopy(state))), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", return_value=(True, "OK", {})), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertTrue(saved_states)
        saved_episode = saved_states[-1]["server-a"]["history"]["episodes"][episode_key]
        self.assertTrue(saved_episode["notified"])


if __name__ == "__main__":
    unittest.main()
