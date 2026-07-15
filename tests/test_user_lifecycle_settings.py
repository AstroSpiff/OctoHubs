"""User creation should delegate initial settings to SettingsManager."""

from __future__ import annotations

import unittest

from emby_users.user_lifecycle_manager import UserLifecycleManager


class _SettingsManager:
    def __init__(self):
        self.calls = []

    def apply_settings_to_users(self, targets, settings, apply_libraries=False):
        self.calls.append((targets, settings, apply_libraries))
        return {"success": [target["username"] for target in targets], "failed": []}


class _PasswordManager:
    def update_user_password(self, _server_id, _user_id, _password):
        return {"ok": True}


class _GroupManager:
    def link_users(self, _links):
        return "group-a"

    def rename_group(self, _group_id, _name):
        return True


class UserLifecycleSettingsTests(unittest.TestCase):
    def test_create_users_applies_the_initial_patch_once_to_created_users(self):
        settings_manager = _SettingsManager()
        server = {"id": "server-a", "name": "Server A"}
        manager = UserLifecycleManager(
            storage=object(),
            settings_manager=settings_manager,
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda server_id: server if server_id == "server-a" else None,
            get_unlinked_group_id=lambda _server_id, _user_id: "unused",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: (None, None),
            create_user=lambda _server, username, _password: (True, {"Id": f"id-{username}"}),
            delete_user=lambda _server, _user_id: (True, None),
        )

        patch = {"config": {"RememberAudioSelections": True}}
        result = manager.create_users(
            [{"server_id": "server-a", "username": "a_test_refactor"}],
            settings=patch,
            password="initial-password",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(settings_manager.calls), 1)
        targets, applied_settings, apply_libraries = settings_manager.calls[0]
        self.assertEqual(targets[0]["user_id"], "id-a_test_refactor")
        self.assertEqual(applied_settings, patch)
        self.assertFalse(apply_libraries)


if __name__ == "__main__":
    unittest.main()
