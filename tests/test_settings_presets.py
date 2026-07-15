"""Saved settings preset naming rules."""

from __future__ import annotations

import unittest

from emby_users.settings_presets import SettingsPresetManager


class _Storage:
    def __init__(self):
        self.values = {}

    def get_keys_by_prefix(self, prefix):
        return [key for key in self.values if key.startswith(prefix)]

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value

    def delete_key(self, key):
        self.values.pop(key, None)


class _SettingsManager:
    def _normalize_settings_payload(self, settings, protect_fields=True):
        return dict(settings or {})

    def get_settings_schema(self):
        return {"schema_version": 1}


class SettingsPresetNamingTests(unittest.TestCase):
    def setUp(self):
        self.manager = SettingsPresetManager(_Storage(), _SettingsManager())

    def test_new_preset_rejects_existing_label(self):
        created = self.manager.save_preset("Cinema", {"config": {"Theme": "dark"}})
        self.assertTrue(created["ok"])

        duplicate = self.manager.save_preset(" cinema ", {"config": {"Theme": "light"}})

        self.assertFalse(duplicate["ok"])
        self.assertEqual(duplicate["error"], "Nome preset gia esistente")
        self.assertEqual(len(self.manager.list_presets()), 1)

    def test_existing_preset_can_be_renamed_to_a_free_label(self):
        created = self.manager.save_preset("Cinema", {"config": {"Theme": "dark"}})
        preset_id = created["preset"]["id"]

        updated = self.manager.save_preset("Cinema sera", {"config": {"Theme": "dark"}}, preset_id=preset_id)

        self.assertTrue(updated["ok"])
        self.assertEqual(updated["preset"]["id"], preset_id)
        self.assertEqual(updated["preset"]["label"], "Cinema sera")

    def test_existing_preset_rejects_rename_to_another_preset_label(self):
        first = self.manager.save_preset("Cinema", {"config": {"Theme": "dark"}})
        self.manager.save_preset("Kids", {"policy": {"EnableLiveTv": False}})

        renamed = self.manager.save_preset(
            "kids",
            {"config": {"Theme": "dark"}},
            preset_id=first["preset"]["id"],
        )

        self.assertFalse(renamed["ok"])
        self.assertEqual(renamed["error"], "Nome preset gia esistente")

    def test_duplicate_preset_rejects_existing_label(self):
        first = self.manager.save_preset("Cinema", {"config": {"Theme": "dark"}})
        self.manager.save_preset("Kids", {"policy": {"EnableLiveTv": False}})

        duplicated = self.manager.duplicate_preset(first["preset"]["id"], "Kids")

        self.assertFalse(duplicated["ok"])
        self.assertEqual(duplicated["error"], "Nome preset gia esistente")


if __name__ == "__main__":
    unittest.main()
