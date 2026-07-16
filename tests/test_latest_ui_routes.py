"""Latest publications UI route behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app_helpers import _resolve_next_url
from emby_latest.ui_routes import (
    emby_latest_reset_post,
    emby_latest_state_clear_post,
    emby_latest_preset_add_post,
    emby_latest_preset_remove_post,
    emby_latest_notification_settings_post,
    emby_latest_rule_save_post,
    init_emby_latest_ui_routes,
)


class LatestUiRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.flash_messages = []
        init_emby_latest_ui_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
            flash=lambda request, message: self.flash_messages.append(message),
            resolve_next_url=_resolve_next_url,
            load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
            ensure_db_backend=lambda: None,
        )

    def test_resolve_next_url_rejects_protocol_relative_url(self):
        self.assertEqual("/emby", _resolve_next_url("//evil.example/path", "emby_dashboard"))
        self.assertEqual("/emby", _resolve_next_url("https://evil.example/path", "emby_dashboard"))
        self.assertEqual("/emby?tab=latest", _resolve_next_url("/emby?tab=latest", "emby_dashboard"))

    async def test_preset_add_rejects_duplicate_name(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-a",
        }

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings"
        ) as save_settings:
            response = await emby_latest_preset_add_post(
                request=object(),
                latest_preset_name="notifiche",
                latest_preset_template="{title} nuovo",
                latest_preset_id=None,
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("Nome preset già esistente.", self.flash_messages)
        save_settings.assert_not_called()

    async def test_preset_update_rejects_duplicate_name_from_another_preset(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
                {"id": "preset-b", "name": "Cinema", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-b",
        }

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings"
        ) as save_settings:
            response = await emby_latest_preset_add_post(
                request=object(),
                latest_preset_id="preset-b",
                latest_preset_name="NOTIFICHE",
                latest_preset_template="{title} aggiornato",
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("Nome preset già esistente.", self.flash_messages)
        save_settings.assert_not_called()

    async def test_preset_update_rejects_missing_preset_id(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-a",
        }

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings"
        ) as save_settings:
            response = await emby_latest_preset_add_post(
                request=object(),
                latest_preset_id="missing-preset",
                latest_preset_name="Cinema",
                latest_preset_template="{title}",
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("Preset non trovato.", self.flash_messages)
        save_settings.assert_not_called()

    async def test_preset_remove_rejects_preset_used_by_notification_rule(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
                {"id": "preset-b", "name": "Cinema", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-a",
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Regola",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
            ],
        }

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings"
        ) as save_settings:
            response = await emby_latest_preset_remove_post(
                request=object(),
                latest_preset_id="preset-a",
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertIn(
            "Preset usato da 1 regola. Modifica o elimina prima la regola collegata.",
            self.flash_messages,
        )
        save_settings.assert_not_called()

    async def test_preset_remove_clears_active_id_when_last_active_preset_is_removed(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-a",
            "NOTIFICATION_RULES": [],
        }
        saved_settings = []

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings",
            side_effect=lambda latest_settings: saved_settings.append(latest_settings),
        ):
            response = await emby_latest_preset_remove_post(
                request=object(),
                latest_preset_id="preset-a",
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertTrue(saved_settings)
        self.assertEqual([], saved_settings[-1]["PRESETS"])
        self.assertEqual("", saved_settings[-1]["ACTIVE_PRESET_ID"])

    async def test_rule_save_deduplicates_server_ids(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
            ],
            "NOTIFICATION_RULES": [],
        }
        saved_settings = []
        config = {
            "DATABASE": {"ENABLED": True},
            "EMBY": {
                "SERVERS": [
                    {"id": "server-a", "name": "Server A"},
                    {"id": "server-b", "name": "Server B"},
                ]
            },
        }
        init_emby_latest_ui_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
            flash=lambda request, message: self.flash_messages.append(message),
            resolve_next_url=_resolve_next_url,
            load_config=lambda: (config, True),
            ensure_db_backend=lambda: None,
        )

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings",
            side_effect=lambda latest_settings: saved_settings.append(latest_settings),
        ), patch(
            "emby_latest.ui_routes._load_telegram_settings",
            return_value={"PRESETS": [{"id": "telegram-a", "name": "Telegram"}]},
        ):
            response = await emby_latest_rule_save_post(
                request=object(),
                latest_rule_name="Regola",
                latest_rule_servers=["server-a", "server-a", "server-b"],
                latest_rule_preset="preset-a",
                latest_rule_telegram="telegram-a",
                latest_rule_id=None,
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertTrue(saved_settings)
        rules = saved_settings[-1]["NOTIFICATION_RULES"]
        self.assertEqual(["server-a", "server-b"], rules[0]["server_ids"])

    async def test_rule_update_rejects_missing_rule_id(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
            ],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Regola A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
            ],
        }
        config = {
            "DATABASE": {"ENABLED": True},
            "EMBY": {"SERVERS": [{"id": "server-a", "name": "Server A"}]},
        }
        init_emby_latest_ui_routes(
            require_auth=lambda request: True,
            validate_csrf=lambda request, token: True,
            flash=lambda request, message: self.flash_messages.append(message),
            resolve_next_url=_resolve_next_url,
            load_config=lambda: (config, True),
            ensure_db_backend=lambda: None,
        )

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings"
        ) as save_settings, patch(
            "emby_latest.ui_routes._load_telegram_settings",
            return_value={"PRESETS": [{"id": "telegram-a", "name": "Telegram"}]},
        ):
            response = await emby_latest_rule_save_post(
                request=object(),
                latest_rule_name="Regola B",
                latest_rule_servers=["server-a"],
                latest_rule_preset="preset-a",
                latest_rule_telegram="telegram-a",
                latest_rule_id="missing-rule",
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertIn("Regola non trovata.", self.flash_messages)
        save_settings.assert_not_called()

    async def test_notification_settings_keep_only_valid_unique_references(self):
        settings = {
            "PRESETS": [
                {"id": "preset-a", "name": "Notifiche", "template": "{title}"},
                {"id": "preset-b", "name": "Cinema", "template": "{title}"},
            ],
            "ACTIVE_PRESET_ID": "preset-b",
            "TELEGRAM_PRESET_IDS": ["telegram-old"],
        }
        saved_settings = []

        with patch("emby_latest.settings._load_latest_settings", return_value=settings), patch(
            "emby_latest.settings._save_latest_settings",
            side_effect=lambda latest_settings: saved_settings.append(latest_settings),
        ), patch(
            "emby_latest.ui_routes._load_telegram_settings",
            return_value={"PRESETS": [{"id": "telegram-a", "name": "Telegram A"}]},
        ):
            response = await emby_latest_notification_settings_post(
                request=object(),
                latest_active_preset_id="missing-preset",
                latest_telegram_presets=["telegram-a", "missing-telegram", "telegram-a", ""],
                csrf_token="ok",
                next_param="/emby?tab=latest",
            )

        self.assertEqual(303, response.status_code)
        self.assertTrue(saved_settings)
        self.assertEqual("preset-b", saved_settings[-1]["ACTIVE_PRESET_ID"])
        self.assertEqual(["telegram-a"], saved_settings[-1]["TELEGRAM_PRESET_IDS"])

    async def test_latest_maintenance_routes_use_safe_next_url(self):
        with patch("emby_latest.db_state.clear_state"), patch(
            "emby_latest.settings._clear_latest_state"
        ):
            response = await emby_latest_state_clear_post(
                request=object(),
                csrf_token="ok",
                next_param="https://evil.example/path",
            )

        self.assertEqual("/emby", response.headers.get("location"))

        with patch("emby_latest.settings._reset_latest_cache_state"):
            response = await emby_latest_reset_post(
                request=object(),
                csrf_token="ok",
                next_param="//evil.example/path",
            )

        self.assertEqual("/emby", response.headers.get("location"))


if __name__ == "__main__":
    unittest.main()
