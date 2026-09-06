"""Single-line logging canaries for configurable and upstream metadata."""

from __future__ import annotations

import json
import logging

from core.log_sanitization import format_exception_for_log
from emby_runtime.websocket_manager import EmbyWebSocketConnection
from emby_users.favorites_manager import FavoritesManager
from emby_users.playlists_manager import PlaylistsManager


def _assert_no_forged_record(log_text: str) -> None:
    assert not any(line.startswith("[FORGED]") for line in log_text.splitlines())


def test_exception_formatter_preserves_traceback_but_neutralizes_exception_lines():
    secret = "R31_SECRET"
    try:
        raise RuntimeError(f"first line\n[FORGED] accepted token={secret}")
    except RuntimeError as exc:
        rendered = format_exception_for_log(exc)

    assert "test_exception_formatter_preserves_traceback" in rendered
    assert "builtins.RuntimeError" in rendered
    assert secret not in rendered
    _assert_no_forged_record(rendered)


def test_favorites_and_playlists_logs_neutralize_configurable_server_alias(caplog):
    malicious_alias = "primary\n[FORGED] accepted"
    servers = {
        "source": {"id": "source", "name": "Source"},
        "target": {"id": "target", "alias": malicious_alias},
    }
    caplog.set_level(logging.WARNING)

    favorites = FavoritesManager(
        get_server_by_id=servers.get,
        fetch_favorites=lambda server, _user: (
            ([{"Type": "Movie", "ProviderIds": {"Tmdb": "42"}}], None)
            if server["id"] == "source"
            else ([], None)
        ),
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args, **_kwargs: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        set_favorite=lambda *_args: (True, None),
    )
    favorites.sync_user_favorites("source", "user-a", [("target", "user-b")])

    playlists = PlaylistsManager(
        get_server_by_id=servers.get,
        fetch_playlists=lambda *_args: ([], None),
        fetch_playlist_items=lambda *_args: ([], None),
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args, **_kwargs: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        create_playlist=lambda *_args: (True, {}),
        add_playlist_items=lambda *_args: (True, None),
        remove_playlist_entries=lambda *_args: (True, None),
        delete_playlist=lambda *_args: (True, None),
    )
    playlists.sync_user_playlists("source", "user-a", [("target", "user-b")])

    assert "primary [FORGED] accepted" in caplog.text
    _assert_no_forged_record(caplog.text)


def test_websocket_message_type_cannot_create_a_forged_log_record(caplog):
    caplog.set_level(logging.DEBUG)
    connection = EmbyWebSocketConnection(
        "server\n[FORGED] server",
        "https://emby.example.test",
        "secret",
        lambda _event: None,
    )

    connection._on_message(
        None,
        json.dumps({"MessageType": "Unknown\n[FORGED] authorization=passed"}),
    )

    assert "Unknown [FORGED] authorization=[REDACTED]" in caplog.text
    _assert_no_forged_record(caplog.text)
