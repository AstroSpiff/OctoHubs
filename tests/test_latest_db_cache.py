"""Latest publications DB cache merge behavior."""

from __future__ import annotations

from copy import deepcopy
import unittest

from emby_latest import db_cache
from emby_latest.collector_finalization import (
    CollectionFinalizationContext,
    finalize_collection,
)
from emby_latest.db_cache import (
    LatestCachePersistenceError,
    merge_cached_entry,
    merge_with_db,
)
from emby_latest.publication_identity import reconcile_publication_events


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
    @staticmethod
    def _movie_event(batch_id, source_id, added_at, *, update_type="new"):
        is_update = update_type == "update"
        return {
            "server_id": "server-a",
            "item_id": "movie-1",
            "signature": "tmdb:1",
            "item_type": "Movie",
            "batch_id": batch_id,
            "title": "Movie One",
            "added_at": added_at,
            "update_type": update_type,
            "update_label": "Nuova versione" if is_update else "Nuovo film",
            "changes": [
                {
                    "kind": "new_version" if is_update else "new_movie",
                    "label": "Nuova versione" if is_update else "Nuovo film",
                    "media_source_id": source_id,
                    "path": f"/media/{source_id}.mkv",
                    "added_at": added_at,
                    "resolution": "1920x1080",
                    "size": 1000,
                }
            ],
        }

    def test_load_cache_can_use_explicit_storage_without_global_backend(self):
        storage = _ExplicitCacheStorage()

        data = db_cache.load_cache("batch", db_storage=storage)

        self.assertEqual("Cached movie", data["payload"]["movies"][0]["title"])
        self.assertEqual([("load_latest_cache", "batch")], storage.calls)

    def test_load_cache_distinguishes_read_failure_from_missing_snapshot(self):
        class _FailingStorage:
            @staticmethod
            def load_latest_cache(_cache_kind):
                raise RuntimeError("database unavailable")

        with self.assertRaises(LatestCachePersistenceError):
            db_cache.load_cache("batch", db_storage=_FailingStorage())

    def test_incremental_merge_failure_cannot_publish_a_replacement(self):
        class _FailingCache:
            def __init__(self):
                self.saved = []

            @staticmethod
            def merge_with_db(_new_payload, _existing_payload):
                raise RuntimeError("merge failed")

            def save_cache(self, *args):
                self.saved.append(args)

        cache = _FailingCache()
        context = CollectionFinalizationContext(
            movies=[],
            series=[],
            errors=[],
            config={},
            cache_payload={},
            latest_state={},
            limit=10,
            per_server_limit=10,
            apply_batch_gap=True,
            enrich=False,
            force_omdb=False,
            omdb_cache_hours=24,
            skip_existing_complete=True,
            existing_db_payload={"movies": [{"item_id": "old"}], "series": []},
            state_enabled=True,
            state_changed=False,
            publish_progress_completion=False,
            progress_tracker=None,
            db_cache=cache,
            db_state=None,
            enrich_entry_with_tmdb=lambda entry, *_args, **_kwargs: entry,
            apply_jellyseerr_request_info=lambda *_args: None,
            sync_jellyseerr_to_db=lambda *_args: None,
        )

        with self.assertRaises(LatestCachePersistenceError):
            finalize_collection(context)
        self.assertEqual([], cache.saved)

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

    def test_merge_with_db_collapses_same_movie_event_across_refresh_batches(self):
        original = self._movie_event(
            "server-a:movie:20260908122603:20260908122603",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        repeated = self._movie_event(
            "server-a:movie:20260912100000:20260912100000",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )

        merged = merge_with_db(
            {"movies": [repeated], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual(original["batch_id"], merged["movies"][0]["batch_id"])
        self.assertEqual("Nuovo film", merged["movies"][0]["update_label"])

    def test_movie_identity_ignores_mediainfo_enrichment_and_date_format(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03Z",
        )
        enriched = self._movie_event(
            "server-a:movie:refresh",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        enriched["changes"][0].update(
            {
                "path": "/MEDIA/SOURCE-A.MKV",
                "resolution": "1080p",
                "video_codec": "avc",
                "audio_codec": "eac3",
                "size": 1001,
                "source_name": "/MEDIA/SOURCE-A.MKV",
            }
        )

        merged = merge_with_db(
            {"movies": [enriched], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual(original["batch_id"], merged["movies"][0]["batch_id"])

    def test_path_fallback_canonicalizes_case_and_timestamp_format(self):
        original = self._movie_event(
            "server-a:movie:original",
            "",
            "2026-09-08T12:26:03Z",
        )
        original["changes"][0]["path"] = "/MEDIA/Movie.mkv"
        repeated = self._movie_event(
            "server-a:movie:refresh",
            "",
            "2026-09-08T12:26:03+00:00",
        )
        repeated["changes"][0].update(
            {
                "path": "/media/movie.mkv",
                "resolution": "1080p",
                "video_codec": "avc",
                "size": 1001,
            }
        )

        merged = merge_with_db(
            {"movies": [repeated], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual(original["batch_id"], merged["movies"][0]["batch_id"])

    def test_placeholder_identity_survives_provider_signature_enrichment(self):
        original = self._movie_event(
            "server-a:movie:original",
            "",
            "2026-09-08T12:26:03Z",
        )
        original.update({"signature": "title:movie-one:2026"})
        original["changes"][0].update({"path": "", "source_name": ""})
        enriched = deepcopy(original)
        enriched.update(
            {
                "batch_id": "server-a:movie:refresh",
                "signature": "tmdb:1",
            }
        )

        merged = merge_with_db(
            {"movies": [enriched], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual("tmdb:1", merged["movies"][0]["signature"])

    def test_placeholder_identity_ignores_later_mediainfo_enrichment(self):
        original = self._movie_event(
            "server-a:movie:original",
            "",
            "2026-09-08T12:26:03Z",
        )
        original["changes"][0].update(
            {"path": "", "source_name": "", "resolution": "", "size": ""}
        )
        enriched = deepcopy(original)
        enriched.update({"batch_id": "server-a:movie:refresh"})
        enriched["changes"][0].update(
            {
                "resolution": "1920x1080",
                "video_codec": "h264",
                "audio_codec": "aac",
                "size": 1001,
            }
        )

        merged = merge_with_db(
            {"movies": [enriched], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))

    def test_placeholder_alias_chain_is_deduplicated_transitively(self):
        first = self._movie_event(
            "server-a:movie:first",
            "",
            "2026-09-08T12:26:03Z",
        )
        first.update({"item_id": "movie-1", "signature": "title:movie-one:2026"})
        first["changes"][0].update({"path": "", "source_name": ""})
        bridge = deepcopy(first)
        bridge.update({"batch_id": "server-a:movie:bridge", "signature": "tmdb:1"})
        current = deepcopy(bridge)
        current.update({"batch_id": "server-a:movie:current", "item_id": "movie-2"})

        reconciled = reconcile_publication_events(
            [first, bridge, current],
            [],
            "movie",
        )

        self.assertEqual(1, len(reconciled))

    def test_placeholder_alias_chain_survives_cache_fresh_boundary(self):
        first = self._movie_event(
            "server-a:movie:first",
            "",
            "2026-09-08T12:26:03Z",
        )
        first.update({"item_id": "movie-1", "signature": "title:movie-one:2026"})
        first["changes"][0].update({"path": "", "source_name": ""})
        bridge = deepcopy(first)
        bridge.update({"batch_id": "server-a:movie:bridge", "signature": "tmdb:1"})
        current = deepcopy(bridge)
        current.update({"batch_id": "server-a:movie:current", "item_id": "movie-2"})

        merged = merge_with_db(
            {"movies": [current], "series": [], "errors": []},
            {"movies": [first, bridge], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual("movie-2", merged["movies"][0]["item_id"])
        self.assertEqual("tmdb:1", merged["movies"][0]["signature"])

    def test_movie_identity_survives_provider_signature_enrichment(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        original["signature"] = "title:movie-one:2026"
        enriched = self._movie_event(
            "server-a:movie:refresh",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        enriched["signature"] = "tmdb:1"

        merged = merge_with_db(
            {"movies": [enriched], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual("tmdb:1", merged["movies"][0]["signature"])
        self.assertEqual(original["batch_id"], merged["movies"][0]["batch_id"])

    def test_movie_identity_survives_representative_item_change(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        repeated = self._movie_event(
            "server-a:movie:refresh",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        repeated["item_id"] = "movie-2"

        merged = merge_with_db(
            {"movies": [repeated], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(1, len(merged["movies"]))
        self.assertEqual("movie-2", merged["movies"][0]["item_id"])
        self.assertEqual(original["batch_id"], merged["movies"][0]["batch_id"])

    def test_reused_source_id_with_new_path_remains_a_new_version(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        new_version = self._movie_event(
            "server-a:movie:new-version",
            "source-a",
            "2026-09-12T10:00:00+00:00",
            update_type="update",
        )
        original["changes"][0]["path"] = "/media/old.mkv"
        new_version["changes"][0]["path"] = "/media/new.mkv"

        merged = merge_with_db(
            {"movies": [new_version], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(2, len(merged["movies"]))
        self.assertEqual(
            ["Nuovo film", "Nuova versione"],
            [entry["update_label"] for entry in merged["movies"]],
        )

    def test_placeholder_movies_at_same_instant_are_not_conflated(self):
        first = self._movie_event(
            "server-a:movie:first",
            "",
            "2026-09-12T10:00:00+00:00",
        )
        second = self._movie_event(
            "server-a:movie:second",
            "",
            "2026-09-12T10:00:00+00:00",
        )
        for entry in (first, second):
            entry["changes"][0].update({"path": "", "source_name": ""})
        second.update(
            {
                "item_id": "movie-2",
                "signature": "tmdb:2",
                "title": "Movie Two",
            }
        )

        reconciled = reconcile_publication_events(
            [first, second],
            [],
            "movie",
        )

        self.assertEqual(2, len(reconciled))

    def test_placeholder_series_at_same_instant_are_not_conflated(self):
        def _series(item_id, signature):
            return {
                "server_id": "server-a",
                "item_id": item_id,
                "signature": signature,
                "item_type": "Series",
                "batch_id": f"batch-{item_id}",
                "update_type": "new",
                "update_label": "Nuova serie",
                "changes": [
                    {
                        "kind": "new_episode",
                        "season_number": 1,
                        "episode_number": 1,
                        "episode_title": "Pilot",
                        "added_at": "2026-09-12T10:00:00+00:00",
                    }
                ],
            }

        reconciled = reconcile_publication_events(
            [_series("series-1", "tmdb:1"), _series("series-2", "tmdb:2")],
            [],
            "series",
        )

        self.assertEqual(2, len(reconciled))

    def test_reconcile_existing_snapshot_preserves_original_publication_meaning(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        existing = self._movie_event(
            "server-a:movie:refresh",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        existing.update({"update_type": "existing", "update_label": ""})
        existing["changes"][0].update({"kind": "existing", "label": ""})

        reconciled = reconcile_publication_events([existing], [original], "movie")

        self.assertEqual(1, len(reconciled))
        self.assertEqual("new", reconciled[0]["update_type"])
        self.assertEqual("Nuovo film", reconciled[0]["update_label"])
        self.assertEqual("new_movie", reconciled[0]["changes"][0]["kind"])
        self.assertEqual(original["batch_id"], reconciled[0]["batch_id"])

    def test_merge_with_db_preserves_genuine_later_movie_version(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        new_version = self._movie_event(
            "server-a:movie:new-version",
            "source-b",
            "2026-09-12T10:00:00+00:00",
            update_type="update",
        )

        merged = merge_with_db(
            {"movies": [new_version], "series": [], "errors": []},
            {"movies": [original], "series": [], "errors": []},
        )

        self.assertEqual(2, len(merged["movies"]))
        self.assertEqual(
            ["Nuovo film", "Nuova versione"],
            [entry["update_label"] for entry in merged["movies"]],
        )

    def test_unchanged_refresh_after_new_version_keeps_latest_version_event(self):
        original = self._movie_event(
            "server-a:movie:original",
            "source-a",
            "2026-09-08T12:26:03+00:00",
        )
        new_version = self._movie_event(
            "server-a:movie:new-version",
            "source-b",
            "2026-09-12T10:00:00+00:00",
            update_type="update",
        )
        existing = self._movie_event(
            "server-a:movie:refresh",
            "source-b",
            "2026-09-12T10:00:00+00:00",
        )
        existing.update({"update_type": "existing", "update_label": ""})
        existing["changes"][0].update({"kind": "existing", "label": ""})

        reconciled = reconcile_publication_events(
            [existing],
            [original, new_version],
            "movie",
        )

        self.assertEqual(1, len(reconciled))
        self.assertEqual("update", reconciled[0]["update_type"])
        self.assertEqual("Nuova versione", reconciled[0]["update_label"])
        self.assertEqual("new_version", reconciled[0]["changes"][0]["kind"])
        self.assertEqual("source-b", reconciled[0]["changes"][0]["media_source_id"])

    def test_reconcile_series_events_uses_same_identity_invariant(self):
        original = {
            "server_id": "server-a",
            "item_id": "series-1",
            "item_type": "Series",
            "batch_id": "series-original",
            "update_type": "new",
            "update_label": "Nuova serie",
            "changes": [
                {
                    "kind": "new_episode",
                    "season_number": 1,
                    "episode_number": 2,
                    "media_source_id": "episode-source",
                    "added_at": "2026-09-08T12:26:03+00:00",
                }
            ],
        }
        repeated = {
            **original,
            "batch_id": "series-refresh",
            "update_type": "existing",
            "update_label": "",
            "changes": [{**original["changes"][0], "kind": "existing"}],
        }

        reconciled = reconcile_publication_events([repeated], [original], "series")

        self.assertEqual(1, len(reconciled))
        self.assertEqual("Nuova serie", reconciled[0]["update_label"])
        self.assertEqual("new_episode", reconciled[0]["changes"][0]["kind"])

    def test_series_durable_source_ignores_corrected_episode_metadata(self):
        original = {
            "server_id": "server-a",
            "item_id": "series-1",
            "item_type": "Series",
            "batch_id": "series-original",
            "update_type": "new",
            "update_label": "Nuova serie",
            "changes": [
                {
                    "kind": "new_episode",
                    "season_number": 1,
                    "episode_number": 1,
                    "episode_title": "TBA",
                    "media_source_id": "episode-source",
                    "path": "/show/s01e01.mkv",
                    "added_at": "2026-09-08T12:26:03+00:00",
                }
            ],
        }
        corrected = deepcopy(original)
        corrected.update({"batch_id": "series-refresh", "update_type": "existing"})
        corrected["changes"][0].update(
            {
                "kind": "existing",
                "season_number": 2,
                "episode_number": 3,
                "episode_title": "Pilot",
            }
        )

        merged = merge_with_db(
            {"movies": [], "series": [corrected], "errors": []},
            {"movies": [], "series": [original], "errors": []},
        )

        self.assertEqual(1, len(merged["series"]))
        self.assertEqual("Nuova serie", merged["series"][0]["update_label"])


if __name__ == "__main__":
    unittest.main()
