"""Latest publications manager availability diagnostics."""

from __future__ import annotations

import unittest
import threading
from unittest.mock import patch

from emby_latest import reset_manager
from emby_latest.api_handlers import build_latest_progress_payload
from emby_latest.manager import EmbyLatestManager


class LatestManagerAvailabilityTests(unittest.TestCase):
    def tearDown(self):
        reset_manager()

    def test_progress_payload_reports_database_unavailable_reason(self):
        reset_manager()

        with patch(
            "core.config_manager.load_config",
            return_value=({"DATABASE": {"ENABLED": True}}, True),
        ), patch(
            "core.config_manager._ensure_db_backend",
            side_effect=RuntimeError("database down"),
        ):
            payload, status_code = build_latest_progress_payload()

        self.assertEqual(status_code, 404)
        self.assertIn("Latest manager not available", payload["message"])
        self.assertIn("database/config unavailable", payload["message"])
        self.assertNotIn("database down", payload["message"])

    def test_progress_payload_reports_database_or_config_when_config_load_is_invalid(self):
        reset_manager()

        with patch("core.config_manager.load_config", return_value=({}, False)):
            payload, status_code = build_latest_progress_payload()

        self.assertEqual(status_code, 404)
        self.assertIn("Latest manager not available", payload["message"])
        self.assertIn("database/config unavailable", payload["message"])


class LatestManagerSnapshotTests(unittest.TestCase):
    def test_snapshot_uses_updated_at_as_cache_timestamp(self):
        manager = EmbyLatestManager.__new__(EmbyLatestManager)
        manager._lock = threading.Lock()
        manager._refreshing = False
        manager.progress_tracker = type(
            "ProgressTracker",
            (),
            {"get_snapshot": lambda _self: {}},
        )()
        stamp = "2026-07-15T10:30:00+00:00"

        with patch(
            "emby_latest.manager.db_cache.load_cache",
            return_value={
                "updated_at": stamp,
                "params": {"limit": 100, "per_server_limit": 50},
                "payload": {"movies": [], "series": [], "errors": []},
            },
        ):
            snapshot = manager.get_snapshot("batch")

        self.assertEqual(snapshot["timestamp"], stamp)


class LatestManagerRefreshTests(unittest.TestCase):
    def _manager(self):
        manager = EmbyLatestManager.__new__(EmbyLatestManager)
        manager._lock = threading.Lock()
        manager._refreshing = False
        manager.progress_tracker = type(
            "ProgressTracker",
            (),
            {"get_snapshot": lambda _self: {}, "update": lambda _self, **_kwargs: None},
        )()
        manager.db_cache = type(
            "Cache",
            (),
            {"save_cache": lambda _self, *_args, **_kwargs: None},
        )()
        manager.db_state = object()
        return manager

    def test_incremental_refresh_rebuilds_batch_and_feed_from_one_batch_collection_when_feed_snapshot_is_missing(self):
        manager = self._manager()
        collect_calls = []
        saved_caches = []
        manager.db_cache.save_cache = lambda *args, **kwargs: saved_caches.append((args, kwargs))

        def fake_load_cache(mode):
            if mode == "batch":
                return {
                    "updated_at": "2026-07-16T10:00:00+00:00",
                    "payload": {"movies": [{"title": "existing"}], "series": [], "errors": []},
                }
            return {}

        def fake_collect_entries(**kwargs):
            collect_calls.append(kwargs)
            return {
                "movies": [
                    {
                        "mode": "batch",
                        "title": "existing",
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "added_at": "2026-07-16T10:00:00+00:00",
                    }
                ],
                "series": [],
                "errors": [],
            }, None

        with patch("emby_latest.manager.db_cache.load_cache", side_effect=fake_load_cache), patch(
            "emby_latest.manager.collectors.collect_entries",
            side_effect=fake_collect_entries,
        ):
            payload, error = manager.refresh_incremental(100, 25, enrich=False)

        self.assertIsNone(error)
        self.assertEqual("batch", payload["movies"][0]["mode"])
        self.assertEqual([True], [call["apply_batch_gap"] for call in collect_calls])
        self.assertEqual([False], [call["skip_existing_complete"] for call in collect_calls])
        self.assertEqual(["feed"], [args[0] for args, _kwargs in saved_caches])

    def test_full_refresh_builds_batch_and_feed_from_one_batch_collection(self):
        manager = self._manager()
        collect_calls = []
        saved_caches = []
        manager.db_cache.save_cache = lambda *args, **kwargs: saved_caches.append((args, kwargs))

        def fake_collect_entries(**kwargs):
            collect_calls.append(kwargs)
            return {
                "movies": [
                    {
                        "mode": "batch",
                        "title": "Movie One",
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "added_at": "2026-07-16T10:00:00+00:00",
                    }
                ],
                "series": [],
                "errors": [],
            }, None

        with patch(
            "emby_latest.manager.collectors.collect_entries",
            side_effect=fake_collect_entries,
        ):
            payload, error = manager.refresh_full(100, 25, enrich=False)

        self.assertIsNone(error)
        self.assertEqual("batch", payload["movies"][0]["mode"])
        self.assertEqual([True], [call["apply_batch_gap"] for call in collect_calls])
        self.assertEqual(["feed"], [args[0] for args, _kwargs in saved_caches])

    def test_incremental_refresh_updates_batch_and_feed_from_one_batch_collection_when_snapshots_exist(self):
        manager = self._manager()
        collect_calls = []
        saved_caches = []
        manager.db_cache.save_cache = lambda *args, **kwargs: saved_caches.append((args, kwargs))

        def fake_load_cache(mode):
            return {
                "updated_at": "2026-07-16T10:00:00+00:00",
                "payload": {"movies": [{"title": f"{mode} existing"}], "series": [], "errors": []},
            }

        def fake_collect_entries(**kwargs):
            collect_calls.append(kwargs)
            return {"movies": [], "series": [], "errors": []}, None

        with patch("emby_latest.manager.db_cache.load_cache", side_effect=fake_load_cache), patch(
            "emby_latest.manager.collectors.collect_entries",
            side_effect=fake_collect_entries,
        ):
            payload, error = manager.refresh_incremental(100, 25, enrich=False)

        self.assertIsNone(error)
        self.assertEqual({"movies": [], "series": [], "errors": []}, payload)
        self.assertEqual([True], [call["apply_batch_gap"] for call in collect_calls])
        self.assertEqual([True], [call["skip_existing_complete"] for call in collect_calls])
        self.assertEqual(["feed"], [args[0] for args, _kwargs in saved_caches])


if __name__ == "__main__":
    unittest.main()
