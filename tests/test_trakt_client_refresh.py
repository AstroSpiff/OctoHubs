"""Trakt client token refresh tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return dict(self._payload)


class TraktClientRefreshTests(unittest.TestCase):
    def test_expiring_token_is_refreshed_and_persisted_before_request(self):
        from core.integrations import TraktClient

        persisted_updates: list[dict] = []
        request_headers: list[dict] = []
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

        def fake_post(url, *, headers, json, timeout):
            self.assertEqual("https://api.trakt.tv/oauth/token", url)
            self.assertEqual("refresh_token", json["grant_type"])
            self.assertEqual("client-abc", json["client_id"])
            self.assertEqual("secret-def", json["client_secret"])
            self.assertEqual("refresh-old", json["refresh_token"])
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


if __name__ == "__main__":
    unittest.main()
