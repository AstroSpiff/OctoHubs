from __future__ import annotations

import unittest

from emby_users.playstate_manager import PlaystateManager
from emby_users.auto_sync_manager import AutoSyncManager


def _item(
    item_id: str,
    *,
    played: bool = False,
    last_played: str | None = None,
    position: int = 0,
    hide_from_resume: bool | None = None,
) -> dict:
    user_data = {
        "Played": played,
        "PlaybackPositionTicks": position,
    }
    if last_played:
        user_data["LastPlayedDate"] = last_played
    if hide_from_resume is not None:
        user_data["HideFromResume"] = hide_from_resume
    return {
        "Id": item_id,
        "Name": "Shared Movie",
        "Type": "Movie",
        "ProviderIds": {"Tmdb": "42"},
        "UserData": user_data,
    }


class PlaystateMergeRuleTests(unittest.TestCase):
    def test_bootstrap_bidirectional_keeps_oldest_played_date(self):
        manager, calls = self._manager(
            source_items={
                ("server-a", "user-a"): [
                    _item("source-old", played=True, last_played="2024-01-01T10:00:00.0000000Z")
                ],
                ("server-b", "user-b"): [
                    _item("source-new", played=True, last_played="2026-07-15T10:00:00.0000000Z")
                ],
            },
            target_items={
                ("server-a", "user-a"): [_item("target-a", played=False)],
                ("server-b", "user-b"): [_item("target-b", played=False)],
            },
        )

        result = manager.sync_merge_playstate(
            [("server-a", "user-a"), ("server-b", "user-b")],
            include_resume=False,
        )

        self.assertEqual(result["failed"], [])
        self.assertEqual(
            calls["played"],
            [
                ("server-a", "user-a", "target-a", "2024-01-01T10:00:00.0000000Z"),
                ("server-b", "user-b", "target-b", "2024-01-01T10:00:00.0000000Z"),
            ],
        )

    def test_bootstrap_bidirectional_keeps_hidden_resume_when_position_differs(self):
        manager, calls = self._manager(
            source_items={
                ("server-a", "user-a"): [
                    _item(
                        "source-hidden",
                        position=100,
                        last_played="2026-07-15T10:00:00.0000000Z",
                        hide_from_resume=True,
                    )
                ],
                ("server-b", "user-b"): [
                    _item(
                        "source-visible",
                        position=200,
                        last_played="2026-07-15T11:00:00.0000000Z",
                        hide_from_resume=False,
                    )
                ],
            },
            target_items={
                ("server-a", "user-a"): [_item("target-a", position=0, hide_from_resume=False)],
                ("server-b", "user-b"): [_item("target-b", position=0, hide_from_resume=False)],
            },
        )

        result = manager.sync_merge_playstate(
            [("server-a", "user-a"), ("server-b", "user-b")],
            include_resume=True,
        )

        self.assertEqual(result["failed"], [])
        self.assertEqual(
            calls["resume"],
            [
                ("server-a", "user-a", "target-a", 200, "2026-07-15T11:00:00.0000000Z"),
                ("server-b", "user-b", "target-b", 200, "2026-07-15T11:00:00.0000000Z"),
            ],
        )
        self.assertEqual(
            calls["hide"],
            [
                ("server-a", "user-a", "target-a", True),
                ("server-b", "user-b", "target-b", True),
            ],
        )

    def test_delta_bidirectional_rejects_two_conflicting_changed_snapshots(self):
        applied = []

        class Tracker:
            def refresh_many_with_diff(self, _domain, _participants, progress_callback=None):
                return [
                    {
                        "snapshot": {
                            "items": {
                                "tmdb:42": {
                                    "played": True,
                                    "last_played": "2024-01-01T10:00:00.0000000Z",
                                    "position": 0,
                                }
                            }
                        },
                        "previous_snapshot": {},
                        "diff": {"initial": False, "added": [], "removed": [], "changed": ["tmdb:42"]},
                        "updated_at": "2026-07-15T10:00:00.0000000Z",
                    },
                    {
                        "snapshot": {
                            "items": {
                                "tmdb:42": {
                                    "played": True,
                                    "last_played": "2026-07-15T10:00:00.0000000Z",
                                    "position": 0,
                                }
                            }
                        },
                        "previous_snapshot": {},
                        "diff": {"initial": False, "added": [], "removed": [], "changed": ["tmdb:42"]},
                        "updated_at": "2026-07-15T11:00:00.0000000Z",
                    },
                ]

        manager = AutoSyncManager(
            get_users_dashboard_data=lambda: {},
            sync_merge_playstate=lambda *_args: {},
            sync_user_playstate=lambda *_args: {},
            sync_user_playstate_exact=lambda *_args: {},
            sync_user_playstate_to_state=lambda desired, targets, include_resume: (
                applied.append((desired, targets, include_resume)) or {"ok": True}
            ),
            sync_user_config=lambda *_args: {},
            sync_library_access=lambda *_args: {},
            sync_user_favorites=lambda *_args: {},
            sync_user_favorites_exact=lambda *_args: {},
            sync_user_favorites_to_keys=lambda *_args: {},
            sync_merge_favorites=lambda *_args: {},
            sync_user_playlists=lambda *_args: {},
            sync_user_playlists_exact=lambda *_args: {},
            sync_user_playlists_to_payload=lambda *_args: {},
            sync_merge_playlists=lambda *_args: {},
            mark_group_bootstrap_done=lambda *_args: True,
            mark_group_sync_result=lambda *_args: True,
            state_tracker=Tracker(),
        )

        with self.assertRaisesRegex(RuntimeError, "Conflitto stato riproduzione"):
            manager._run_playstate_delta_sync(
                [("server-a", "user-a"), ("server-b", "user-b")],
                include_resume=True,
            )
        self.assertEqual(applied, [])

    def test_delta_bidirectional_hide_from_resume_conflict_is_explicit(self):
        applied = []

        class Tracker:
            def refresh_many_with_diff(self, _domain, _participants, progress_callback=None):
                return [
                    {
                        "snapshot": {
                            "items": {
                                "tmdb:42": {
                                    "played": False,
                                    "last_played": "2026-07-15T10:00:00.0000000Z",
                                    "position": 100,
                                    "hide_from_resume": True,
                                }
                            }
                        },
                        "previous_snapshot": {},
                        "diff": {"initial": False, "added": [], "removed": [], "changed": ["tmdb:42"]},
                        "updated_at": "2026-07-15T11:00:00.0000000Z",
                    },
                    {
                        "snapshot": {
                            "items": {
                                "tmdb:42": {
                                    "played": False,
                                    "last_played": "2026-07-15T10:00:00.0000000Z",
                                    "position": 100,
                                    "hide_from_resume": False,
                                }
                            }
                        },
                        "previous_snapshot": {},
                        "diff": {"initial": False, "added": [], "removed": [], "changed": ["tmdb:42"]},
                        "updated_at": "2026-07-15T11:00:00.0000000Z",
                    },
                ]

        manager = AutoSyncManager(
            get_users_dashboard_data=lambda: {},
            sync_merge_playstate=lambda *_args: {},
            sync_user_playstate=lambda *_args: {},
            sync_user_playstate_exact=lambda *_args: {},
            sync_user_playstate_to_state=lambda desired, targets, include_resume: (
                applied.append((desired, targets, include_resume)) or {"ok": True}
            ),
            sync_user_config=lambda *_args: {},
            sync_library_access=lambda *_args: {},
            sync_user_favorites=lambda *_args: {},
            sync_user_favorites_exact=lambda *_args: {},
            sync_user_favorites_to_keys=lambda *_args: {},
            sync_merge_favorites=lambda *_args: {},
            sync_user_playlists=lambda *_args: {},
            sync_user_playlists_exact=lambda *_args: {},
            sync_user_playlists_to_payload=lambda *_args: {},
            sync_merge_playlists=lambda *_args: {},
            mark_group_bootstrap_done=lambda *_args: True,
            mark_group_sync_result=lambda *_args: True,
            state_tracker=Tracker(),
        )

        with self.assertRaisesRegex(RuntimeError, "Conflitto stato riproduzione"):
            manager._run_playstate_delta_sync(
                [("server-a", "user-a"), ("server-b", "user-b")],
                include_resume=True,
            )
        self.assertEqual(applied, [])

    def _manager(self, *, source_items: dict[tuple[str, str], list[dict]], target_items: dict[tuple[str, str], list[dict]]):
        servers = {
            "server-a": {"id": "server-a", "name": "Server A"},
            "server-b": {"id": "server-b", "name": "Server B"},
        }
        calls = {"played": [], "resume": [], "hide": []}

        def fetch_user_items(server, user_id, _include_resume):
            return source_items.get((server["id"], user_id), []), None

        def fetch_by_provider(server, user_id, _keys, _include_user_data):
            return target_items.get((server["id"], user_id), []), None

        manager = PlaystateManager(
            get_server_by_id=servers.get,
            fetch_user_details=lambda _server, user_id: ({"Name": user_id}, None),
            fetch_user_items_for_sync=fetch_user_items,
            fetch_all_media_for_user=lambda _server, _user_id: ([], None),
            fetch_items_by_provider_ids=fetch_by_provider,
            fetch_items_by_safe_fallback=lambda _server, _user_id, _source_item: ([], None),
            mark_item_played=lambda server, user_id, item_id, last_played=None: (
                calls["played"].append((server["id"], user_id, item_id, last_played)) or (True, None)
            ),
            mark_item_unplayed=lambda *_args: (True, None),
            set_item_resume=lambda server, user_id, item_id, position, last_played=None, preserve_played=False: (
                calls["resume"].append((server["id"], user_id, item_id, position, last_played)) or (True, None)
            ),
            set_item_hide_from_resume=lambda server, user_id, item_id, hidden: (
                calls["hide"].append((server["id"], user_id, item_id, hidden)) or (True, None)
            ),
        )
        return manager, calls


if __name__ == "__main__":
    unittest.main()
