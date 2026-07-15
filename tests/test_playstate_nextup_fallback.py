from __future__ import annotations

import unittest

from emby_users.item_matching import get_item_sync_keys
from emby_users.playstate_manager import PlaystateManager
from emby_users.state_tracker import UserSyncStateTracker


def _episode(
    item_id: str,
    *,
    series: str = "I mestieri del fumetto",
    season: int = 1,
    episode: int = 1,
    played: bool = False,
    runtime_ticks: int | None = 1_200 * 10_000_000,
) -> dict:
    return {
        "Id": item_id,
        "Name": f"Episodio {episode}",
        "SeriesName": series,
        "Type": "Episode",
        "ParentIndexNumber": season,
        "IndexNumber": episode,
        "RunTimeTicks": runtime_ticks,
        "ProviderIds": {},
        "SeriesProviderIds": {},
        "UserData": {
            "Played": played,
            "PlaybackPositionTicks": 0,
            "LastPlayedDate": "2026-07-15T10:00:00.0000000Z" if played else None,
        },
    }


class PlaystateNextUpFallbackTests(unittest.TestCase):
    def test_safe_episode_without_provider_ids_gets_stable_sync_key(self):
        keys = get_item_sync_keys(_episode("source-ep1", played=True))

        self.assertTrue(keys)
        self.assertTrue(any(key.startswith("fallback-episode:") for key in keys))

    def test_safe_episode_without_runtime_still_gets_stable_sync_key(self):
        keys = get_item_sync_keys(_episode("source-ep1", played=True, runtime_ticks=None))

        self.assertEqual(["fallback-episode:i mestieri del fumetto|s1|e1"], keys)

    def test_snapshot_tracks_safe_episode_without_provider_ids_for_delta_sync(self):
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

        snapshot = tracker._snapshot_playstate([_episode("source-ep1", played=True)])

        self.assertEqual(1, len(snapshot["items"]))
        self.assertTrue(next(iter(snapshot["items"])).startswith("fallback-episode:"))

    def test_exact_sync_marks_unplayed_target_episode_by_safe_fallback(self):
        manager, calls = self._manager(
            source_items=[_episode("source-ep1", played=True)],
            target_current_items=[],
            target_media_items=[_episode("target-ep1", played=False)],
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=False,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-ep1")])

    def test_exact_sync_clears_extra_played_target_episode_by_safe_fallback(self):
        manager, calls = self._manager(
            source_items=[_episode("source-ep1", episode=1, played=True)],
            target_current_items=[_episode("target-ep2", episode=2, played=True)],
            target_media_items=[],
        )

        result = manager.sync_user_playstate_exact(
            "source",
            "source-user",
            [("target", "target-user")],
            include_resume=False,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["unplayed"], [("target", "target-user", "target-ep2")])

    def test_delta_sync_marks_unplayed_target_episode_by_safe_fallback(self):
        desired_key = get_item_sync_keys(_episode("source-ep1", played=True))[0]
        manager, calls = self._manager(
            source_items=[],
            target_current_items=[],
            target_media_items=[_episode("target-ep1", played=False)],
        )

        result = manager.sync_user_playstate_to_state(
            {desired_key: {"played": True, "last_played": "2026-07-15T10:00:00.0000000Z", "position": 0}},
            [("target", "target-user")],
            include_resume=False,
        )

        self.assertEqual(result["success"], ["Target"])
        self.assertEqual(calls["played"], [("target", "target-user", "target-ep1")])

    def _manager(self, *, source_items: list[dict], target_current_items: list[dict], target_media_items: list[dict]):
        servers = {
            "source": {"id": "source", "name": "Source"},
            "target": {"id": "target", "name": "Target"},
        }
        calls = {"played": [], "unplayed": []}

        def fetch_user_items(server, _user_id, _include_resume):
            if server["id"] == "source":
                return source_items, None
            return target_current_items, None

        manager = PlaystateManager(
            get_server_by_id=servers.get,
            fetch_user_details=lambda _server, user_id: ({"Name": user_id}, None),
            fetch_user_items_for_sync=fetch_user_items,
            fetch_all_media_for_user=lambda _server, _user_id: (target_media_items, None),
            fetch_items_by_provider_ids=lambda _server, _user_id, _keys, _include_user_data: ([], None),
            fetch_items_by_safe_fallback=lambda _server, _user_id, _source_item: ([], None),
            mark_item_played=lambda server, user_id, item_id, _last_played=None: (
                calls["played"].append((server["id"], user_id, item_id)) or (True, None)
            ),
            mark_item_unplayed=lambda server, user_id, item_id: (
                calls["unplayed"].append((server["id"], user_id, item_id)) or (True, None)
            ),
            set_item_resume=lambda *_args: (True, None),
        )
        manager._fetch_all_media_for_user = lambda _server, _user_id: (target_media_items, None)
        manager._fetch_items_by_fallback_key = (
            lambda _server, _user_id, key, **_kwargs: (
                [item for item in target_media_items if key in get_item_sync_keys(item)],
                None,
            )
        )
        return manager, calls


if __name__ == "__main__":
    unittest.main()
