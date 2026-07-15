from __future__ import annotations

import unittest
from unittest.mock import ANY, patch

from emby_users.api_client_items import _fetch_emby_user_items_for_sync, USER_ITEM_FIELDS
from emby_users.item_matching import get_item_sync_keys
from emby_users.playstate_manager import PlaystateManager
from emby_users.state_tracker import UserSyncStateTracker


def _item(item_id: str, position: int = 600, hide: bool | None = None) -> dict:
    user_data = {
        "Played": False,
        "PlaybackPositionTicks": position,
    }
    if hide is not None:
        user_data["HideFromResume"] = hide
    return {
        "Id": item_id,
        "Name": "Shared Movie",
        "Type": "Movie",
        "ProviderIds": {"Tmdb": "42"},
        "UserData": user_data,
    }


class PlaystateHideFromResumeTests(unittest.TestCase):
    def test_fetch_marks_resumable_items_missing_from_visible_resume_as_hidden(self):
        calls = []

        def fake_call(_server, path, method="GET", params=None, json_payload=None):
            calls.append((path, params or {}))
            if path == "Users/user-a/Items" and params.get("Filters") == "IsPlayed":
                return True, {"Items": [], "TotalRecordCount": 0}
            if path == "Users/user-a/Items" and params.get("Filters") == "IsResumable":
                self.assertEqual(params.get("Fields"), USER_ITEM_FIELDS)
                return True, {"Items": [_item("hidden-item")], "TotalRecordCount": 1}
            if path == "Users/user-a/Items/Resume":
                return True, {"Items": [], "TotalRecordCount": 0}
            if path == "Users/user-a/Items/hidden-item":
                return True, _item("hidden-item")
            self.fail(f"Unexpected Emby call: {path} {params} {method} {json_payload}")

        with patch("emby_users.api_client_items._call_emby_api", fake_call):
            items, err = _fetch_emby_user_items_for_sync({"id": "server-a"}, "user-a", include_resume=True)

        self.assertIsNone(err)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["UserData"].get("HideFromResume"))
        self.assertIn(("Users/user-a/Items/Resume", ANY), calls)

    def test_snapshot_keeps_hide_from_resume_for_delta_sync(self):
        tracker = UserSyncStateTracker(
            storage=None,
            get_server_by_id=lambda _server_id: None,
            fetch_user_details=lambda _server, _user_id: ({}, None),
            fetch_playstate_items=lambda _server, _user_id, _include_resume: ([], None),
            fetch_favorites=lambda _server, _user_id: ([], None),
            fetch_playlists=lambda _server, _user_id: ([], None),
            fetch_playlist_items=lambda _server, _user_id, _playlist_id: ([], None),
            item_keys=get_item_sync_keys,
            extract_settings=lambda _details, _server_id: {},
        )

        snapshot = tracker._snapshot_playstate([_item("source-item", hide=True)])

        self.assertTrue(snapshot["items"]["tmdb:42"].get("hide_from_resume"))

    def test_exact_sync_applies_hidden_resume_state_to_target(self):
        manager, hide_calls = self._manager_for_hide_tests(_item("source-item", hide=True), _item("target-item"))

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(hide_calls, [("target", "target-user", "target-item", True)])

    def test_exact_sync_applies_visible_resume_state_to_target(self):
        manager, hide_calls = self._manager_for_hide_tests(_item("source-item", hide=False), _item("target-item", hide=True))

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(hide_calls, [("target", "target-user", "target-item", False)])

    def test_delta_sync_applies_hidden_resume_state_to_target(self):
        manager, hide_calls = self._manager_for_hide_tests(_item("source-item"), _item("target-item"))

        result = manager.sync_user_playstate_to_state(
            {"tmdb:42": {"played": False, "position": 600, "hide_from_resume": True}},
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(hide_calls, [("target", "target-user", "target-item", True)])

    def test_exact_sync_keeps_extra_hidden_target_resume_hidden(self):
        manager, hide_calls = self._manager_for_hide_tests(
            _item("source-item", hide=False),
            {
                **_item("target-item", hide=True),
                "ProviderIds": {"Tmdb": "99"},
            },
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(hide_calls, [])

    def test_delta_sync_hides_extra_visible_target_resume_missing_from_desired_state(self):
        manager, hide_calls = self._manager_for_hide_tests(
            _item("source-item", hide=False),
            {
                **_item("target-item", hide=False),
                "ProviderIds": {"Tmdb": "99"},
            },
        )

        result = manager.sync_user_playstate_to_state(
            {},
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(hide_calls, [("target", "target-user", "target-item", True)])

    def _manager_for_hide_tests(self, source_item: dict, target_item: dict):
        servers = {
            "source": {"id": "source", "name": "Source"},
            "target": {"id": "target", "name": "Target"},
        }
        hide_calls = []

        def fetch_user_items(server, _user_id, _include_resume):
            if server["id"] == "source":
                return [source_item], None
            return [target_item], None

        manager = PlaystateManager(
            get_server_by_id=servers.get,
            fetch_user_details=lambda _server, user_id: ({"Name": user_id}, None),
            fetch_user_items_for_sync=fetch_user_items,
            fetch_all_media_for_user=lambda _server, _user_id: ([target_item], None),
            fetch_items_by_provider_ids=lambda _server, _user_id, _keys, _include_user_data: ([target_item], None),
            fetch_items_by_safe_fallback=lambda _server, _user_id, _item_data: ([], None),
            mark_item_played=lambda *_args: (True, None),
            mark_item_unplayed=lambda *_args: (True, None),
            set_item_resume=lambda *_args: (True, None),
        )
        manager._set_item_hide_from_resume = (
            lambda server, user_id, item_id, hide: hide_calls.append((server["id"], user_id, item_id, hide)) or (True, None)
        )
        return manager, hide_calls


if __name__ == "__main__":
    unittest.main()
