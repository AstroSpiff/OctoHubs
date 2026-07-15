"""Progress callback hooks for long-running user operations."""

from __future__ import annotations

import unittest

from emby_users.settings_manager import SettingsManager
from emby_users.settings_target_applier import SettingsApplyResult
from emby_users.sync_manager import SyncManager
from emby_users.user_lifecycle_manager import UserLifecycleManager


class _Storage:
    def __init__(self):
        self.values = {}
        self.backups = []

    def create_user_backup(self, *args):
        self.backups.append(args)

    def set_key_value(self, key, value):
        self.values[key] = value


class OperationProgressCallbackTests(unittest.TestCase):
    def test_create_users_reports_per_target_progress(self):
        server = {"id": "server-a", "name": "Server A"}
        events = []
        manager = UserLifecycleManager(
            storage=_Storage(),
            settings_manager=type("Settings", (), {"apply_settings_to_users": lambda *_args, **_kwargs: {"success": [], "failed": []}})(),
            password_manager=type("Passwords", (), {"update_user_password": lambda *_args, **_kwargs: {"ok": True}})(),
            group_manager=type("Groups", (), {"link_users": lambda *_args, **_kwargs: "group-a", "rename_group": lambda *_args, **_kwargs: True})(),
            get_server_by_id=lambda server_id: server if server_id == "server-a" else None,
            get_unlinked_group_id=lambda _server_id, _user_id: "unused",
            fetch_users_list=lambda _server: ([], None),
            fetch_user_details=lambda _server, _user_id: ({}, None),
            create_user=lambda _server, username, _password: (True, {"Id": f"id-{username}"}),
            delete_user=lambda _server, _user_id: (True, None),
        )

        result = manager.create_users(
            [
                {"server_id": "server-a", "username": "a_test1"},
                {"server_id": "server-a", "username": "a_test2"},
            ],
            progress_callback=events.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(events[-1]["stage"], "complete")
        self.assertEqual(events[-1]["current"], 2)
        self.assertEqual(events[-1]["total"], 2)
        self.assertIn("a_test2", events[-1]["message"])

    def test_clone_user_reports_copy_domains(self):
        servers = {
            "source": {"id": "source", "name": "Source"},
            "target": {"id": "target", "name": "Target"},
        }
        events = []
        manager = SyncManager(
            storage=_Storage(),
            get_server_by_id=servers.get,
            fetch_user_details=lambda _server, _user_id: ({"Name": "a_test", "Policy": {}, "Configuration": {}}, None),
            fetch_users_list=lambda _server: ([], None),
            create_user=lambda _server, username: (True, {"Id": f"id-{username}"}),
            playstate_sync=lambda *_args: {"ok": True},
            library_access_sync=lambda *_args: {"ok": True},
            favorites_sync=lambda *_args: {"ok": True},
            playlists_sync=lambda *_args: {"ok": True},
            link_clone_to_group=lambda *_args: "group-a",
            apply_config_patch=lambda *_args: {"ok": True},
        )

        result = manager.clone_user(
            "source",
            "source-user",
            "target",
            sync_config=True,
            sync_playstate=True,
            sync_favorites=True,
            progress_callback=events.append,
        )

        self.assertTrue(result["ok"])
        stages = [event["stage"] for event in events]
        self.assertIn("config", stages)
        self.assertIn("playstate", stages)
        self.assertIn("favorites", stages)
        self.assertEqual(events[-1]["stage"], "complete")

    def test_apply_settings_to_users_reports_per_target_progress(self):
        manager = SettingsManager.__new__(SettingsManager)
        manager._build_library_group_index = lambda: ({}, {}, {}, {})
        manager._normalize_settings_payload = lambda settings, protect_fields=True: settings
        manager._get_server_by_id = lambda server_id: {"id": server_id, "name": "Server"}
        manager._apply_normalized_settings_to_user = lambda *_args, **_kwargs: SettingsApplyResult(
            server={"id": "server-a"},
            details={"Policy": {}, "Configuration": {}},
            policy={},
            config={},
            display_payload={},
            policy_ok=True,
            config_ok=True,
            display_ok=True,
        )
        manager._extract_settings_from_details = lambda *_args, **_kwargs: {"policy": {}, "config": {}, "display_preferences": {}}
        manager._save_settings_entry = lambda *_args, **_kwargs: {"updated_at": "now"}
        manager.settings_user_key = lambda server_id, user_id: f"settings:{server_id}:{user_id}"

        events = []
        result = manager.apply_settings_to_users(
            [
                {"server_id": "server-a", "user_id": "user-1", "username": "a_test1"},
                {"server_id": "server-a", "user_id": "user-2", "username": "a_test2"},
            ],
            {"policy": {"EnableLiveTv": True}, "config": {}, "display_preferences": {}},
            progress_callback=events.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(events[-1]["stage"], "complete")
        self.assertEqual(events[-1]["current"], 2)
        self.assertEqual(events[-1]["total"], 2)


if __name__ == "__main__":
    unittest.main()
