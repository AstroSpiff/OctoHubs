"""Behavior tests for the React-facing Latest Publications configuration API."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_latest.configuration_api import (
    build_latest_configuration_snapshot,
    remove_latest_preset,
    save_latest_preset,
    save_latest_rule,
)


class LatestConfigurationApiTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "DATABASE": {"ENABLED": True},
            "EMBY": {
                "SERVERS": [
                    {"id": "green", "alias": "Green", "icon": "fa-server", "icon_color": "#19a36f"},
                    {"id": "purple", "name": "Purple"},
                ]
            },
        }
        self.settings = {
            "SETTINGS": {"max_movies": 100, "max_series": 100},
            "PRESETS": [{"id": "preset-1", "name": "Base", "template": "{{ title }}"}],
            "ACTIVE_PRESET_ID": "preset-1",
            "TELEGRAM_PRESET_IDS": [],
            "NOTIFICATION_RULES": [],
        }
        self.telegram = {"PRESETS": [{"id": "telegram-1", "name": "Gruppo" , "bot_token": "must-not-leak"}]}

    def _patches(self):
        return (
            patch("emby_latest.configuration_api.load_config", return_value=(self.config, True)),
            patch("emby_latest.configuration_api._db_enabled", return_value=True),
            patch("emby_latest.configuration_api.latest_settings._load_latest_settings", return_value=self.settings),
            patch("emby_latest.configuration_api._load_telegram_settings", return_value=self.telegram),
        )

    def test_snapshot_exposes_only_ui_safe_server_and_telegram_fields(self):
        with self._patches()[0], self._patches()[1], self._patches()[2], self._patches()[3]:
            payload, status = build_latest_configuration_snapshot()

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual("Green", payload["servers"][0]["name"])
        self.assertEqual({"id": "telegram-1", "name": "Gruppo"}, payload["telegram_presets"][0])
        self.assertNotIn("bot_token", payload["telegram_presets"][0])

    def test_save_preset_updates_the_active_preset_and_returns_fresh_snapshot(self):
        save_calls = []
        patchers = self._patches()
        with patchers[0], patchers[1], patchers[2], patchers[3], patch(
            "emby_latest.configuration_api.latest_settings._save_latest_settings",
            side_effect=lambda value: save_calls.append(value.copy()),
        ):
            payload, status = save_latest_preset({"id": "preset-1", "name": "Base", "template": "<b>{{ title }}</b>"})

        self.assertEqual(200, status)
        self.assertEqual("Preset notifica aggiornato", payload["message"])
        self.assertEqual("preset-1", self.settings["ACTIVE_PRESET_ID"])
        self.assertEqual("<b>{{ title }}</b>", self.settings["PRESETS"][0]["template"])
        self.assertTrue(save_calls)

    def test_preset_cannot_be_removed_while_a_rule_references_it(self):
        self.settings["NOTIFICATION_RULES"] = [{"id": "rule-1", "preset_id": "preset-1"}]
        patchers = self._patches()
        with patchers[0], patchers[1], patchers[2], patchers[3]:
            payload, status = remove_latest_preset("preset-1")

        self.assertEqual(400, status)
        self.assertIn("Preset usato da 1 regola", payload["message"])

    def test_rule_rejects_unknown_telegram_destination(self):
        patchers = self._patches()
        with patchers[0], patchers[1], patchers[2], patchers[3]:
            payload, status = save_latest_rule({
                "name": "Green",
                "server_ids": ["green"],
                "preset_id": "preset-1",
                "telegram_config_id": "missing",
            })

        self.assertEqual(400, status)
        self.assertEqual("Destinazione Telegram non valida", payload["message"])


if __name__ == "__main__":
    unittest.main()
