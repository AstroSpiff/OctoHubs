"""Playlist source reads must be all-or-nothing before exact synchronization."""

from __future__ import annotations

from emby_users.playlists_manager import PlaylistsManager


def test_exact_playlist_sync_aborts_before_target_deletion_on_source_item_error():
    deletions = []
    manager = PlaylistsManager(
        get_server_by_id=lambda server_id: {"id": server_id, "name": server_id},
        fetch_playlists=lambda _server, _user_id: ([{"Id": "keep", "Name": "Keep"}], None),
        fetch_playlist_items=lambda _server, _user_id, _playlist_id: ([], "temporary failure"),
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        create_playlist=lambda *_args: (True, {}),
        add_playlist_items=lambda *_args: (True, {}),
        remove_playlist_entries=lambda *_args: (True, {}),
        delete_playlist=lambda *args: (deletions.append(args) or True, {}),
    )

    result = manager.sync_user_playlists_exact("source", "user-a", [("target", "user-b")])

    assert "Failed to read source playlist" in result["error"]
    assert deletions == []


def test_exact_playlist_removal_failure_is_not_reported_as_target_success():
    def fetch_playlists(server, _user_id):
        if server["id"] == "source":
            return [{"Id": "source-list", "Name": "Keep"}], None
        return [{"Id": "target-list", "Name": "Keep"}], None

    def fetch_items(server, _user_id, _playlist_id):
        if server["id"] == "source":
            return [], None
        return [{"Id": "extra", "PlaylistItemId": "entry-extra"}], None

    manager = PlaylistsManager(
        get_server_by_id=lambda server_id: {"id": server_id, "name": server_id.title()},
        fetch_playlists=fetch_playlists,
        fetch_playlist_items=fetch_items,
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        create_playlist=lambda *_args: (True, {}),
        add_playlist_items=lambda *_args: (True, {}),
        remove_playlist_entries=lambda *_args: (False, "remote rejected"),
        delete_playlist=lambda *_args: (True, {}),
    )

    result = manager.sync_user_playlists_exact(
        "source", "user-a", [("target", "user-b")]
    )

    assert result["success"] == []
    assert result["not_removed_counts"] == {"Target": 1}
    assert result["failed"] == ["Target: remove 'Keep' incomplete (1 item(s))"]
