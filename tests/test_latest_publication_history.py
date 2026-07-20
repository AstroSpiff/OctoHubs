"""Latest publications historical classification behavior."""

from __future__ import annotations

from copy import deepcopy
import os
import tempfile
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


def _latest_settings(batch_gap_minutes=180):
    return {
        "SETTINGS": {
            "batch_gap_minutes": batch_gap_minutes,
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
    emby_user_items=None,
    batch_gap_minutes=180,
):
    movie_items = list(movie_items or [])
    movie_catalog_items = list(movie_catalog_items or [])
    episode_items = list(episode_items or [])
    series_entries = list(series_entries or [])
    episode_catalog_items = list(episode_catalog_items or [])
    emby_user_items = deepcopy(emby_user_items or {})

    def fake_fetch(_server, item_type, _limit, fields=None):
        if item_type == "Movie":
            return movie_items, None
        if item_type == "Episode":
            return episode_items, None
        return [], None

    def fake_emby_api(_server, path, method="GET", params=None, json_payload=None):
        if path == "Users":
            return True, [{"Id": "emby-user-a"}]
        if path == "Items":
            params = params or {}
            item_ids = [
                item_id.strip()
                for item_id in str(params.get("Ids") or "").split(",")
                if item_id.strip()
            ]
            return True, {"Items": [deepcopy(emby_user_items[item_id]) for item_id in item_ids if item_id in emby_user_items]}
        prefix = "Users/emby-user-a/Items/"
        if isinstance(path, str) and path.startswith(prefix):
            item_id = path[len(prefix):]
            item = emby_user_items.get(item_id)
            if item is not None:
                return True, deepcopy(item)
            return False, "404 Not Found"
        return False, "Unexpected Emby API call"

    with patch("core.config_manager.load_config", return_value=(_base_config(), True)), patch(
        "core.config_manager._db_enabled",
        return_value=True,
    ), patch("emby_latest.collectors.get_emby_servers", return_value=[{"id": "server-a", "name": "Server A"}]), patch(
        "emby_latest.collectors._load_latest_settings",
        return_value=_latest_settings(batch_gap_minutes=batch_gap_minutes),
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
        "emby_latest.emby_api._call_emby_api",
        side_effect=fake_emby_api,
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

    def test_movie_version_classification_prefers_emby_dates_over_filesystem_times(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()

        with tempfile.TemporaryDirectory() as tmpdir:
            old_path = os.path.join(tmpdir, "tito-720p.mkv")
            new_path = os.path.join(tmpdir, "tito-1080p.mkv")
            for path in (old_path, new_path):
                with open(path, "wb") as handle:
                    handle.write(b"media")
                os.utime(path, (1_800_000_000, 1_800_000_000))

            current_movie = {
                "Id": "movie-1",
                "Name": "Tito e gli alieni",
                "Type": "Movie",
                "ProductionYear": 2018,
                "DateCreated": "2026-07-16T10:00:00+00:00",
                "ProviderIds": {"Tmdb": "1"},
                "MediaSources": [
                    {
                        "Id": "source-720",
                        "Path": old_path,
                        "Container": "mkv",
                        "Size": 7780000000,
                        "DateCreated": "2026-07-16T09:40:00+00:00",
                    },
                    {
                        "Id": "source-1080",
                        "Path": new_path,
                        "Container": "mkv",
                        "Size": 8120000000,
                        "DateCreated": "2026-07-16T10:00:00+00:00",
                    },
                ],
            }

            payload, error = _collect_with_mocks(
                db_state,
                db_cache,
                movie_items=[current_movie],
                movie_catalog_items=[current_movie],
                batch_gap_minutes=10,
            )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual([new_path], [change.get("path") for change in payload["movies"][0]["changes"]])

    def test_movie_notification_checkpoint_excludes_versions_already_notified_inside_gap(self):
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
                                "title": "Tito e gli alieni",
                                "notified": True,
                                "notified_at": "2026-07-16T10:02:00+00:00",
                                "media_source_keys": [],
                            }
                        }
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Tito e gli alieni",
            "Type": "Movie",
            "ProductionYear": 2018,
            "DateCreated": "2026-07-16T10:05:00+00:00",
            "ProviderIds": {"Tmdb": "1"},
            "MediaSources": [
                {
                    "Id": "source-720",
                    "Path": "/media/tito-720p.mkv",
                    "Container": "mkv",
                    "Size": 7780000000,
                    "DateCreated": "2026-07-16T10:00:00+00:00",
                },
                {
                    "Id": "source-1080",
                    "Path": "/media/tito-1080p.mkv",
                    "Container": "mkv",
                    "Size": 8120000000,
                    "DateCreated": "2026-07-16T10:05:00+00:00",
                },
            ],
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie],
            movie_catalog_items=[current_movie],
            batch_gap_minutes=10,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual(["/media/tito-1080p.mkv"], [change.get("path") for change in payload["movies"][0]["changes"]])

    def test_movie_uses_media_source_item_dates_when_playback_sources_have_no_dates(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Underworld: Il risveglio",
            "Type": "Movie",
            "ProductionYear": 2012,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "52520"},
            "MediaSources": [
                {
                    "Id": "mediasource_496008",
                    "Path": "/media/underworld-awakening-2160p-new.mkv",
                    "Container": "mkv",
                    "Size": 37985466278,
                },
                {
                    "Id": "mediasource_489411",
                    "Path": "/media/underworld-awakening-2160p-old.mkv",
                    "Container": "mkv",
                    "Size": 12040319162,
                },
                {
                    "Id": "mediasource_496007",
                    "Path": "/media/underworld-awakening-1080p-new.mkv",
                    "Container": "mkv",
                    "Size": 19343509796,
                },
                {
                    "Id": "mediasource_489412",
                    "Path": "/media/underworld-awakening-1080p-old.mkv",
                    "Container": "mkv",
                    "Size": 9158170433,
                },
            ],
        }
        emby_user_items = {
            "496008": {"Id": "496008", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "496007": {"Id": "496007", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "489411": {"Id": "489411", "DateCreated": "2026-06-14T03:27:22+00:00"},
            "489412": {"Id": "489412", "DateCreated": "2026-06-14T03:27:22+00:00"},
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie],
            movie_catalog_items=[current_movie],
            emby_user_items=emby_user_items,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual(
            {
                "/media/underworld-awakening-1080p-new.mkv",
                "/media/underworld-awakening-2160p-new.mkv",
            },
            {change.get("path") for change in payload["movies"][0]["changes"]},
        )
        self.assertFalse(
            {
                "/media/underworld-awakening-1080p-old.mkv",
                "/media/underworld-awakening-2160p-old.mkv",
            }
            & {change.get("path") for change in payload["movies"][0]["changes"]},
        )

    def test_movie_uses_playbackinfo_extra_sources_as_existing_emby_baseline(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Underworld: Evolution",
            "Type": "Movie",
            "ProductionYear": 2006,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "834"},
            "MediaSources": [
                {
                    "Id": "source-2160",
                    "Path": "/media/underworld-evolution-2160p.mkv",
                    "Container": "mkv",
                    "Size": 19608381412,
                },
                {
                    "Id": "source-1080",
                    "Path": "/media/underworld-evolution-1080p.mkv",
                    "Container": "mkv",
                    "Size": 10118529350,
                },
            ],
        }
        playback_sources = [
            *current_movie["MediaSources"],
            {
                "Id": "source-720",
                "Path": "/media/underworld-evolution-720p.mkv",
                "Container": "mkv",
                "Size": 1700000000,
            },
        ]

        with patch(
            "emby_latest.collectors._fetch_emby_playback_media_sources",
            return_value=playback_sources,
        ):
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
                "/media/underworld-evolution-2160p.mkv",
                "/media/underworld-evolution-1080p.mkv",
            },
            {change.get("path") for change in payload["movies"][0]["changes"]},
        )
        saved_movie = db_state.saved[-1]["server-a"]["movies"]["items"]["tmdb:834"]
        self.assertEqual(3, len(saved_movie.get("media_source_keys") or []))

    def test_movie_change_list_omits_strm_placeholders_when_real_sources_exist(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "movies": {
                            "tmdb:277": {
                                "item_id": "movie-1",
                                "signature": "tmdb:277",
                                "media_source_keys": ["old-720-key"],
                                "notified": True,
                                "notified_at": "2026-06-15T10:00:00+00:00",
                            }
                        }
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Underworld",
            "Type": "Movie",
            "ProductionYear": 2003,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "277"},
            "MediaSources": [
                {
                    "Id": "source-2160",
                    "Path": "http://example.test/Underworld (2003) - 2160p.mkv",
                    "Container": "mkv",
                    "Size": 37916041979,
                },
                {
                    "Id": "source-1080",
                    "Path": "http://example.test/Underworld (2003) - 1080p.mkv",
                    "Container": "mkv",
                    "Size": 14974791386,
                },
                {
                    "Path": "/mnt/shared/fusemounts/redprimrose_strms/media/movies/Underworld (2003)/Underworld (2003) - 1080p.strm",
                    "Container": "strm",
                },
                {
                    "Path": "/mnt/shared/fusemounts/redprimrose_strms/media/movies/Underworld (2003)/Underworld (2003) - 2160p.strm",
                    "Container": "strm",
                },
            ],
        }
        emby_user_items = {
            "source-2160": {"Id": "source-2160", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "source-1080": {"Id": "source-1080", "DateCreated": "2026-07-16T13:03:01+00:00"},
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            movie_items=[current_movie],
            movie_catalog_items=[current_movie],
            emby_user_items=emby_user_items,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        changes = payload["movies"][0]["changes"]
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(
            {
                "http://example.test/Underworld (2003) - 1080p.mkv",
                "http://example.test/Underworld (2003) - 2160p.mkv",
            },
            {change.get("path") for change in changes},
        )
        self.assertFalse([change for change in changes if str(change.get("path") or "").endswith(".strm")])
        saved_movie = db_state.saved[-1]["server-a"]["movies"]["items"]["tmdb:277"]
        self.assertEqual(5, len(saved_movie.get("media_source_keys") or []))

    def test_movie_playbackinfo_sibling_versions_are_not_misclassified_as_baseline(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        movie_1080 = {
            "Id": "496002",
            "Name": "Underworld: Evolution",
            "Type": "Movie",
            "ProductionYear": 2006,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "834"},
            "MediaSources": [
                {
                    "Id": "mediasource_496002",
                    "Path": "/media/underworld-evolution-1080p-new.mkv",
                    "Container": "mkv",
                    "Size": 10118529350,
                }
            ],
        }
        movie_2160 = {
            "Id": "496003",
            "Name": "Underworld: Evolution",
            "Type": "Movie",
            "ProductionYear": "2006",
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "834"},
            "MediaSources": [
                {
                    "Id": "mediasource_496003",
                    "Path": "/media/underworld-evolution-2160p-new.mkv",
                    "Container": "mkv",
                    "Size": 19608381412,
                }
            ],
        }
        playback_sources = [
            {
                "Id": "mediasource_496003",
                "Path": "/media/underworld-evolution-2160p-new.mkv",
                "Container": "mkv",
                "Size": 19608381412,
                "DateCreated": "2026-07-16T13:03:01+00:00",
            },
            {
                "Id": "mediasource_496002",
                "Path": "/media/underworld-evolution-1080p-new.mkv",
                "Container": "mkv",
                "Size": 10118529350,
                "DateCreated": "2026-07-16T13:03:01+00:00",
            },
            {
                "Id": "mediasource_210661",
                "Path": "/media/underworld-evolution-720p-old.mkv",
                "Container": "mkv",
                "Size": 2232553504,
                "DateCreated": "2025-11-09T09:29:35+00:00",
            },
        ]

        with patch(
            "emby_latest.collectors._fetch_emby_playback_media_sources",
            return_value=playback_sources,
        ):
            payload, error = _collect_with_mocks(
                db_state,
                db_cache,
                movie_items=[movie_1080, movie_2160],
                movie_catalog_items=[movie_1080, movie_2160],
            )

        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("update", payload["movies"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["movies"][0]["changes"]])
        self.assertEqual(
            {
                "/media/underworld-evolution-1080p-new.mkv",
                "/media/underworld-evolution-2160p-new.mkv",
            },
            {change.get("path") for change in payload["movies"][0]["changes"]},
        )

    def test_known_movie_does_not_fetch_playbackinfo_baseline(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {
                        "items": {
                            "tmdb:834": {
                                "title": "Underworld: Evolution",
                                "media_source_keys": ["old-720-key"],
                                "notified": True,
                                "notified_at": "2026-07-01T10:00:00+00:00",
                            }
                        }
                    },
                    "series": {"items": {}},
                }
            }
        )
        db_cache = _RecordingCache()
        current_movie = {
            "Id": "movie-1",
            "Name": "Underworld: Evolution",
            "Type": "Movie",
            "ProductionYear": 2006,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "ProviderIds": {"Tmdb": "834"},
            "MediaSources": [
                {
                    "Id": "source-1080",
                    "Path": "/media/underworld-evolution-1080p.mkv",
                    "Container": "mkv",
                    "Size": 10118529350,
                }
            ],
        }

        with patch("emby_latest.collectors._fetch_emby_playback_media_sources") as playback_fetch:
            payload, error = _collect_with_mocks(db_state, db_cache, movie_items=[current_movie])

        playback_fetch.assert_not_called()
        self.assertIsNone(error)
        self.assertTrue(payload["movies"])
        self.assertEqual("Nuova versione", payload["movies"][0].get("update_label"))

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

    def test_known_episode_does_not_fetch_playbackinfo_baseline(self):
        episode_key = "series-1:S1:E2"
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "episodes": {
                            episode_key: {
                                "series_id": "series-1",
                                "season": 1,
                                "episode": 2,
                                "media_source_keys": ["old-episode-key"],
                                "notified": True,
                                "notified_at": "2026-07-01T10:00:00+00:00",
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

        with patch("emby_latest.collectors._fetch_emby_playback_media_sources") as playback_fetch:
            payload, error = _collect_with_mocks(db_state, db_cache, episode_items=[episode], series_entries=[series])

        playback_fetch.assert_not_called()
        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))

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

    def test_episode_version_classification_prefers_emby_dates_over_filesystem_times(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()

        with tempfile.TemporaryDirectory() as tmpdir:
            old_path = os.path.join(tmpdir, "ride-or-die-s01e01-2160p.mkv")
            new_path = os.path.join(tmpdir, "ride-or-die-s01e01-1080p.mkv")
            for path in (old_path, new_path):
                with open(path, "wb") as handle:
                    handle.write(b"media")
                os.utime(path, (1_800_000_000, 1_800_000_000))

            current_episode = {
                "Id": "episode-1",
                "Name": "Il libro di Giuditta",
                "Type": "Episode",
                "SeriesId": "series-1",
                "SeriesName": "Ride or Die",
                "SeriesProductionYear": 2026,
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "DateCreated": "2026-07-19T11:00:00+00:00",
                "MediaSources": [
                    {
                        "Id": "source-s01e01-2160",
                        "Path": old_path,
                        "Container": "mkv",
                        "Size": 7540000000,
                        "DateCreated": "2026-07-19T10:00:00+00:00",
                    },
                    {
                        "Id": "source-s01e01-1080",
                        "Path": new_path,
                        "Container": "mkv",
                        "Size": 2940000000,
                        "DateCreated": "2026-07-19T11:00:00+00:00",
                    },
                ],
            }
            series = {
                "Id": "series-1",
                "Name": "Ride or Die",
                "Type": "Series",
                "ProductionYear": 2026,
                "DateCreated": "2026-07-19T10:00:00+00:00",
            }

            payload, error = _collect_with_mocks(
                db_state,
                db_cache,
                episode_items=[current_episode],
                episode_catalog_items=[current_episode],
                series_entries=[series],
                batch_gap_minutes=10,
            )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(["new_version"], [change.get("kind") for change in payload["series"][0]["changes"]])
        self.assertEqual([new_path], [change.get("path") for change in payload["series"][0]["changes"]])

    def test_episode_notification_checkpoint_excludes_versions_already_notified_inside_gap(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "episodes": {
                            "series-1:S1:E1": {
                                "series_id": "series-1",
                                "season": 1,
                                "episode": 1,
                                "notified": True,
                                "notified_at": "2026-07-19T10:02:00+00:00",
                                "media_source_keys": [],
                            }
                        }
                    },
                }
            }
        )
        db_cache = _RecordingCache()
        current_episode = {
            "Id": "episode-1",
            "Name": "Il libro di Giuditta",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Ride or Die",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 1,
            "DateCreated": "2026-07-19T10:05:00+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e01-2160",
                    "Path": "/media/ride-or-die-s01e01-2160p.mkv",
                    "Container": "mkv",
                    "Size": 7540000000,
                    "DateCreated": "2026-07-19T10:00:00+00:00",
                },
                {
                    "Id": "source-s01e01-1080",
                    "Path": "/media/ride-or-die-s01e01-1080p.mkv",
                    "Container": "mkv",
                    "Size": 2940000000,
                    "DateCreated": "2026-07-19T10:05:00+00:00",
                },
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Ride or Die",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-19T10:00:00+00:00",
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode],
            series_entries=[series],
            batch_gap_minutes=10,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(["new_version"], [change.get("kind") for change in payload["series"][0]["changes"]])
        self.assertEqual(
            ["/media/ride-or-die-s01e01-1080p.mkv"],
            [change.get("path") for change in payload["series"][0]["changes"]],
        )

    def test_episode_uses_media_source_item_dates_when_playback_sources_have_no_dates(self):
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
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "MediaSources": [
                {
                    "Id": "mediasource_496008",
                    "Path": "/media/series-one/s01e02-2160p-new.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                },
                {
                    "Id": "mediasource_489411",
                    "Path": "/media/series-one/s01e02-2160p-old.mkv",
                    "Container": "mkv",
                    "Size": 1500,
                },
                {
                    "Id": "mediasource_496007",
                    "Path": "/media/series-one/s01e02-1080p-new.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                },
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T13:03:01+00:00",
        }
        emby_user_items = {
            "496008": {"Id": "496008", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "496007": {"Id": "496007", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "489411": {"Id": "489411", "DateCreated": "2026-06-14T03:27:22+00:00"},
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode],
            series_entries=[series],
            emby_user_items=emby_user_items,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["series"][0]["changes"]])
        self.assertEqual(
            {
                "/media/series-one/s01e02-1080p-new.mkv",
                "/media/series-one/s01e02-2160p-new.mkv",
            },
            {change.get("path") for change in payload["series"][0]["changes"]},
        )

    def test_episode_change_list_omits_strm_placeholders_when_real_sources_exist(self):
        db_state = _RecordingState(
            {
                "server-a": {
                    "movies": {"items": {}},
                    "series": {"items": {}},
                    "history": {
                        "episodes": {
                            "series-1:S1:E2": {
                                "item_id": "episode-2",
                                "series_id": "series-1",
                                "season_number": 1,
                                "episode_number": 2,
                                "media_source_keys": ["old-720-key"],
                                "notified": True,
                                "notified_at": "2026-06-15T10:00:00+00:00",
                            }
                        }
                    },
                }
            }
        )
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
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e02-2160",
                    "Path": "http://example.test/Series One S01E02 - 2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                },
                {
                    "Id": "source-s01e02-1080",
                    "Path": "http://example.test/Series One S01E02 - 1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                },
                {
                    "Path": "/mnt/shared/fusemounts/redprimrose_strms/media/tv/Series One/Series One S01E02 - 1080p.strm",
                    "Container": "strm",
                },
                {
                    "Path": "/mnt/shared/fusemounts/redprimrose_strms/media/tv/Series One/Series One S01E02 - 2160p.strm",
                    "Container": "strm",
                },
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T13:03:01+00:00",
        }
        emby_user_items = {
            "source-s01e02-2160": {"Id": "source-s01e02-2160", "DateCreated": "2026-07-16T13:03:01+00:00"},
            "source-s01e02-1080": {"Id": "source-s01e02-1080", "DateCreated": "2026-07-16T13:03:01+00:00"},
        }

        payload, error = _collect_with_mocks(
            db_state,
            db_cache,
            episode_items=[current_episode],
            episode_catalog_items=[current_episode],
            series_entries=[series],
            emby_user_items=emby_user_items,
        )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        changes = payload["series"][0]["changes"]
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(
            {
                "http://example.test/Series One S01E02 - 1080p.mkv",
                "http://example.test/Series One S01E02 - 2160p.mkv",
            },
            {change.get("path") for change in changes},
        )
        self.assertFalse([change for change in changes if str(change.get("path") or "").endswith(".strm")])

    def test_episode_uses_playbackinfo_extra_sources_as_existing_emby_baseline(self):
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
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e02-2160",
                    "Path": "/media/series-one/s01e02-2160p.mkv",
                    "Container": "mkv",
                    "Size": 2000,
                },
                {
                    "Id": "source-s01e02-1080",
                    "Path": "/media/series-one/s01e02-1080p.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                },
            ],
        }
        series = {
            "Id": "series-1",
            "Name": "Series One",
            "Type": "Series",
            "ProductionYear": 2026,
            "DateCreated": "2026-07-16T13:03:01+00:00",
        }
        playback_sources = [
            *current_episode["MediaSources"],
            {
                "Id": "source-s01e02-720",
                "Path": "/media/series-one/s01e02-720p.mkv",
                "Container": "mkv",
                "Size": 700,
            },
        ]

        with patch(
            "emby_latest.collectors._fetch_emby_playback_media_sources",
            return_value=playback_sources,
        ):
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
                "/media/series-one/s01e02-2160p.mkv",
                "/media/series-one/s01e02-1080p.mkv",
            },
            {change.get("path") for change in payload["series"][0]["changes"]},
        )
        saved_episode = db_state.saved[-1]["server-a"]["history"]["episodes"]["series-1:S1:E2"]
        self.assertEqual(3, len(saved_episode.get("media_source_keys") or []))

    def test_episode_playbackinfo_sibling_versions_are_not_misclassified_as_baseline(self):
        db_state = _RecordingState({"server-a": {"movies": {"items": {}}, "series": {"items": {}}}})
        db_cache = _RecordingCache()
        episode_1080 = {
            "Id": "episode-sibling-1080",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e02-1080",
                    "Path": "/media/series-one/s01e02-1080p-new.mkv",
                    "Container": "mkv",
                    "Size": 1000,
                }
            ],
        }
        episode_2160 = {
            "Id": "episode-sibling-2160",
            "Name": "Episode Two",
            "Type": "Episode",
            "SeriesId": "series-1",
            "SeriesName": "Series One",
            "SeriesProductionYear": 2026,
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "DateCreated": "2026-07-16T13:03:01+00:00",
            "MediaSources": [
                {
                    "Id": "source-s01e02-2160",
                    "Path": "/media/series-one/s01e02-2160p-new.mkv",
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
            "DateCreated": "2026-07-16T13:03:01+00:00",
        }
        playback_sources = [
            {
                "Id": "source-s01e02-2160",
                "Path": "/media/series-one/s01e02-2160p-new.mkv",
                "Container": "mkv",
                "Size": 2000,
                "DateCreated": "2026-07-16T13:03:01+00:00",
            },
            {
                "Id": "source-s01e02-1080",
                "Path": "/media/series-one/s01e02-1080p-new.mkv",
                "Container": "mkv",
                "Size": 1000,
                "DateCreated": "2026-07-16T13:03:01+00:00",
            },
            {
                "Id": "source-s01e02-720",
                "Path": "/media/series-one/s01e02-720p-old.mkv",
                "Container": "mkv",
                "Size": 700,
                "DateCreated": "2025-11-09T09:29:35+00:00",
            },
        ]

        with patch(
            "emby_latest.collectors._fetch_emby_playback_media_sources",
            return_value=playback_sources,
        ):
            payload, error = _collect_with_mocks(
                db_state,
                db_cache,
                episode_items=[episode_1080, episode_2160],
                episode_catalog_items=[episode_1080, episode_2160],
                series_entries=[series],
            )

        self.assertIsNone(error)
        self.assertTrue(payload["series"])
        self.assertEqual("update", payload["series"][0].get("update_type"))
        self.assertEqual("Nuova versione", payload["series"][0].get("update_label"))
        self.assertEqual(["new_version", "new_version"], [change.get("kind") for change in payload["series"][0]["changes"]])
        self.assertEqual(
            {
                "/media/series-one/s01e02-1080p-new.mkv",
                "/media/series-one/s01e02-2160p-new.mkv",
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
