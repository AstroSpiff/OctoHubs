"""Latest publications settings normalization."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_latest.settings import (
    _load_latest_settings,
    _normalize_latest_notification_rules,
    _prepare_latest_notification_rules,
    _save_latest_settings,
)


class LatestSettingsTests(unittest.TestCase):
    def test_load_settings_replaces_stale_active_preset_with_existing_preset(self):
        stored = {
            "EMBY_LATEST": {
                "PRESETS": [
                    {"id": "preset-a", "name": "A", "template": "{title}"},
                ],
                "ACTIVE_PRESET_ID": "missing-preset",
            }
        }

        with patch("services.manager._load_app_settings_snapshot", return_value=stored):
            settings = _load_latest_settings()

        self.assertEqual(settings["ACTIVE_PRESET_ID"], "preset-a")

    def test_save_settings_replaces_invalid_active_preset_with_existing_preset(self):
        saved = {}

        with patch("services.manager._load_app_settings_snapshot", return_value={}), patch(
            "services.manager._save_app_settings_snapshot",
            side_effect=lambda payload: saved.update(payload),
        ):
            _save_latest_settings(
                {
                    "PRESETS": [
                        {"id": "preset-a", "name": "A", "template": "{title}"},
                    ],
                    "ACTIVE_PRESET_ID": "missing-preset",
                }
            )

        latest = saved["EMBY_LATEST"]
        self.assertEqual(latest["ACTIVE_PRESET_ID"], "preset-a")

    def test_notification_rule_enabled_normalizes_false_strings(self):
        false_values = ("0", "false", "False", "no", "off")

        for value in false_values:
            with self.subTest(value=value):
                rules = _normalize_latest_notification_rules(
                    [{"name": "Regola", "enabled": value}]
                )

                self.assertEqual(False, rules[0]["enabled"])

    def test_notification_rule_server_ids_are_trimmed_and_deduplicated(self):
        rules = _normalize_latest_notification_rules(
            [
                {
                    "name": "Regola",
                    "server_ids": [" server-a ", "server-a", "server-b", "", None],
                }
            ]
        )

        self.assertEqual(["server-a", "server-b"], rules[0]["server_ids"])

    def test_load_settings_deduplicates_telegram_preset_ids(self):
        stored = {
            "EMBY_LATEST": {
                "TELEGRAM_PRESET_IDS": [" telegram-a ", "telegram-a", "", None, "telegram-b"],
            }
        }

        with patch("services.manager._load_app_settings_snapshot", return_value=stored):
            settings = _load_latest_settings()

        self.assertEqual(["telegram-a", "telegram-b"], settings["TELEGRAM_PRESET_IDS"])

    def test_save_settings_deduplicates_telegram_preset_ids(self):
        saved = {}

        with patch("services.manager._load_app_settings_snapshot", return_value={}), patch(
            "services.manager._save_app_settings_snapshot",
            side_effect=lambda payload: saved.update(payload),
        ):
            _save_latest_settings(
                {
                    "TELEGRAM_PRESET_IDS": [" telegram-a ", "telegram-a", "", None, "telegram-b"],
                }
            )

        latest = saved["EMBY_LATEST"]
        self.assertEqual(["telegram-a", "telegram-b"], latest["TELEGRAM_PRESET_IDS"])

    def test_notification_rule_view_uses_normalized_server_ids(self):
        rules = [
            {
                "id": "rule-a",
                "name": "Regola",
                "enabled": True,
                "server_ids": ["server-a", " server-b ", "server-a"],
                "preset_id": "preset-a",
                "telegram_config_id": "telegram-a",
            }
        ]

        views = _prepare_latest_notification_rules(
            rules,
            servers=[
                {"id": "server-a", "name": "Server A"},
                {"id": "server-b", "name": "Server B"},
            ],
            presets=[{"id": "preset-a", "name": "Preset"}],
            telegram_presets=[{"id": "telegram-a", "name": "Telegram"}],
        )

        self.assertEqual(["server-a", "server-b"], views[0]["server_ids"])
        self.assertEqual(["Server A", "Server B"], views[0]["server_names"])
        self.assertEqual([], views[0]["missing_servers"])
        self.assertFalse(views[0]["has_missing"])

    def test_load_settings_falls_back_for_invalid_numeric_values(self):
        stored = {
            "EMBY_LATEST": {
                "SETTINGS": {
                    "batch_gap_minutes": "abc",
                    "max_movies": "abc",
                    "max_series": -10,
                    "retention_days": None,
                    "max_versions": "",
                    "batch_fetch_limit": "bad",
                    "latest_cache_seconds": -5,
                }
            }
        }

        with patch("services.manager._load_app_settings_snapshot", return_value=stored):
            settings = _load_latest_settings()["SETTINGS"]

        self.assertEqual(settings["batch_gap_minutes"], 180)
        self.assertEqual(settings["max_movies"], 50)
        self.assertEqual(settings["max_series"], 25)
        self.assertEqual(settings["retention_days"], 90)
        self.assertEqual(settings["max_versions"], 6)
        self.assertEqual(settings["batch_fetch_limit"], 1000)
        self.assertEqual(settings["latest_cache_seconds"], 60)

    def test_save_settings_persists_normalized_numeric_values(self):
        saved = {}

        with patch("services.manager._load_app_settings_snapshot", return_value={}), patch(
            "services.manager._save_app_settings_snapshot",
            side_effect=lambda payload: saved.update(payload),
        ):
            _save_latest_settings(
                {
                    "SETTINGS": {
                        "batch_gap_minutes": "abc",
                        "max_movies": "999",
                        "max_series": "-4",
                        "retention_days": None,
                        "max_versions": "",
                        "batch_fetch_limit": "bad",
                        "latest_cache_seconds": -5,
                    },
                    "PRESETS": [
                        {"id": "preset-a", "name": "A", "template": "{title}"},
                    ],
                    "ACTIVE_PRESET_ID": "preset-a",
                }
            )

        settings = saved["EMBY_LATEST"]["SETTINGS"]
        self.assertEqual(settings["batch_gap_minutes"], 180)
        self.assertEqual(settings["max_movies"], 50)
        self.assertEqual(settings["max_series"], 25)
        self.assertEqual(settings["retention_days"], 90)
        self.assertEqual(settings["max_versions"], 6)
        self.assertEqual(settings["batch_fetch_limit"], 1000)
        self.assertEqual(settings["latest_cache_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
