from __future__ import annotations

import unittest
from unittest.mock import patch

from emby_users.api_client_items import _fetch_emby_user_items_for_sync, _mark_emby_item_played
from emby_users.playstate_manager import PlaystateManager


def _item(
    item_id: str,
    *,
    played: bool,
    position: int = 0,
    last_played: str | None = None,
) -> dict:
    user_data = {
        "Played": played,
        "PlaybackPositionTicks": position,
    }
    if last_played:
        user_data["LastPlayedDate"] = last_played
    return {
        "Id": item_id,
        "Name": "Shared Movie",
        "Type": "Movie",
        "ProviderIds": {"Tmdb": "42"},
        "UserData": user_data,
    }


class PlaystateDateSyncTests(unittest.TestCase):
    def test_mark_played_sends_date_played_as_emby_query_timestamp(self):
        calls = []

        def fake_call(_server, path, method="GET", params=None, json_payload=None):
            calls.append((path, method, params, json_payload))
            return True, {}

        with patch("emby_users.api_client_items._call_emby_api", fake_call):
            ok, _payload = _mark_emby_item_played(
                {"id": "server-a"},
                "user-a",
                "item-a",
                "2026-03-04T05:06:07.0000000Z",
            )

        self.assertTrue(ok)
        self.assertEqual(
            calls,
            [("Users/user-a/PlayedItems/item-a", "POST", {"DatePlayed": "20260304050607"}, None)],
        )

    def test_fetch_enriches_partial_resume_last_played_from_item_details(self):
        def fake_call(_server, path, method="GET", params=None, json_payload=None):
            params = params or {}
            if path == "Users/user-a/Items" and params.get("Filters") == "IsPlayed":
                return True, {"Items": [], "TotalRecordCount": 0}
            if path == "Users/user-a/Items" and params.get("Filters") == "IsResumable":
                return True, {
                    "Items": [_item("resume-item", played=False, position=600)],
                    "TotalRecordCount": 1,
                }
            if path == "Users/user-a/Items/Resume":
                return True, {
                    "Items": [_item("resume-item", played=False, position=600)],
                    "TotalRecordCount": 1,
                }
            if path == "Users/user-a/Items/resume-item":
                return True, _item(
                    "resume-item",
                    played=False,
                    position=600,
                    last_played="2026-02-03T04:05:06.0000000Z",
                )
            self.fail(f"Unexpected Emby call: {path} {params} {method} {json_payload}")

        with patch("emby_users.api_client_items._call_emby_api", fake_call):
            items, err = _fetch_emby_user_items_for_sync({"id": "server-a"}, "user-a", include_resume=True)

        self.assertIsNone(err)
        self.assertEqual(items[0]["UserData"].get("LastPlayedDate"), "2026-02-03T04:05:06.0000000Z")

    def test_fetch_enriches_played_last_played_from_item_details(self):
        def fake_call(_server, path, method="GET", params=None, json_payload=None):
            params = params or {}
            if path == "Users/user-a/Items" and params.get("Filters") == "IsPlayed":
                return True, {
                    "Items": [_item("played-item", played=True)],
                    "TotalRecordCount": 1,
                }
            if path == "Users/user-a/Items/played-item":
                return True, _item(
                    "played-item",
                    played=True,
                    last_played="2026-03-04T05:06:07.0000000Z",
                )
            self.fail(f"Unexpected Emby call: {path} {params} {method} {json_payload}")

        with patch("emby_users.api_client_items._call_emby_api", fake_call):
            items, err = _fetch_emby_user_items_for_sync({"id": "server-a"}, "user-a", include_resume=False)

        self.assertIsNone(err)
        self.assertEqual(items[0]["UserData"].get("LastPlayedDate"), "2026-03-04T05:06:07.0000000Z")

    def test_exact_sync_updates_last_played_when_target_is_already_played(self):
        manager, calls = self._manager(
            source_item=_item("source-item", played=True, last_played="2026-01-02T03:04:05.0000000Z"),
            target_item=_item("target-item", played=True, last_played="2025-01-02T03:04:05.0000000Z"),
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=False,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-item", "2026-01-02T03:04:05.0000000Z")])

    def test_exact_sync_keeps_enriched_target_userdata_when_provider_lookup_lacks_last_played(self):
        manager, calls = self._manager(
            source_item=_item("source-item", played=True, last_played="2026-01-02T03:04:05.0000000Z"),
            target_item=_item("target-item", played=True, last_played="2026-01-02T03:04:05.0000000Z"),
            provider_item=_item("target-item", played=True),
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=False,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [])

    def test_exact_sync_updates_partial_resume_date_when_position_is_unchanged(self):
        manager, calls = self._manager(
            source_item=_item(
                "source-item",
                played=False,
                position=600,
                last_played="2026-01-02T03:04:05.0000000Z",
            ),
            target_item=_item(
                "target-item",
                played=False,
                position=600,
                last_played="2025-01-02T03:04:05.0000000Z",
            ),
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["resume"], [("target", "target-user", "target-item", 600, "2026-01-02T03:04:05.0000000Z", False)])

    def test_exact_sync_does_not_write_resume_userdata_for_played_items(self):
        manager, calls = self._manager(
            source_item=_item(
                "source-item",
                played=True,
                last_played="2026-01-02T03:04:05.0000000Z",
            ),
            target_item=_item("target-item", played=False),
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-item", "2026-01-02T03:04:05.0000000Z")])
        self.assertEqual(calls["resume"], [])

    def test_exact_sync_preserves_played_when_source_has_played_resume_position(self):
        manager, calls = self._manager(
            source_item=_item(
                "source-item",
                played=True,
                position=600,
                last_played="2026-01-02T03:04:05.0000000Z",
            ),
            target_item=_item("target-item", played=False),
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-item", "2026-01-02T03:04:05.0000000Z")])
        self.assertEqual(calls["resume"], [("target", "target-user", "target-item", 600, "2026-01-02T03:04:05.0000000Z", True)])

    def test_delta_sync_updates_partial_resume_date_when_position_is_unchanged(self):
        manager, calls = self._manager(
            source_item=_item("source-item", played=False),
            target_item=_item(
                "target-item",
                played=False,
                position=600,
                last_played="2025-01-02T03:04:05.0000000Z",
            ),
        )

        result = manager.sync_user_playstate_to_state(
            {
                "tmdb:42": {
                    "played": False,
                    "position": 600,
                    "last_played": "2026-01-02T03:04:05.0000000Z",
                }
            },
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["resume"], [("target", "target-user", "target-item", 600, "2026-01-02T03:04:05.0000000Z", False)])

    def test_delta_sync_does_not_write_resume_userdata_for_played_items(self):
        manager, calls = self._manager(
            source_item=_item("source-item", played=False),
            target_item=_item("target-item", played=False),
        )

        result = manager.sync_user_playstate_to_state(
            {
                "tmdb:42": {
                    "played": True,
                    "position": 0,
                    "last_played": "2026-01-02T03:04:05.0000000Z",
                }
            },
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-item", "2026-01-02T03:04:05.0000000Z")])
        self.assertEqual(calls["resume"], [])

    def test_delta_sync_preserves_played_when_desired_state_has_played_resume_position(self):
        manager, calls = self._manager(
            source_item=_item("source-item", played=False),
            target_item=_item("target-item", played=False),
        )

        result = manager.sync_user_playstate_to_state(
            {
                "tmdb:42": {
                    "played": True,
                    "position": 600,
                    "last_played": "2026-01-02T03:04:05.0000000Z",
                }
            },
            [("target", "target-user")],
            include_resume=True,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-item", "2026-01-02T03:04:05.0000000Z")])
        self.assertEqual(calls["resume"], [("target", "target-user", "target-item", 600, "2026-01-02T03:04:05.0000000Z", True)])

    def _manager(self, *, source_item: dict, target_item: dict, provider_item: dict | None = None):
        servers = {
            "source": {"id": "source", "name": "Source"},
            "target": {"id": "target", "name": "Target"},
        }
        calls = {"played": [], "resume": []}

        def fetch_user_items(server, _user_id, _include_resume):
            if server["id"] == "source":
                return [source_item], None
            return [target_item], None

        manager = PlaystateManager(
            get_server_by_id=servers.get,
            fetch_user_details=lambda _server, user_id: ({"Name": user_id}, None),
            fetch_user_items_for_sync=fetch_user_items,
            fetch_all_media_for_user=lambda _server, _user_id: ([target_item], None),
            fetch_items_by_provider_ids=lambda _server, _user_id, _keys, _include_user_data: ([provider_item or target_item], None),
            fetch_items_by_safe_fallback=lambda _server, _user_id, _item_data: ([], None),
            mark_item_played=lambda server, user_id, item_id, date: (
                calls["played"].append((server["id"], user_id, item_id, date)) or (True, None)
            ),
            mark_item_unplayed=lambda *_args: (True, None),
            set_item_resume=lambda server, user_id, item_id, position, last_played=None, preserve_played=False: (
                calls["resume"].append((server["id"], user_id, item_id, position, last_played, preserve_played)) or (True, None)
            ),
        )
        return manager, calls


if __name__ == "__main__":
    unittest.main()
