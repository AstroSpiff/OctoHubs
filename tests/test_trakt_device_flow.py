"""Trakt device-flow persistence tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return dict(self._payload)


class TraktDeviceFlowTests(unittest.TestCase):
    def test_settings_payload_preserves_existing_secret_and_refresh(self):
        from services.configuration_settings import build_trakt_settings_payload

        payload = build_trakt_settings_payload(
            {
                "CLIENT_ID": "client-existing",
                "CLIENT_SECRET": "secret-existing",
                "ACCESS_TOKEN": "access-existing",
                "REFRESH_TOKEN": "refresh-existing",
                "EXPIRES_AT": "2026-01-01T00:00:00+00:00",
            },
            client_id="client-existing",
            client_secret="",
            access_token="",
            enabled="",
        )

        self.assertEqual("secret-existing", payload["CLIENT_SECRET"])
        self.assertEqual("refresh-existing", payload["REFRESH_TOKEN"])
        self.assertEqual("access-existing", payload["ACCESS_TOKEN"])
        self.assertIs(payload["ENABLED"], True)

    def test_device_poll_persists_refresh_token_and_client_secret(self):
        from services.manager import _build_trakt_device_poll_snapshot

        saved_settings: dict = {}

        def save_settings(settings):
            saved_settings.update(settings)
            return True

        with (
            patch(
                "services.manager.requests.post",
                return_value=_FakeResponse(
                    200,
                    {
                        "access_token": "access-123",
                        "refresh_token": "refresh-456",
                        "expires_in": 3600,
                    },
                ),
            ),
            patch("services.manager._load_app_settings_snapshot", return_value={"TRAKT": {}}),
            patch("services.manager._save_app_settings_snapshot", side_effect=save_settings),
            patch("core.config_manager.load_config", return_value=({}, True)),
        ):
            payload, status_code = _build_trakt_device_poll_snapshot(
                {
                    "client_id": "client-abc",
                    "client_secret": "secret-def",
                    "device_code": "device-xyz",
                }
            )

        self.assertEqual(200, status_code)
        self.assertEqual("authorized", payload["status"])
        self.assertNotIn("access_token", payload)
        trakt = saved_settings["TRAKT"]
        self.assertEqual("client-abc", trakt["CLIENT_ID"])
        self.assertEqual("secret-def", trakt["CLIENT_SECRET"])
        self.assertEqual("access-123", trakt["ACCESS_TOKEN"])
        self.assertEqual("refresh-456", trakt["REFRESH_TOKEN"])
        self.assertIs(trakt["ENABLED"], True)

    def test_device_poll_reuses_the_saved_client_secret_when_the_browser_omits_it(self):
        from services.manager import _build_trakt_device_poll_snapshot

        saved_settings: dict = {}

        with (
            patch(
                "services.manager.requests.post",
                return_value=_FakeResponse(
                    200,
                    {
                        "access_token": "access-123",
                        "refresh_token": "refresh-456",
                        "expires_in": 3600,
                    },
                ),
            ) as post,
            patch(
                "services.manager._load_app_settings_snapshot",
                return_value={"TRAKT": {"CLIENT_ID": "client-saved", "CLIENT_SECRET": "secret-saved"}},
            ),
            patch("services.manager._save_app_settings_snapshot", side_effect=lambda settings: saved_settings.update(settings) or True),
            patch("core.config_manager.load_config", return_value=({}, True)),
        ):
            payload, status_code = _build_trakt_device_poll_snapshot(
                {"client_id": "client-saved", "client_secret": "", "device_code": "device-xyz"}
            )

        self.assertEqual(200, status_code)
        self.assertEqual("authorized", payload["status"])
        self.assertEqual("secret-saved", post.call_args.kwargs["json"]["client_secret"])
        self.assertEqual("secret-saved", saved_settings["TRAKT"]["CLIENT_SECRET"])


if __name__ == "__main__":
    unittest.main()
