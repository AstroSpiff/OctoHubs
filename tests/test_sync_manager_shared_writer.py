"""SyncManager should filter source data and delegate the target write."""

from __future__ import annotations

import unittest

from emby_users.sync_manager import SyncManager


class _Storage:
    def __init__(self):
        self.backups = []

    def create_user_backup(self, *args):
        self.backups.append(args)


class SyncManagerSharedWriterTests(unittest.TestCase):
    def test_config_sync_filters_source_fields_then_uses_shared_writer(self):
        servers = {
            "source": {"id": "source", "name": "Source"},
            "target": {"id": "target", "name": "Target"},
        }
        applied = []

        def fetch_details(server, user_id):
            if server["id"] == "source":
                return {
                    "Name": "source-user",
                    "Policy": {"EnableLiveTv": True, "IsAdministrator": True},
                    "Configuration": {"RememberAudioSelections": True, "DashboardLayout": "blocked"},
                }, None
            return {"Name": user_id, "Policy": {}, "Configuration": {}}, None

        def apply_patch(server_id, user_id, patch, source_server_id):
            applied.append((server_id, user_id, patch, source_server_id))
            return {"ok": True, "policy": True, "config": True, "display_preferences": True}

        manager = SyncManager(
            storage=_Storage(),
            get_server_by_id=servers.get,
            fetch_user_details=fetch_details,
            fetch_users_list=lambda _server: ([], None),
            create_user=lambda _server, _name: (False, {}),
            playstate_sync=lambda *_args: {},
            library_access_sync=lambda *_args: {},
            favorites_sync=lambda *_args: {},
            playlists_sync=lambda *_args: {},
            link_clone_to_group=lambda *_args: "group",
            apply_config_patch=apply_patch,
            fetch_user_display_preferences=lambda _server, _user_id: ({"CustomPrefs": {"unused": "value"}}, None),
        )

        result = manager.sync_user_config(
            "source",
            "source-user",
            [("target", "target-user")],
            config_categories=[
                "policy:EnableLiveTv",
                "config:RememberAudioSelections",
                "config:DashboardLayout",
            ],
        )

        self.assertEqual(result["success"], ["Target (target-user)"])
        self.assertEqual(len(applied), 1)
        _server_id, _user_id, patch, source_server_id = applied[0]
        self.assertEqual(source_server_id, "source")
        self.assertEqual(patch["policy"], {"EnableLiveTv": True})
        self.assertEqual(patch["config"], {"RememberAudioSelections": True})
        self.assertEqual(patch["display_preferences"], {})


if __name__ == "__main__":
    unittest.main()
