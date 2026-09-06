"""Trakt client token refresh tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from unittest.mock import Mock, patch


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return dict(self._payload)


class TraktClientRefreshTests(unittest.TestCase):
    def test_latest_enrichment_requests_never_follow_redirects(self):
        from emby_latest import enrichment_sources

        enrichment_sources._TRAKT_ID_CACHE.clear()
        enrichment_sources._TRAKT_RATING_CACHE.clear()
        identifier_response = Mock()
        identifier_response.json.return_value = [
            {"movie": {"ids": {"slug": "movie-slug"}}}
        ]
        rating_response = Mock()
        rating_response.json.return_value = {"rating": 8.2, "votes": 42}

        with patch(
            "emby_latest.enrichment_sources.requests.get",
            side_effect=[identifier_response, rating_response],
        ) as get:
            result = enrichment_sources._fetch_trakt_rating(
                "",
                "movie",
                "CANARY_CLIENT_ID",
                tmdb_id="123",
            )

        self.assertEqual("8.2", result["trakt_rating"])
        self.assertEqual(2, get.call_count)
        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in get.call_args_list))

    def test_expiring_token_is_refreshed_and_persisted_before_request(self):
        from core.integrations import TraktClient

        persisted_updates: list[dict] = []
        request_headers: list[dict] = []
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        def fake_post(url, *, headers, json, allow_redirects, timeout):
            self.assertEqual("https://api.trakt.tv/oauth/token", url)
            self.assertEqual("refresh_token", json["grant_type"])
            self.assertEqual("client-abc", json["client_id"])
            self.assertEqual("secret-def", json["client_secret"])
            self.assertEqual("refresh-old", json["refresh_token"])
            self.assertIs(allow_redirects, False)
            return _FakeResponse(
                200,
                {
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "expires_in": 3600,
                },
            )

        def fake_request(method, url, *, headers, timeout, **kwargs):
            request_headers.append(dict(headers))
            return _FakeResponse(200, {})

        client = TraktClient(
            client_id="client-abc",
            access_token="access-old",
            client_secret="secret-def",
            refresh_token="refresh-old",
            expires_at=expired_at,
            on_token_update=persisted_updates.append,
        )

        with (
            patch("core.integrations.requests.post", side_effect=fake_post),
            patch("core.integrations.requests.request", side_effect=fake_request),
        ):
            self.assertTrue(client.ping())

        self.assertEqual("Bearer access-new", request_headers[0]["Authorization"])
        self.assertEqual("access-new", persisted_updates[0]["ACCESS_TOKEN"])
        self.assertEqual("refresh-new", persisted_updates[0]["REFRESH_TOKEN"])
        self.assertTrue(persisted_updates[0]["EXPIRES_AT"])

    def test_authenticated_request_does_not_follow_cross_origin_redirect(self):
        from core.integrations import TraktAPIError, TraktClient

        sink_hits = []

        class SinkHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                sink_hits.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args):
                return

        sink = ThreadingHTTPServer(("127.0.0.1", 0), SinkHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(307)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{sink.server_port}/credential-sink",
                )
                self.end_headers()

            def log_message(self, *_args):
                return

        source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (sink, source)
        ]
        for thread in threads:
            thread.start()
        try:
            client = TraktClient("client-id", "CANARY_ACCESS_TOKEN")
            client.BASE_URL = f"http://127.0.0.1:{source.server_port}"
            with self.assertRaisesRegex(TraktAPIError, "Redirect Trakt rifiutato"):
                client.ping()
            self.assertEqual([], sink_hits)
        finally:
            source.shutdown()
            sink.shutdown()
            source.server_close()
            sink.server_close()

    def test_refresh_and_unauthorized_errors_do_not_expose_upstream_body(self):
        from core.integrations import TraktAPIError, TraktClient

        canary = "CANARY_TRAKT_RESPONSE_SECRET"
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        response = _FakeResponse(
            401,
            {"error_description": canary},
            text=canary,
        )
        client = TraktClient(
            "client-id",
            "access-token",
            client_secret="client-secret",
            refresh_token="refresh-token",
            expires_at=expired_at,
        )

        with patch("core.integrations.requests.post", return_value=response) as post:
            with self.assertRaises(TraktAPIError) as raised:
                client.ping()

        self.assertNotIn(canary, str(raised.exception))
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)

    def test_expired_token_refresh_is_single_flight_across_threads(self):
        from core.integrations import TraktClient

        calls = 0
        entered = threading.Event()
        release = threading.Event()

        def fake_post(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            self.assertTrue(release.wait(2))
            return _FakeResponse(200, {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
            })

        client = TraktClient(
            "client",
            "access-old",
            client_secret="secret",
            refresh_token="refresh-old",
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            on_token_update=lambda _update: True,
        )
        threads = [threading.Thread(target=client._ensure_valid_token) for _ in range(2)]
        with patch("core.integrations.requests.post", side_effect=fake_post):
            for thread in threads:
                thread.start()
            self.assertTrue(entered.wait(2))
            release.set()
            for thread in threads:
                thread.join(2)

        self.assertEqual(1, calls)
        self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_stale_refresh_cannot_restore_disabled_trakt_configuration(self):
        from core import config_manager
        from core.integrations import _persist_trakt_token_update, _trakt_settings_revision

        old = {
            "ENABLED": True,
            "CLIENT_ID": "client",
            "CLIENT_SECRET": "secret",
            "ACCESS_TOKEN": "old-access",
            "REFRESH_TOKEN": "old-refresh",
            "EXPIRES_AT": "1",
        }
        disabled = {**old, "ENABLED": False, "ACCESS_TOKEN": "", "REFRESH_TOKEN": ""}
        storage = Mock()
        storage.load_app_settings.return_value = {"TRAKT": disabled}
        previous = config_manager._ACTIVE_CONFIG
        config_manager._ACTIVE_CONFIG = {"TRAKT": old}
        try:
            with patch("core.integrations._ensure_db_backend", return_value=storage):
                accepted = _persist_trakt_token_update(
                    {"ACCESS_TOKEN": "stale-new", "REFRESH_TOKEN": "stale-refresh"},
                    expected_revision=_trakt_settings_revision(old),
                )
        finally:
            config_manager._ACTIVE_CONFIG = previous

        self.assertFalse(accepted)
        storage.save_app_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
