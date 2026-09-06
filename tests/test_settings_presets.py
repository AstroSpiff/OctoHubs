"""Saved settings preset naming rules."""

from __future__ import annotations

import threading
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


class _BlockingStorage(_Storage):
    def __init__(self):
        super().__init__()
        self.block_set = False
        self.set_entered = threading.Event()
        self.release_set = threading.Event()
        self.delete_entered = threading.Event()

    def set_key_value(self, key, value):
        if self.block_set:
            self.set_entered.set()
            self.release_set.wait(timeout=2)
        super().set_key_value(key, value)

    def delete_key(self, key):
        self.delete_entered.set()
        super().delete_key(key)


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

    def test_update_does_not_recreate_a_missing_preset(self):
        result = self.manager.save_preset(
            "Cinema",
            {"config": {"Theme": "dark"}},
            preset_id="removed-preset",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Preset non trovato")
        self.assertIsNone(self.manager.get_preset("removed-preset"))

    def test_update_and_delete_are_serialized_without_resurrection(self):
        storage = _BlockingStorage()
        manager = SettingsPresetManager(storage, _SettingsManager())
        created = manager.save_preset("Cinema", {"config": {"Theme": "dark"}})
        preset_id = created["preset"]["id"]
        results = {}
        delete_attempted = threading.Event()
        storage.block_set = True

        update_thread = threading.Thread(
            target=lambda: results.setdefault(
                "update",
                manager.save_preset(
                    "Cinema sera",
                    {"config": {"Theme": "dark"}},
                    preset_id=preset_id,
                ),
            )
        )
        update_thread.start()
        self.assertTrue(storage.set_entered.wait(timeout=1))

        def delete_preset():
            delete_attempted.set()
            results.setdefault(
                "delete",
                manager.delete_preset(preset_id),
            )

        delete_thread = threading.Thread(target=delete_preset)
        delete_thread.start()
        self.assertTrue(delete_attempted.wait(timeout=1))
        self.assertFalse(storage.delete_entered.wait(timeout=0.1))

        storage.release_set.set()
        update_thread.join(timeout=1)
        delete_thread.join(timeout=1)

        self.assertFalse(update_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertTrue(results["update"]["ok"])
        self.assertTrue(results["delete"]["ok"])
        self.assertIsNone(manager.get_preset(preset_id))

    def test_two_manager_instances_cannot_create_the_same_normalized_label(self):
        storage = _BlockingStorage()
        first = SettingsPresetManager(storage, _SettingsManager())
        second = SettingsPresetManager(storage, _SettingsManager())
        storage.block_set = True
        results = {}
        thread = threading.Thread(
            target=lambda: results.setdefault("first", first.save_preset("Cinema", {}))
        )
        thread.start()
        self.assertTrue(storage.set_entered.wait(timeout=1))

        results["second"] = second.save_preset(" cinema ", {})
        storage.release_set.set()
        thread.join(timeout=2)

        self.assertTrue(results["first"]["ok"])
        self.assertFalse(results["second"]["ok"])
        self.assertTrue(results["second"]["busy"])
        self.assertEqual(len(first.list_presets()), 1)


if __name__ == "__main__":
    unittest.main()
