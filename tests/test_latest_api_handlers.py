"""Latest publications API handler behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_latest.api_handlers import (
    build_enrich_snapshot,
    build_latest_refresh_payload,
    build_latest_snapshot_payload,
    build_notify_snapshot,
    build_preview_snapshot,
)
from emby_latest.operations import make_latest_operation_progress_tracker


class _RecordingManager:
    def __init__(self):
        self.calls = []

    def send_notifications(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "sent": 0, "failed": 0, "errors": []}

    def enrich_item(self, item, force_omdb=False):
        self.calls.append({"item": item, "force_omdb": force_omdb})
        return {"title": item.get("title"), "force_omdb": force_omdb}


class _SnapshotManager:
    def __init__(self):
        self.calls = []

    def get_snapshot(self, mode="batch"):
        self.calls.append(mode)
        return {
            "payload": {
                "movies": [{"title": f"{mode} movie"}],
                "series": [],
                "errors": [],
            },
            "timestamp": f"{mode}-ts",
            "refreshing": False,
            "progress": {},
        }


class _RefreshingSnapshotManager:
    def __init__(self, initial_payload=None):
        self.calls = []
        self.refreshed = False
        self.initial_payload = initial_payload

    def get_snapshot(self, mode="batch"):
        self.calls.append(("snapshot", mode))
        if self.refreshed:
            return {
                "payload": {
                    "movies": [{"title": "refreshed movie"}],
                    "series": [],
                    "errors": [],
                },
                "timestamp": "after-refresh",
                "refreshing": False,
                "progress": {"state": "done", "completed": 1, "total": 1},
            }
        return {
            "payload": self.initial_payload,
            "timestamp": "before-refresh",
            "refreshing": False,
            "progress": {"state": "old", "completed": 0, "total": 1},
        }

    def refresh_full(self, *args, **kwargs):
        self.calls.append(("refresh_full", args, kwargs))
        self.refreshed = True
        return {
            "movies": [{"title": "refreshed movie"}],
            "series": [],
            "errors": [],
        }, None


class _BackgroundRefreshManager:
    def __init__(self):
        self.calls = []
        self.refreshing = False
        self.progress_tracker = _RecordingLatestProgressTracker()

    def is_refreshing(self):
        return self.refreshing

    def refresh_incremental(self, *args, **kwargs):
        self.calls.append(("refresh_incremental", args, kwargs))
        return {"movies": [], "series": [], "errors": []}, None

    def refresh_full(self, *args, **kwargs):
        self.calls.append(("refresh_full", args, kwargs))
        return {"movies": [], "series": [], "errors": []}, None


class _RecordingLatestProgressTracker:
    def __init__(self):
        self.snapshot = {}

    def update(self, **kwargs):
        self.snapshot.update({key: value for key, value in kwargs.items() if value is not None})

    def get_snapshot(self):
        return dict(self.snapshot)


class _RecordingOperationTracker:
    def __init__(self):
        self.started = []
        self.updated = []
        self.finished = []
        self.failed = []

    def start(self, kind, title, summary="", details=None, total=None):
        operation = {
            "id": "operation-1",
            "kind": kind,
            "title": title,
            "summary": summary,
            "details": details or {},
            "total": total,
        }
        self.started.append(operation)
        return operation

    def update(self, operation_id, **kwargs):
        self.updated.append({"operation_id": operation_id, **kwargs})
        return {"id": operation_id, **kwargs}

    def finish(self, operation_id, message="Completato", result=None):
        self.finished.append({"operation_id": operation_id, "message": message, "result": result or {}})
        return {"id": operation_id, "status": "success"}

    def fail(self, operation_id, message, result=None):
        self.failed.append({"operation_id": operation_id, "message": message, "result": result or {}})
        return {"id": operation_id, "status": "error"}


class _RaisingEnrichManager:
    def enrich_item(self, item, force_omdb=False):
        raise RuntimeError("external source unavailable")


class LatestApiHandlerTests(unittest.TestCase):
    def test_latest_snapshot_projects_cached_feed_to_requested_bounds(self):
        cached_movies = [
            {"id": "a-1", "server_id": "a"},
            {"id": "a-2", "server_id": "a"},
            {"id": "b-1", "server_id": "b"},
            {"id": "c-1", "server_id": "c"},
        ]
        cached_series = [
            {"id": "series-a", "server_id": "a"},
            {"id": "series-b", "server_id": "b"},
            {"id": "series-c", "server_id": "c"},
        ]
        manager = _RefreshingSnapshotManager(
            initial_payload={
                "movies": cached_movies,
                "series": cached_series,
                "errors": [],
            }
        )

        with patch("emby_latest.get_manager", return_value=manager), patch(
            "core.config_manager.load_config",
            return_value=({"DATABASE": {"enabled": True}}, True),
        ), patch("core.config_manager._db_enabled", return_value=True), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info"
        ):
            payload, status_code = build_latest_snapshot_payload(
                limit=2,
                per_server_limit=1,
                force=False,
                cache_only=True,
                view="history",
            )

        assert status_code == 200
        assert [item["id"] for item in payload["movies"]] == ["a-1", "b-1"]
        assert [item["id"] for item in payload["series"]] == ["series-a", "series-b"]
        assert cached_movies == [
            {"id": "a-1", "server_id": "a"},
            {"id": "a-2", "server_id": "a"},
            {"id": "b-1", "server_id": "b"},
            {"id": "c-1", "server_id": "c"},
        ]

    def test_latest_snapshot_normalizes_view_aliases(self):
        cases = (
            ("history", "feed"),
            ("", "feed"),
            ("nonsense", "feed"),
            ("batch", "batch"),
        )

        for view, expected_mode in cases:
            with self.subTest(view=view):
                manager = _SnapshotManager()

                with patch("emby_latest.get_manager", return_value=manager), patch(
                    "core.config_manager.load_config",
                    return_value=({"DATABASE": {"ENABLED": True}}, True),
                ), patch("core.config_manager._db_enabled", return_value=True), patch(
                    "emby_latest.jellyseerr._apply_jellyseerr_request_info"
                ):
                    payload, status_code = build_latest_snapshot_payload(
                        limit=10,
                        per_server_limit=5,
                        force=False,
                        cache_only=True,
                        view=view,
                    )

                self.assertEqual(200, status_code)
                self.assertTrue(payload["success"])
                self.assertEqual(f"{expected_mode}-ts", payload["cached_at"])
                self.assertEqual([expected_mode], manager.calls)

    def test_latest_snapshot_force_query_is_rejected_without_refresh(self):
        manager = _RefreshingSnapshotManager(
            initial_payload={"movies": [{"title": "old"}], "series": [], "errors": []}
        )

        payload, status_code = build_latest_snapshot_payload(
            limit=10,
            per_server_limit=5,
            force=True,
            cache_only=False,
            view="batch",
        )

        self.assertEqual(400, status_code)
        self.assertFalse(payload["success"])
        self.assertIn("POST /api/emby/latest/refresh", payload["message"])
        self.assertFalse(manager.refreshed)
        self.assertEqual([], manager.calls)

    def test_latest_snapshot_cache_miss_never_triggers_refresh(self):
        manager = _RefreshingSnapshotManager(initial_payload=None)

        with patch("emby_latest.get_manager", return_value=manager), patch(
            "core.config_manager.load_config",
            return_value=({"DATABASE": {"ENABLED": True}}, True),
        ), patch("core.config_manager._db_enabled", return_value=True):
            payload, status_code = build_latest_snapshot_payload(
                limit=10,
                per_server_limit=5,
                force=False,
                cache_only=False,
                view="batch",
            )

        self.assertEqual(404, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("Nessun dato Pubblicazioni salvato nel DB", payload["message"])
        self.assertFalse(payload["refreshing"])
        self.assertFalse(manager.refreshed)
        self.assertEqual([("snapshot", "batch")], manager.calls)

    def test_latest_snapshot_cache_only_without_data_uses_database_message(self):
        manager = _RefreshingSnapshotManager(initial_payload=None)

        with patch("emby_latest.get_manager", return_value=manager), patch(
            "core.config_manager.load_config",
            return_value=({"DATABASE": {"ENABLED": True}}, True),
        ), patch("core.config_manager._db_enabled", return_value=True):
            payload, status_code = build_latest_snapshot_payload(
                limit=10,
                per_server_limit=5,
                force=False,
                cache_only=True,
                view="history",
            )

        self.assertEqual(404, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("Nessun dato Pubblicazioni salvato nel DB", payload["message"])

    def test_latest_background_refresh_creates_global_operation(self):
        manager = _BackgroundRefreshManager()
        tracker = _RecordingOperationTracker()

        class _ImmediateThread:
            def __init__(self, target, daemon=None):
                self.target = target
                self.daemon = daemon

            def start(self):
                self.target()

        with patch("emby_latest.get_manager", return_value=manager), patch(
            "app_state.get_operation_tracker",
            return_value=tracker,
        ), patch("threading.Thread", _ImmediateThread):
            payload, status_code = build_latest_refresh_payload(
                limit=25,
                per_server_limit=5,
                full_refresh=False,
            )

        self.assertEqual(202, status_code)
        self.assertTrue(payload["success"])
        self.assertEqual("latest_refresh", tracker.started[0]["kind"])
        self.assertEqual("Aggiornamento Pubblicazioni", tracker.started[0]["title"])
        self.assertEqual("Incrementale", tracker.started[0]["summary"])
        self.assertEqual("refresh_incremental", manager.calls[0][0])
        self.assertEqual((25, 5), manager.calls[0][1])
        self.assertIn("progress_tracker", manager.calls[0][2])
        self.assertEqual("operation-1", tracker.finished[-1]["operation_id"])

    def test_latest_background_refresh_redacts_exception_credentials(self):
        secret = "CANARY_LATEST_PASSWORD"
        manager = _BackgroundRefreshManager()
        tracker = _RecordingOperationTracker()

        def fail_refresh(*_args, **_kwargs):
            raise RuntimeError(
                f"postgresql://octohubs:{secret}@database/octohubs"
            )

        manager.refresh_incremental = fail_refresh

        class _StopEvent:
            def is_set(self):
                return False

        def run_worker(target):
            target(_StopEvent())
            return True

        handler_globals = build_latest_refresh_payload.__globals__
        with patch("emby_latest.get_manager", return_value=manager), patch(
            "app_state.get_operation_tracker", return_value=tracker
        ), patch.dict(
            handler_globals,
            {
                "_reserve_latest_refresh_request": lambda _manager: True,
                "_start_latest_refresh_worker": run_worker,
            },
        ), patch.object(handler_globals["logger"], "error") as logged_error:
            payload, status_code = build_latest_refresh_payload(25, 5, False)

        self.assertEqual(202, status_code)
        self.assertTrue(payload["success"])
        logged_error.assert_called_once()
        rendered = "\n".join(str(value) for value in logged_error.call_args.args)
        self.assertNotIn(secret, rendered)
        self.assertIn("RuntimeError", rendered)

    def test_latest_background_refresh_rejects_second_request_before_thread_sets_refreshing(self):
        manager = _BackgroundRefreshManager()
        tracker = _RecordingOperationTracker()
        queued_threads = []

        def _drain_threads():
            for queued_thread in list(queued_threads):
                queued_thread.target()

        self.addCleanup(_drain_threads)

        class _QueuedThread:
            def __init__(self, target, daemon=None):
                self.target = target
                self.daemon = daemon
                queued_threads.append(self)

            def start(self):
                return None

        with patch("emby_latest.get_manager", return_value=manager), patch(
            "app_state.get_operation_tracker",
            return_value=tracker,
        ), patch("threading.Thread", _QueuedThread):
            first_payload, first_status = build_latest_refresh_payload(
                limit=25,
                per_server_limit=5,
                full_refresh=False,
            )
            second_payload, second_status = build_latest_refresh_payload(
                limit=25,
                per_server_limit=5,
                full_refresh=False,
            )

        self.assertEqual(202, first_status)
        self.assertTrue(first_payload["success"])
        self.assertEqual(409, second_status)
        self.assertFalse(second_payload["success"])
        self.assertEqual("Refresh già in corso", second_payload["message"])
        self.assertEqual(1, len(tracker.started))
        self.assertEqual(1, len(queued_threads))

    def test_latest_operation_progress_bridge_updates_global_operation(self):
        latest_progress = _RecordingLatestProgressTracker()
        operation_tracker = _RecordingOperationTracker()
        bridge = make_latest_operation_progress_tracker(
            latest_progress,
            operation_tracker,
            "operation-1",
            full_refresh=False,
            limit=25,
            per_server_limit=5,
        )

        bridge.update(
            state="enriching",
            total=10,
            completed=4,
            message="Arricchimento dati esterni",
        )

        update = operation_tracker.updated[-1]
        self.assertEqual("operation-1", update["operation_id"])
        self.assertEqual("Arricchimento dati esterni", update["message"])
        self.assertEqual(40, update["progress"])
        self.assertEqual(4, update["current"])
        self.assertEqual(10, update["total"])
        self.assertEqual("Arricchimento dati", update["details"]["current_step_label"])
        self.assertEqual("Incrementale", update["details"]["mode"])

    def test_preview_snapshot_handles_malformed_payload_shapes(self):
        cases = (
            ({"template": "{{ title }}", "payload": "bad"}, 200, True, {}),
            ({"template": "{{ title }}", "payload": ["bad"]}, 200, True, {}),
            ({"template": "{{ title }}", "items": "bad"}, 200, True, {}),
            ({"template": 123, "items": {"movie": {"title": "Movie"}}}, 400, False, None),
        )

        for body, expected_status, expected_success, expected_previews in cases:
            with self.subTest(body=body):
                payload, status_code = build_preview_snapshot(body)

                self.assertEqual(expected_status, status_code)
                self.assertEqual(expected_success, payload["success"])
                if expected_previews is not None:
                    self.assertEqual(expected_previews, payload["previews"])
                else:
                    self.assertEqual("Template mancante", payload["message"])

    def test_preview_snapshot_rejects_whitespace_only_template(self):
        for template in ("   ", "\n\t"):
            with self.subTest(template=repr(template)):
                payload, status_code = build_preview_snapshot(
                    {"template": template, "items": {"movie": {"title": "Movie"}}}
                )

                self.assertEqual(400, status_code)
                self.assertFalse(payload["success"])
                self.assertEqual("Template mancante", payload["message"])

    def test_preview_snapshot_supports_all_image_tokens(self):
        item = {
            "title": "Movie",
            "item_type": "movie",
            "image_url": "https://example.test/image.jpg",
            "logo_url": "https://example.test/logo.png",
        }
        cases = (
            ("image_url", "https://example.test/image.jpg"),
            ("logo_url", "https://example.test/logo.png"),
        )

        for token, expected_url in cases:
            with self.subTest(token=token):
                payload, status_code = build_preview_snapshot(
                    {"template": "{{ " + token + " }}\n{{ title }}", "items": {"movie": item}}
                )
                preview = payload["previews"]["movie"]

                self.assertEqual(200, status_code)
                self.assertTrue(payload["success"])
                self.assertTrue(preview["image_enabled"])
                self.assertEqual(expected_url, preview["image_url"])
                self.assertEqual("Movie", preview["message"])

    def test_enrich_snapshot_normalizes_force_omdb_bool(self):
        cases = (
            ("false", False),
            ("0", False),
            ("off", False),
            ("true", True),
            ("1", True),
            ("on", True),
        )

        for value, expected in cases:
            with self.subTest(value=value):
                manager = _RecordingManager()

                with patch("emby_latest.get_manager", return_value=manager):
                    payload, status_code = build_enrich_snapshot(
                        {"item": {"title": "Movie"}, "force_omdb": value}
                    )

                self.assertEqual(200, status_code)
                self.assertTrue(payload["success"])
                self.assertEqual(expected, manager.calls[0]["force_omdb"])
                self.assertIs(expected, payload["item"]["force_omdb"])

    def test_enrich_snapshot_returns_controlled_error_when_manager_fails(self):
        with patch("emby_latest.get_manager", return_value=_RaisingEnrichManager()):
            payload, status_code = build_enrich_snapshot({"item": {"title": "Movie"}})

        self.assertEqual(500, status_code)
        self.assertFalse(payload["success"])
        self.assertIn("Errore enrichment", payload["message"])

    def test_notify_snapshot_normalizes_per_server_limit(self):
        cases = (
            ("abc", 50),
            (-5, 1),
            (9999, 100),
        )

        for value, expected in cases:
            with self.subTest(value=value):
                manager = _RecordingManager()

                with patch("emby_latest.get_manager", return_value=manager):
                    payload, status_code = build_notify_snapshot(
                        {"per_server_limit": value}
                    )

                self.assertEqual(200, status_code)
                self.assertTrue(payload["success"])
                self.assertEqual(expected, manager.calls[0]["per_server_limit"])

    def test_notify_snapshot_does_not_forward_unused_global_limit(self):
        manager = _RecordingManager()

        with patch("emby_latest.get_manager", return_value=manager):
            payload, status_code = build_notify_snapshot(
                {"limit": 1, "per_server_limit": 2}
            )

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        self.assertNotIn("limit", manager.calls[0])

    def test_notify_snapshot_preserves_partial_outcome_without_marking_success(self):
        manager = _RecordingManager()
        manager.send_notifications = lambda **_kwargs: {
            "success": False,
            "status": "partial",
            "message": "Una destinazione non raggiunta",
            "sent": 1,
            "failed": 1,
            "errors": ["failed"],
        }

        with patch("emby_latest.get_manager", return_value=manager):
            payload, status_code = build_notify_snapshot({"per_server_limit": 10})

        self.assertEqual(200, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("partial", payload["status"])


if __name__ == "__main__":
    unittest.main()
