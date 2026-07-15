"""Characterization tests for the shared Emby settings writer."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from emby_users.settings_manager import SettingsManager
from emby_users.settings_target_applier import SettingsApplyOptions, SettingsTargetApplier


class SettingsTargetApplierTests(unittest.TestCase):
    def setUp(self):
        self.server = {"id": "server-a", "name": "Server A"}
        self.details = {
            "Policy": {
                "ExistingPolicy": "keep",
                "EnableAllFolders": False,
                "EnabledFolders": ["group-old", "private"],
            },
            "Configuration": {"ExistingConfig": "keep"},
        }
        self.display = {"Id": "usersettings", "Client": "emby", "CustomPrefs": {"existing": "keep"}}
        self.policy_updates = []
        self.config_updates = []
        self.display_updates = []

        self.applier = SettingsTargetApplier(
            get_server_by_id=lambda server_id: self.server if server_id == "server-a" else None,
            fetch_user_details=lambda _server, _user_id: (copy.deepcopy(self.details), None),
            update_user_policy=self._update_policy,
            update_user_config=self._update_config,
            fetch_display_preferences=lambda _server, _user_id: (copy.deepcopy(self.display), None),
            update_display_preferences=self._update_display,
            derive_enabled_ids=self._derive_enabled_ids,
            remap_display_preferences=self._remap_display_preferences,
            build_display_payload=self._build_display_payload,
        )

    def _update_policy(self, _server, _user_id, payload):
        self.policy_updates.append(copy.deepcopy(payload))
        return True, None

    def _update_config(self, _server, _user_id, payload):
        self.config_updates.append(copy.deepcopy(payload))
        return True, None

    def _update_display(self, _server, _user_id, payload):
        self.display_updates.append(copy.deepcopy(payload))
        return True, None

    @staticmethod
    def _derive_enabled_ids(groups, index, server_id):
        enabled = []
        for group, selected in groups.items():
            if selected:
                enabled.extend(index.get(group, {}).get(server_id, []))
        return enabled

    @staticmethod
    def _remap_display_preferences(patch, _server_id, _membership, _index, _libraries_by_server, _source_server_id):
        return dict(patch)

    @staticmethod
    def _build_display_payload(existing, patch):
        payload = dict(existing or {})
        custom = dict(payload.get("CustomPrefs") or {})
        custom.update(patch)
        payload["CustomPrefs"] = custom
        return payload

    def test_patch_merges_policy_config_and_display_without_touching_libraries(self):
        result = self.applier.apply(
            "server-a",
            "user-a",
            {
                "policy": {"NewPolicy": True},
                "config": {"NewConfig": "value"},
                "display_preferences": {"theme": "dark"},
                "libraries": {"mode": "all", "groups": {}, "items": []},
            },
            {},
            {},
            options=SettingsApplyOptions(apply_libraries=False),
        )

        self.assertTrue(result.ok)
        self.assertEqual(self.policy_updates[-1]["ExistingPolicy"], "keep")
        self.assertTrue(self.policy_updates[-1]["NewPolicy"])
        self.assertFalse(self.policy_updates[-1]["EnableAllFolders"])
        self.assertEqual(self.config_updates[-1], {"ExistingConfig": "keep", "NewConfig": "value"})
        self.assertEqual(self.display_updates[-1]["CustomPrefs"]["theme"], "dark")

    def test_custom_library_patch_preserves_unassociated_target_libraries(self):
        result = self.applier.apply(
            "server-a",
            "user-a",
            {
                "policy": {},
                "config": {},
                "display_preferences": {},
                "libraries": {"mode": "custom", "groups": {"movies": True}, "items": []},
            },
            {
                "movies": {"server-a": ["group-new"]},
                "old-group": {"server-a": ["group-old"]},
            },
            {"server-a": {"libraries": [{"id": "group-old"}, {"id": "group-new"}, {"id": "private"}]}},
            options=SettingsApplyOptions(preserve_non_group_libraries=True),
        )

        self.assertTrue(result.ok)
        self.assertFalse(self.policy_updates[-1]["EnableAllFolders"])
        self.assertEqual(set(self.policy_updates[-1]["EnabledFolders"]), {"group-new", "private"})

    def test_custom_library_patch_maps_grouped_item_ids_to_access_view_ids(self):
        result = self.applier.apply(
            "server-a",
            "user-a",
            {
                "policy": {},
                "config": {},
                "display_preferences": {},
                "libraries": {
                    "mode": "custom",
                    "groups": {"movies::film": True},
                    "items": ["folder-film"],
                },
            },
            {"movies::film": {"server-a": ["view-film"]}},
            {
                "server-a": {
                    "libraries": [
                        {"id": "folder-film", "view_ids": ["folder-film", "view-film"]},
                    ],
                },
            },
            membership={"server-a": {"folder-film": "movies::film", "view-film": "movies::film"}},
        )

        self.assertTrue(result.ok)
        self.assertFalse(self.policy_updates[-1]["EnableAllFolders"])
        self.assertEqual(self.policy_updates[-1]["EnabledFolders"], ["view-film"])

    def test_missing_target_returns_a_structured_failure(self):
        result = self.applier.apply("missing", "user-a", {}, {}, {})

        self.assertFalse(result.ok)
        self.assertEqual(result.fetch_error, "Server non trovato")
        self.assertFalse(result.policy_ok)


class SettingsManagerIntegrationTests(unittest.TestCase):
    @staticmethod
    def _build_manager(storage=None):
        server = {"id": "server-a", "name": "Server A"}
        return SettingsManager(
            storage=storage or type("Storage", (), {"load_library_associations": lambda self: {}})(),
            config={},
            get_server_by_id=lambda server_id: server if server_id == "server-a" else None,
            get_group_users=lambda _group_id: [],
            fetch_user_details=lambda _server, _user_id: (
                {"Policy": {"Existing": True}, "Configuration": {"ExistingConfig": True}},
                None,
            ),
            update_user_policy=lambda _server, _user_id, _payload: (True, None),
            update_user_config=lambda _server, _user_id, _payload: (True, None),
            fetch_user_display_preferences=lambda _server, _user_id: ({"CustomPrefs": {}}, None),
            update_user_display_preferences=lambda _server, _user_id, _payload: (True, None),
        )

    def test_library_group_index_uses_view_id_for_emby_access_policy(self):
        manager = self._build_manager()

        with patch(
            "emby_users.settings_manager.get_emby_servers",
            return_value=[{"id": "server-a", "name": "Server A", "enabled": True}],
        ), patch(
            "emby_users.settings_manager._fetch_emby_libraries",
            return_value=(
                [
                    {
                        "id": "folder-film",
                        "folder_id": "folder-film",
                        "view_ids": ["folder-film", "view-film"],
                        "name": "Film",
                        "collection_type": "movies",
                    }
                ],
                None,
            ),
        ):
            _, library_index, _, membership = manager._build_library_group_index()

        self.assertEqual(library_index["movies::film"]["server-a"], ["view-film"])
        self.assertEqual(membership["server-a"]["folder-film"], "movies::film")
        self.assertEqual(membership["server-a"]["view-film"], "movies::film")

    def test_landing_display_preferences_use_target_library_preference_id(self):
        manager = self._build_manager()
        manager._build_library_group_index = lambda: (
            [],
            {"movies::film": {"target-server": ["target-access-view"]}},
            {
                "source-server": {
                    "libraries": [
                        {"id": "source-folder", "view_ids": ["source-folder", "source-access-view"]},
                    ],
                },
                "target-server": {
                    "libraries": [
                        {"id": "target-folder", "view_ids": ["target-folder", "target-access-view"]},
                    ],
                },
            },
            {
                "source-server": {
                    "source-folder": "movies::film",
                    "source-access-view": "movies::film",
                },
                "target-server": {
                    "target-folder": "movies::film",
                    "target-access-view": "movies::film",
                },
            },
        )

        remapped = manager.remap_display_preferences_for_server(
            {"landing-source-folder": "suggestions"},
            "target-server",
            source_server_id="source-server",
        )

        self.assertEqual(remapped, {"landing-target-folder": "suggestions"})

    def test_bulk_apply_uses_shared_writer_and_persists_the_snapshot(self):
        server = {"id": "server-a", "name": "Server A"}
        stored = {}
        policy_updates = []
        config_updates = []
        display_updates = []

        class Storage:
            def set_key_value(self, key, value):
                stored[key] = value

        manager = SettingsManager(
            storage=Storage(),
            config={},
            get_server_by_id=lambda server_id: server if server_id == "server-a" else None,
            get_group_users=lambda _group_id: [],
            fetch_user_details=lambda _server, _user_id: (
                {"Policy": {"Existing": True}, "Configuration": {"ExistingConfig": True}},
                None,
            ),
            update_user_policy=lambda _server, _user_id, payload: (policy_updates.append(payload) is None, None),
            update_user_config=lambda _server, _user_id, payload: (config_updates.append(payload) is None, None),
            fetch_user_display_preferences=lambda _server, _user_id: ({"CustomPrefs": {}}, None),
            update_user_display_preferences=lambda _server, _user_id, payload: (display_updates.append(payload) is None, None),
        )
        manager._build_library_group_index = lambda: ([], {}, {"server-a": {"libraries": []}}, {})

        result = manager.apply_settings_to_users(
            [{"server_id": "server-a", "user_id": "user-a", "username": "a_test"}],
            {
                "config": {"RememberAudioSelections": True},
                "display_preferences": {"enableCinemaMode": True},
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["success"], ["a_test"])
        self.assertTrue(config_updates[-1]["RememberAudioSelections"])
        self.assertEqual(display_updates[-1]["CustomPrefs"]["enableCinemaMode"], "true")
        self.assertIn("emby_user_settings:server-a:user-a", stored)


if __name__ == "__main__":
    unittest.main()
