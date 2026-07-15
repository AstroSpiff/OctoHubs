"""User creation should delegate initial settings to SettingsManager."""

from __future__ import annotations

import unittest

from emby_users.group_manager import GroupManager
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


class _CleanupStorage:
    def __init__(self):
        self.cleanup_calls = []

    def remove_user_link(self, server_id, user_id):
        self.cleanup_calls.append(("remove_user_link", server_id, user_id))

    def delete_key(self, key):
        self.cleanup_calls.append(("delete_key", key))

    def delete_group_password(self, group_id):
        self.cleanup_calls.append(("delete_group_password", group_id))

    def delete_icon_binding(self, target_type, target_id):
        self.cleanup_calls.append(("delete_icon_binding", target_type, target_id))


class _LinkStorage:
    def __init__(self):
        self.links = []
        self.group_passwords = {}

    def get_user_links(self, server_id=None, user_id=None, group_id=None):
        links = self.links
        if server_id is not None:
            links = [link for link in links if link["server_id"] == server_id]
        if user_id is not None:
            links = [link for link in links if link["user_id"] == user_id]
        if group_id is not None:
            links = [link for link in links if link["group_id"] == group_id]
        return [dict(link) for link in links]

    def set_user_link(self, server_id, user_id, group_id, username, is_leader=False):
        self.links = [
            link for link in self.links
            if not (link["server_id"] == server_id and link["user_id"] == user_id)
        ]
        self.links.append({
            "server_id": server_id,
            "user_id": user_id,
            "group_id": group_id,
            "username": username,
            "is_leader": bool(is_leader),
        })

    def get_group_password(self, group_id):
        return self.group_passwords.get(group_id)

    def save_group_password(self, group_id, password_enc):
        self.group_passwords[group_id] = {"password_enc": password_enc}


class _NoPasswordManager:
    def get_user_plain_password(self, _server_id, _user_id):
        return None

    def ensure_user_password_inherits_group(self, _group_id, _server_id, _user_id):
        return None

    def encrypt_password(self, value):
        return f"enc:{value}"


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

    def test_master_named_user_can_be_deleted_when_not_admin(self):
        storage = _CleanupStorage()
        server = {"id": "server-a", "name": "Server A"}
        deleted = []
        manager = UserLifecycleManager(
            storage=storage,
            settings_manager=type("Settings", (), {"settings_user_key": lambda _self, sid, uid: f"settings:{sid}:{uid}"})(),
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda server_id: server if server_id == "server-a" else None,
            get_unlinked_group_id=lambda server_id, user_id: f"unlinked_{server_id}_{user_id}",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: (
                {"Name": "Master", "Policy": {"IsAdministrator": False}},
                None,
            ),
            create_user=lambda _server, username, _password: (True, {"Id": f"id-{username}"}),
            delete_user=lambda _server, user_id: (deleted.append(user_id) is None, None),
        )

        result = manager.delete_single_user("server-a", "user-master", expected_name="Master")

        self.assertTrue(result["ok"])
        self.assertEqual(deleted, ["user-master"])
        self.assertEqual(result["user"]["username"], "Master")


class GroupManagerMasterUserTests(unittest.TestCase):
    def test_master_named_user_is_not_auto_selected_as_group_leader(self):
        storage = _LinkStorage()
        manager = GroupManager(
            storage=storage,
            password_manager=_NoPasswordManager(),
            get_users_dashboard_data=lambda: {"groups": []},
        )

        group_id = manager.link_users([
            {"server_id": "server-a", "user_id": "user-a", "username": "a_test", "is_leader": False},
            {"server_id": "server-b", "user_id": "user-b", "username": "Master", "is_leader": False},
        ])

        links = storage.get_user_links(group_id=group_id)
        leader = next(link for link in links if link["is_leader"])
        self.assertEqual(leader["user_id"], "user-a")


if __name__ == "__main__":
    unittest.main()
