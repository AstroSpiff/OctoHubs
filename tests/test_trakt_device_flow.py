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

    def test_manual_token_set_replaces_access_refresh_and_expiry_together(self):
        from services.configuration_settings import build_trakt_settings_payload

        payload = build_trakt_settings_payload(
            {
                "ACCESS_TOKEN": "old-access",
                "REFRESH_TOKEN": "old-refresh",
                "EXPIRES_AT": "2030-01-01T00:00:00+00:00",
            },
            client_id="client",
            client_secret="secret",
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at="2036-01-01T00:00:00+02:00",
            enabled=True,
        )

        self.assertEqual("new-access", payload["ACCESS_TOKEN"])
        self.assertEqual("new-refresh", payload["REFRESH_TOKEN"])
        self.assertEqual("2035-12-31T22:00:00+00:00", payload["EXPIRES_AT"])

    def test_manual_token_set_rejects_partial_or_naive_credentials(self):
        from services.configuration_settings import build_trakt_settings_payload

        with self.assertRaisesRegex(ValueError, "incompleto"):
            build_trakt_settings_payload(
                {},
                client_id="client",
                client_secret="secret",
                access_token="access-only",
                enabled=True,
            )

    def test_changing_oauth_client_invalidates_tokens_without_a_complete_replacement(self):
        from services.configuration_settings import build_trakt_settings_payload

        payload = build_trakt_settings_payload(
            {
                "CLIENT_ID": "old-client",
                "CLIENT_SECRET": "old-secret",
                "ACCESS_TOKEN": "old-access",
                "REFRESH_TOKEN": "old-refresh",
                "EXPIRES_AT": "2030-01-01T00:00:00+00:00",
                "ENABLED": True,
            },
            client_id="new-client",
            client_secret="new-secret",
            access_token="",
            enabled=True,
        )

        self.assertFalse(payload["ENABLED"])
        self.assertNotIn("ACCESS_TOKEN", payload)
        self.assertNotIn("REFRESH_TOKEN", payload)
        self.assertNotIn("EXPIRES_AT", payload)
        with self.assertRaisesRegex(ValueError, "fuso orario"):
            build_trakt_settings_payload(
                {},
                client_id="client",
                client_secret="secret",
                access_token="access",
                refresh_token="refresh",
                expires_at="2036-01-01T00:00:00",
                enabled=True,
            )

    def test_device_poll_persists_refresh_token_and_client_secret(self):
        from services.manager import _build_trakt_device_poll_snapshot, _trakt_config_revision

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
                    "config_revision": _trakt_config_revision({}),
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
        from services.manager import _build_trakt_device_poll_snapshot, _trakt_config_revision

        saved_settings: dict = {}

        trakt = {"CLIENT_ID": "client-saved", "CLIENT_SECRET": "secret-saved"}
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
                return_value={"TRAKT": trakt},
            ),
            patch("services.manager._save_app_settings_snapshot", side_effect=lambda settings: saved_settings.update(settings) or True),
            patch("core.config_manager.load_config", return_value=({}, True)),
        ):
            payload, status_code = _build_trakt_device_poll_snapshot(
                {
                    "client_id": "client-saved",
                    "client_secret": "",
                    "device_code": "device-xyz",
                    "config_revision": _trakt_config_revision(trakt),
                }
            )

        self.assertEqual(200, status_code)
        self.assertEqual("authorized", payload["status"])
        self.assertEqual("secret-saved", post.call_args.kwargs["json"]["client_secret"])
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)
        self.assertEqual("secret-saved", saved_settings["TRAKT"]["CLIENT_SECRET"])

    def test_stale_device_poll_cannot_overwrite_newer_credentials(self):
        from services.manager import _build_trakt_device_poll_snapshot, _trakt_config_revision

        old = {"CLIENT_ID": "old-client", "CLIENT_SECRET": "old-secret"}
        current = {"CLIENT_ID": "new-client", "CLIENT_SECRET": "new-secret"}
        with (
            patch("services.manager._load_app_settings_snapshot", return_value={"TRAKT": current}),
            patch("services.manager.requests.post") as post,
            patch("services.manager._save_app_settings_snapshot") as save,
        ):
            payload, status_code = _build_trakt_device_poll_snapshot({
                "client_id": "old-client",
                "client_secret": "old-secret",
                "device_code": "device-xyz",
                "config_revision": _trakt_config_revision(old),
            })

        self.assertEqual(409, status_code)
        self.assertFalse(payload["success"])
        post.assert_not_called()
        save.assert_not_called()

    def test_clear_publishes_the_committed_disabled_trakt_snapshot(self):
        from core import config_manager
        from services.manager import _build_trakt_clear_snapshot

        saved_settings: dict = {}

        with (
            patch.object(
                config_manager,
                "_ACTIVE_CONFIG",
                {"TRAKT": {"ENABLED": True, "CLIENT_ID": "client", "ACCESS_TOKEN": "token"}},
            ),
            patch(
                "services.manager._load_app_settings_snapshot",
                return_value={"TRAKT": {"ENABLED": True, "CLIENT_ID": "client", "ACCESS_TOKEN": "token"}},
            ),
            patch(
                "services.manager._save_app_settings_snapshot",
                side_effect=lambda settings: saved_settings.update(settings) or True,
            ),
        ):
            payload, status_code = _build_trakt_clear_snapshot()

            self.assertEqual(status_code, 200)
            self.assertTrue(payload["success"])
            self.assertFalse(saved_settings["TRAKT"]["ENABLED"])
            self.assertEqual(saved_settings["TRAKT"]["ACCESS_TOKEN"], "")
            self.assertEqual(saved_settings["TRAKT"]["REFRESH_TOKEN"], "")
            self.assertEqual(saved_settings["TRAKT"]["EXPIRES_AT"], "")
            self.assertFalse(config_manager._ACTIVE_CONFIG["TRAKT"]["ENABLED"])
            self.assertEqual(config_manager._ACTIVE_CONFIG["TRAKT"]["ACCESS_TOKEN"], "")


if __name__ == "__main__":
    unittest.main()
