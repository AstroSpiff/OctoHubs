"""Lightweight Jellyseerr refresh for Latest Publications."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_runtime.api_clients_jellyseerr import get_jellyseerr_requests, submit_jellyseerr_request
from emby_runtime.api_clients_ping import _ping_jellyseerr
from emby_runtime.api_clients_tmdb import _fetch_tmdb_payload
from services.latest_jellyseerr import refresh_latest_jellyseerr_requests


class _Backend:
    def __init__(self):
        self.saved = []

    def save_jellyseerr_requests(self, entries):
        self.saved.append(entries)
        return len(entries)


class LatestJellyseerrRefreshTests(unittest.TestCase):
    def test_jellyseerr_client_strips_trailing_base_url_slash_for_request_submission(self):
        calls = []

        class _Response:
            content = b"{}"

            def raise_for_status(self):
                return None

            def json(self):
                return {}

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        config = {
            "JELLYSEERR_URL": "https://jellyseerr.example/",
            "JELLYSEERR_API_KEY": "secret",
        }

        with patch("emby_runtime.api_clients_jellyseerr.requests.post", side_effect=fake_post):
            success, _message, _data = submit_jellyseerr_request(
                {"mediaId": 1, "mediaType": "movie"},
                config,
            )

        self.assertTrue(success)
        self.assertEqual("https://jellyseerr.example/api/v1/request", calls[0][0])

    def test_jellyseerr_client_strips_trailing_base_url_slash_for_request_listing(self):
        calls = []

        class _Response:
            content = b"{}"

            def raise_for_status(self):
                return None

            def json(self):
                return {"results": []}

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        config = {
            "JELLYSEERR_URL": "https://jellyseerr.example/",
            "JELLYSEERR_API_KEY": "secret",
        }

        with patch("emby_runtime.api_clients_jellyseerr.requests.get", side_effect=fake_get):
            requests_data, ok = get_jellyseerr_requests(config, silent=True, return_status=True)

        self.assertTrue(ok)
        self.assertEqual([], requests_data)
        self.assertEqual(
            ["https://jellyseerr.example/api/v1/request"] * 3,
            [call[0] for call in calls],
        )

    def test_jellyseerr_ping_strips_trailing_base_url_slash(self):
        calls = []

        class _Response:
            def raise_for_status(self):
                return None

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        config = {
            "JELLYSEERR_URL": "https://jellyseerr.example/",
            "JELLYSEERR_API_KEY": "secret",
        }

        with patch("emby_runtime.api_clients_ping.requests.get", side_effect=fake_get):
            ok, _message = _ping_jellyseerr(config)

        self.assertTrue(ok)
        self.assertEqual("https://jellyseerr.example/api/v1/request", calls[0][0])

    def test_jellyseerr_tmdb_fetch_strips_trailing_base_url_slash(self):
        calls = []

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"id": 1, "title": "Movie"}

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        config = {
            "JELLYSEERR_URL": "https://jellyseerr.example/",
            "JELLYSEERR_API_KEY": "secret",
        }

        with patch("emby_runtime.api_clients_tmdb.requests.get", side_effect=fake_get):
            payload, media_type = _fetch_tmdb_payload(1, ["movie"], config, {})

        self.assertEqual({"id": 1, "title": "Movie"}, payload)
        self.assertEqual("movie", media_type)
        self.assertEqual("https://jellyseerr.example/api/v1/movie/1", calls[0][0])

    def test_refresh_latest_jellyseerr_requests_saves_latest_index_only(self):
        backend = _Backend()
        config = {
            "JELLYSEERR_URL": "http://jellyseerr.test",
            "JELLYSEERR_API_KEY": "secret",
        }
        requests_data = [
            {
                "id": 101,
                "type": "movie",
                "status": 5,
                "media": {"mediaType": "movie", "tmdbId": 277},
                "requestedBy": {"displayName": "Roy"},
            },
            {
                "id": 102,
                "type": "tv",
                "status": 2,
                "media": {"mediaType": "tv", "tmdbId": 1234},
                "seasonRequests": [{"seasonNumber": 2}],
            },
        ]

        with patch(
            "services.latest_jellyseerr.get_jellyseerr_requests",
            return_value=(requests_data, True),
        ), patch(
            "services.latest_jellyseerr._ensure_db_backend",
            return_value=backend,
        ), patch(
            "services.requests_summary._summarize_requests_for_dashboard",
            side_effect=AssertionError("dashboard summary must not run"),
        ):
            data, status_code = refresh_latest_jellyseerr_requests(config)

        self.assertEqual(200, status_code)
        self.assertTrue(data["success"])
        self.assertEqual({"total": 2, "movies": 1, "tv": 1}, data["counts"])
        self.assertEqual(1, len(backend.saved))
        self.assertEqual(["101", "102"], [entry["request_id"] for entry in backend.saved[0]])

    def test_refresh_latest_jellyseerr_requests_skips_when_not_configured(self):
        backend = _Backend()

        with patch(
            "services.latest_jellyseerr.get_jellyseerr_requests",
            side_effect=AssertionError("Jellyseerr API must not be called"),
        ), patch(
            "services.latest_jellyseerr._ensure_db_backend",
            return_value=backend,
        ):
            data, status_code = refresh_latest_jellyseerr_requests({})

        self.assertEqual(200, status_code)
        self.assertFalse(data["success"])
        self.assertEqual("skipped", data["status"])
        self.assertEqual([], backend.saved)


if __name__ == "__main__":
    unittest.main()
