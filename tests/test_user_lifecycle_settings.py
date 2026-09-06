"""User creation should delegate initial settings to SettingsManager."""

from __future__ import annotations

import unittest

from emby_users.group_manager import GroupManager, GroupSyncBusyError
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


class _CreationStorage:
    def __init__(self):
        self.entries = {}

    @staticmethod
    def _key(server_id, username):
        return str(server_id), str(username).strip().casefold()

    def get_emby_user_creation(self, server_id, username):
        entry = self.entries.get(self._key(server_id, username))
        return dict(entry) if entry is not None else None

    def reserve_emby_user_creation(self, server_id, username):
        key = self._key(server_id, username)
        if key in self.entries:
            return False
        self.entries[key] = {"status": "creating"}
        return True

    def mark_emby_user_creation_remote(self, server_id, username):
        self.entries[self._key(server_id, username)]["status"] = "remote_created"

    def clear_emby_user_creation(self, server_id, username):
        self.entries.pop(self._key(server_id, username), None)


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
    def test_remote_create_without_id_is_journaled_and_retry_does_not_recreate(self):
        server = {"id": "server-a", "name": "Server A"}
        storage = _CreationStorage()
        remote_users = []
        create_calls = []

        def fetch_users(_server):
            return list(remote_users), None

        def create_user(_server, username, _password):
            create_calls.append(username)
            remote_users.append({"Id": "id-alice", "Name": username})
            # Simulate eventual visibility: the immediate refetch cannot see it.
            remote_users.pop()
            return True, {}

        manager = UserLifecycleManager(
            storage=storage,
            settings_manager=_SettingsManager(),
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda _server_id: server,
            get_unlinked_group_id=lambda _server_id, _user_id: "unused",
            fetch_users_list=fetch_users,
            fetch_user_details=lambda *_args: (None, None),
            create_user=create_user,
            delete_user=lambda *_args: (True, None),
        )

        first = manager.create_users([{"server_id": "server-a", "username": "alice"}])
        self.assertEqual("partial", first["status"])
        self.assertTrue(first["created"][0]["remote_created"])
        self.assertFalse(first["created"][0]["identity_resolved"])
        self.assertEqual("identity", first["failed"][0]["stage"])

        remote_users.append({"Id": "id-alice", "Name": "alice"})
        restarted_manager = UserLifecycleManager(
            storage=storage,
            settings_manager=_SettingsManager(),
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda _server_id: server,
            get_unlinked_group_id=lambda _server_id, _user_id: "unused",
            fetch_users_list=fetch_users,
            fetch_user_details=lambda *_args: (None, None),
            create_user=create_user,
            delete_user=lambda *_args: (True, None),
        )
        second = restarted_manager.create_users(
            [{"server_id": "server-a", "username": "alice"}]
        )
        self.assertTrue(second["ok"])
        self.assertEqual("id-alice", second["created"][0]["user_id"])
        self.assertEqual(["alice"], create_calls)

    def test_created_users_survive_settings_and_group_rename_failures(self):
        class _FailingSettings:
            def apply_settings_to_users(self, *_args, **_kwargs):
                raise RuntimeError("db secret=CANARY")

        class _RenameFailure(_GroupManager):
            def rename_group(self, _group_id, _name):
                raise RuntimeError("rename unavailable")

        server = {"id": "server-a", "name": "Server A"}
        manager = UserLifecycleManager(
            storage=_CreationStorage(),
            settings_manager=_FailingSettings(),
            password_manager=_PasswordManager(),
            group_manager=_RenameFailure(),
            get_server_by_id=lambda _server_id: server,
            get_unlinked_group_id=lambda _server_id, _user_id: "unused",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: (None, None),
            create_user=lambda _server, username, _password: (True, {"Id": f"id-{username}"}),
            delete_user=lambda _server, _user_id: (True, None),
        )

        result = manager.create_users(
            [
                {"server_id": "server-a", "username": "alice"},
                {"server_id": "server-a", "username": "bob"},
            ],
            settings={"config": {"RememberAudioSelections": True}},
            link_group=True,
            group_name="Family",
        )

        self.assertFalse(result["ok"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(2, len(result["created"]))
        self.assertEqual("group-a", result["group_id"])
        self.assertEqual({"settings", "rename"}, {item["stage"] for item in result["failed"]})
        self.assertTrue(result["reconciliation_required"])

    def test_create_users_applies_the_initial_patch_once_to_created_users(self):
        settings_manager = _SettingsManager()
        server = {"id": "server-a", "name": "Server A"}
        manager = UserLifecycleManager(
            storage=_CreationStorage(),
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

    def test_confirmed_username_is_forwarded_to_atomic_delete_cleanup(self):
        class _AtomicCleanupStorage:
            def __init__(self):
                self.calls = []

            def get_user_links(self, **_filters):
                return []

            def cleanup_deleted_emby_user(self, server_id, user_id, username):
                self.calls.append((server_id, user_id, username))

        storage = _AtomicCleanupStorage()
        server = {"id": "server-a", "name": "Server A"}
        manager = UserLifecycleManager(
            storage=storage,
            settings_manager=_SettingsManager(),
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda _server_id: server,
            get_unlinked_group_id=lambda sid, uid: f"unlinked_{sid}_{uid}",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: (
                {"Name": " Alice ", "Policy": {"IsAdministrator": False}},
                None,
            ),
            create_user=lambda _server, _username, _password: (True, {}),
            delete_user=lambda _server, _user_id: (True, None),
        )

        result = manager.delete_single_user("server-a", "user-a")

        self.assertTrue(result["ok"])
        self.assertEqual(storage.calls, [("server-a", "user-a", " Alice ")])

    def test_remote_delete_reports_partial_failure_when_local_cleanup_fails(self):
        class _FailingCleanupStorage(_CleanupStorage):
            def delete_key(self, key):
                raise RuntimeError("db unavailable")

        server = {"id": "server-a", "name": "Server A"}
        manager = UserLifecycleManager(
            storage=_FailingCleanupStorage(),
            settings_manager=type("Settings", (), {"settings_user_key": lambda _self, sid, uid: f"settings:{sid}:{uid}"})(),
            password_manager=_PasswordManager(),
            group_manager=_GroupManager(),
            get_server_by_id=lambda _server_id: server,
            get_unlinked_group_id=lambda sid, uid: f"unlinked_{sid}_{uid}",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: ({"Name": "Viewer", "Policy": {}}, None),
            create_user=lambda _server, _username, _password: (True, {}),
            delete_user=lambda _server, _user_id: (True, None),
        )

        result = manager.delete_single_user("server-a", "user-a")

        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["cleanup_error"], "Cleanup locale non completato")


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

    def test_unlink_is_rejected_while_group_sync_guard_is_held(self):
        storage = _LinkStorage()
        storage.set_user_link("server-a", "user-a", "group-a", "A", is_leader=True)
        storage.set_user_link("server-b", "user-b", "group-a", "B")
        manager = GroupManager(
            storage=storage,
            password_manager=_NoPasswordManager(),
            get_users_dashboard_data=lambda: {"groups": []},
        )

        with manager.sync_guard("group-a") as acquired:
            self.assertTrue(acquired)
            with self.assertRaises(GroupSyncBusyError):
                manager.unlink_user("server-a", "user-a")

    def test_link_move_is_rejected_while_source_group_sync_guard_is_held(self):
        storage = _LinkStorage()
        storage.set_user_link("server-a", "user-a", "group-a", "A", is_leader=True)
        storage.set_user_link("server-b", "user-b", "group-a", "B")
        manager = GroupManager(
            storage=storage,
            password_manager=_NoPasswordManager(),
            get_users_dashboard_data=lambda: {"groups": []},
        )

        with manager.sync_guard("group-a") as acquired:
            self.assertTrue(acquired)
            with self.assertRaises(GroupSyncBusyError):
                manager.link_users(
                    [{"server_id": "server-a", "user_id": "user-a", "username": "A"}],
                    group_id="group-b",
                )

        self.assertEqual(storage.get_user_links(server_id="server-a")[0]["group_id"], "group-a")

    def test_stale_sync_result_does_not_recreate_deleted_group_settings(self):
        storage = _LinkStorage()
        manager = GroupManager(
            storage=storage,
            password_manager=_NoPasswordManager(),
            get_users_dashboard_data=lambda: {"groups": []},
        )

        self.assertFalse(manager.mark_group_sync_result("deleted", "success"))


if __name__ == "__main__":
    unittest.main()
