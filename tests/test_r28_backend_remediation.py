from __future__ import annotations

import asyncio
from contextlib import contextmanager
import threading

from starlette.requests import Request

from emby_libraries.scan_manager import EmbyLibraryScanManager
from emby_libraries.tracker import LibraryScanTracker
from emby_runtime.library_poller import EmbyLibraryPoller
from emby_runtime import server_routes
from emby_users.auto_sync_manager import AutoSyncManager
from emby_users.favorites_manager import FavoritesManager
from emby_users.mutation_coordinator import (
    _LOCKS,
    UserMutationCoordinator,
    server_mutation_key,
)
from emby_users.sync_manager import SyncManager
from emby_users.playlists_manager import PlaylistsManager
from emby_users.user_lifecycle_manager import UserLifecycleManager
from services import workflows


class _Storage:
    def create_user_backup(self, *_args, **_kwargs):
        return None

    def get_user_links(self, **_kwargs):
        return []


class _GroupManager:
    @contextmanager
    def sync_guard(self, _group_id):
        yield True


def _sync_manager(**overrides):
    servers = {
        "source": {"id": "source", "name": "Source"},
        "target": {"id": "target", "name": "Target"},
    }
    values = {
        "storage": _Storage(),
        "get_server_by_id": servers.get,
        "fetch_user_details": lambda _server, _user_id: (
            {"Name": "alice", "Policy": {}, "Configuration": {}},
            None,
        ),
        "fetch_users_list": lambda server: (
            ([{"Name": "alice", "Id": "target-user"}], None)
            if server["id"] == "target"
            else ([], None)
        ),
        "create_user": lambda *_args: (True, {"Id": "target-user"}),
        "playstate_sync": lambda *_args: {"success": ["target"], "failed": []},
        "library_access_sync": lambda *_args: {"success": ["target"], "failed": []},
        "favorites_sync": lambda *_args: {"success": ["target"], "failed": []},
        "playlists_sync": lambda *_args: {"success": ["target"], "failed": []},
        "link_clone_to_group": lambda *_args: "group-a",
        "apply_config_patch": lambda *_args: {"ok": True},
    }
    values.update(overrides)
    return SyncManager(**values)


def test_clone_aggregates_every_requested_domain_failure():
    events = []
    manager = _sync_manager(
        playstate_sync=lambda *_args: {"error": "playstate failed"},
        library_access_sync=lambda *_args: {"success": [], "failed": ["access failed"]},
        favorites_sync=lambda *_args: {"success": [], "failed": ["favorites failed"]},
        playlists_sync=lambda *_args: {"success": [], "failed": ["playlists failed"]},
        apply_config_patch=lambda *_args: {"ok": False, "message": "config failed"},
    )

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=True,
        sync_playstate=True,
        sync_library_access=True,
        sync_favorites=True,
        sync_playlists=True,
        progress_callback=events.append,
    )

    assert result["ok"] is False
    assert result["status"] == "error"
    assert set(result["failed_domains"]) == {
        "config",
        "playstate",
        "library_access",
        "favorites",
        "playlists",
    }
    assert events[-1]["stage"] == "error"


def test_clone_created_target_is_partial_when_every_requested_domain_fails():
    manager = _sync_manager(
        fetch_users_list=lambda _server: ([], None),
        playstate_sync=lambda *_args: {"error": "playstate failed"},
        apply_config_patch=lambda *_args: {"ok": False, "message": "config failed"},
    )

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=True,
        sync_playstate=True,
    )

    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["partial"] is True
    assert result["target_user_id"] == "target-user"
    assert set(result["failed_domains"]) == {"config", "playstate"}


def test_clone_is_partial_when_domain_reports_structured_success_and_failure():
    remote_effects = []

    def partially_sync_favorites(*_args):
        remote_effects.append("favorite-written")
        return {"success": ["target"], "failed": ["secondary write failed"]}

    manager = _sync_manager(favorites_sync=partially_sync_favorites)

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=False,
        sync_playstate=False,
        sync_favorites=True,
    )

    assert remote_effects == ["favorite-written"]
    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["partial"] is True
    assert set(result["failed_domains"]) == {"favorites"}


def test_clone_does_not_infer_partial_success_from_counts_or_missing_only():
    manager = _sync_manager(
        favorites_sync=lambda *_args: {
            "success": [],
            "failed": ["lookup failed"],
            "counts": {"Target": 1},
            "missing_counts": {"Target": 2},
        }
    )

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=False,
        sync_playstate=False,
        sync_favorites=True,
    )

    assert result["status"] == "error"
    assert result["partial"] is False


def _favorites_manager(fallback_result):
    servers = {
        "source": {"id": "source", "name": "Source"},
        "target": {"id": "target", "name": "Target"},
    }
    return FavoritesManager(
        get_server_by_id=servers.get,
        fetch_favorites=lambda server, _user_id: (
            ([{"Type": "Audio", "Name": "Unkeyed"}], None)
            if server["id"] == "source"
            else ([], None)
        ),
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args, **_kwargs: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: fallback_result,
        set_favorite=lambda *_args: (True, None),
    )


def _playlists_manager(fallback_result, created=None):
    servers = {
        "source": {"id": "source", "name": "Source"},
        "target": {"id": "target", "name": "Target"},
    }
    created = created if created is not None else []

    def fetch_playlists(server, _user_id):
        if server["id"] == "source":
            return [{"Id": "playlist-source", "Name": "Source list"}], None
        return [], None

    return PlaylistsManager(
        get_server_by_id=servers.get,
        fetch_playlists=fetch_playlists,
        fetch_playlist_items=lambda server, _user_id, _playlist_id: (
            ([{"Type": "Audio", "Name": "Unkeyed"}], None)
            if server["id"] == "source"
            else ([], None)
        ),
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: fallback_result,
        create_playlist=lambda *_args: (created.append(True) or True, {"Id": "new-list"}),
        add_playlist_items=lambda *_args: (True, None),
        remove_playlist_entries=lambda *_args: (True, None),
        delete_playlist=lambda *_args: (True, None),
    )


def test_favorites_fallback_distinguishes_lookup_error_from_no_match():
    failed = _favorites_manager(([], "lookup unavailable")).sync_user_favorites(
        "source", "source-user", [("target", "target-user")]
    )
    missing = _favorites_manager(([], None)).sync_user_favorites(
        "source", "source-user", [("target", "target-user")]
    )

    assert failed["failed"] == ["Target: 1 fallback lookup(s) failed"]
    assert failed["success"] == []
    assert missing["failed"] == []
    assert missing["success"] == ["Target"]
    assert missing["missing_counts"] == {"Target": 1}


def test_playlist_fallback_distinguishes_lookup_error_from_no_match():
    failed_creates = []
    failed = _playlists_manager(
        ([], "lookup unavailable"), failed_creates
    ).sync_user_playlists("source", "source-user", [("target", "target-user")])
    missing_creates = []
    missing = _playlists_manager(
        ([], None), missing_creates
    ).sync_user_playlists("source", "source-user", [("target", "target-user")])

    assert failed["failed"] == ["Target: lookup 'Source list' failed"]
    assert failed["success"] == []
    assert failed_creates == []
    assert missing["failed"] == []
    assert missing_creates == [True]
    assert missing["missing_counts"] == {"Target": 1}


def test_clone_propagates_real_favorites_fallback_lookup_failure():
    favorites = _favorites_manager(([], "lookup unavailable"))
    manager = _sync_manager(favorites_sync=favorites.sync_user_favorites)

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=False,
        sync_playstate=False,
        sync_favorites=True,
    )

    assert result["status"] == "error"
    assert set(result["failed_domains"]) == {"favorites"}


def test_clone_propagates_real_playlist_fallback_lookup_failure():
    playlists = _playlists_manager(([], "lookup unavailable"))
    manager = _sync_manager(playlists_sync=playlists.sync_user_playlists)

    result = manager.clone_user(
        "source",
        "source-user",
        "target",
        sync_config=False,
        sync_playstate=False,
        sync_playlists=True,
    )

    assert result["status"] == "error"
    assert set(result["failed_domains"]) == {"playlists"}


def test_auto_sync_returns_retryable_aggregate_for_busy_and_failed_groups(monkeypatch):
    manager = AutoSyncManager.__new__(AutoSyncManager)
    manager._get_users_dashboard_data = lambda: {
        "groups": [{"id": "failed", "auto_sync": True}, {"id": "busy", "auto_sync": True}]
    }
    manager._sync_group_singleflight = lambda group: (
        {"status": "error"}
        if group["id"] == "failed"
        else {"status": "skipped", "reason": "already_running"}
    )
    monkeypatch.setattr("emby_users.auto_sync_manager._publish_users_sync_updated", lambda: None)

    outcome = manager.run_auto_sync()

    assert outcome == {
        "ok": False,
        "attempted": True,
        "succeeded": [],
        "failed": ["failed"],
        "retryable": ["busy"],
        "skipped": [],
    }


def test_workflow_sync_propagates_auto_sync_failure(monkeypatch):
    class AutoSync:
        @staticmethod
        def run_auto_sync():
            return {"ok": False, "failed": ["group-a"]}

    manager = type("Manager", (), {"auto_sync_manager": AutoSync()})()
    monkeypatch.setattr(workflows, "_get_emby_user_manager", lambda *_args: manager)

    assert workflows._wf_trigger_sync() is False


def test_server_fence_blocks_user_create_and_clone():
    coordinator = UserMutationCoordinator(None)
    remote_creates = []
    lifecycle = UserLifecycleManager(
        storage=_Storage(),
        settings_manager=object(),
        password_manager=object(),
        group_manager=_GroupManager(),
        get_server_by_id=lambda server_id: {"id": server_id},
        get_unlinked_group_id=lambda server_id, user_id: f"{server_id}:{user_id}",
        fetch_users_list=lambda _server: ([], None),
        fetch_user_details=lambda _server, _user_id: ({"Name": "alice"}, None),
        create_user=lambda server, username, _password: (
            remote_creates.append((server["id"], username)) or True,
            {"Id": "new-user"},
        ),
        delete_user=lambda *_args: (True, None),
        mutation_coordinator=coordinator,
    )
    clone = _sync_manager(mutation_coordinator=coordinator)

    holder_started = threading.Event()
    release_holder = threading.Event()

    def hold_delete_fence():
        with coordinator.guard([server_mutation_key("target")]) as acquired:
            assert acquired is True
            holder_started.set()
            assert release_holder.wait(timeout=2)

    holder = threading.Thread(target=hold_delete_fence)
    holder.start()
    assert holder_started.wait(timeout=1)
    create_result = lifecycle.create_users([{"server_id": "target", "username": "alice"}])
    clone_result = clone.clone_user("source", "source-user", "target")
    release_holder.set()
    holder.join(timeout=2)

    assert not holder.is_alive()
    assert create_result["busy"] is True
    assert clone_result["busy"] is True
    assert remote_creates == []


def test_mutation_lock_registry_is_reentrant_and_releases_unused_keys():
    coordinator = UserMutationCoordinator(None)
    baseline = set(_LOCKS)

    key = server_mutation_key("same-server")
    with coordinator.guard([key]) as outer:
        assert outer is True
        with coordinator.guard([key]) as inner:
            assert inner is True
    for index in range(2_000):
        with coordinator.guard([f"server:{index}", f"user:{index}"]) as acquired:
            assert acquired is True

    assert set(_LOCKS) == baseline


def test_deleted_server_tombstone_blocks_late_poller_start_until_allow():
    poller = EmbyLibraryPoller()
    asyncio.run(poller.stop_server("server-a"))

    loop = asyncio.new_event_loop()
    try:
        assert poller.schedule_tracking_library(
            loop, "server-a", "library-a", "job-a", object()
        ) is False
    finally:
        loop.close()
    poller.allow_server("server-a")
    assert poller._server_is_blocked("server-a") is False


def test_successful_server_delete_keeps_probe_tombstone(monkeypatch):
    released = []

    class ProbeManager:
        def release_server(self, server_id):
            released.append(server_id)

    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: None)
    monkeypatch.setattr(server_routes, "_validate_json_csrf", lambda _request: None)
    monkeypatch.setattr(server_routes, "_require_valid_configuration", lambda: None)
    monkeypatch.setattr("emby_probe.get_probe_manager", lambda: ProbeManager())

    async def quiesce(_server_id):
        return None

    monkeypatch.setattr(server_routes, "_quiesce_server", quiesce)
    monkeypatch.setattr(
        server_routes,
        "_remove_server_value",
        lambda server_id: {"id": server_id, "name": "Server"},
    )
    request = Request({"type": "http", "method": "DELETE", "path": "/", "headers": []})

    response = asyncio.run(server_routes.delete_emby_server_api("server-a", request))

    assert response.status_code == 200
    assert released == []


def test_scan_tracker_never_deletes_or_evicts_active_jobs():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    first = tracker.create_job("server-a", ["library-active"])

    assert tracker.delete_job(first) == "active"
    for index in range(100):
        tracker.create_job("server-a", [f"library-{index}"])

    assert tracker.get_job(first) is not None
    assert len(tracker.get_all_jobs()) == 101

    tracker.update_library_status(first, "library-active", "completed", 1.0)
    assert tracker.delete_job(first) == "deleted"


def test_tracked_scan_fails_and_terminalizes_job_without_event_loop():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    server = {"id": "server-a", "name": "Server", "enabled": True}
    manager = EmbyLibraryScanManager(
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=tracker,
        trigger_library_scan=lambda *_args: (True, "ok"),
        fetch_libraries=lambda _server: ([{"id": "library-a"}], None),
        get_app_event_loop=lambda: None,
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
    )

    payload, status_code = manager.build_scan_library_tracked_snapshot(
        {"server_id": "server-a", "library_ids": ["library-a"]}
    )

    assert status_code == 503
    assert payload["success"] is False
    assert tracker.get_job(payload["job_id"])["status"] == "error"


def test_scan_trigger_cannot_cross_server_delete_fence():
    coordinator = UserMutationCoordinator(None)
    trigger_calls = []
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    server = {"id": "server-a", "name": "Server", "enabled": True}
    manager = EmbyLibraryScanManager(
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=tracker,
        trigger_library_scan=lambda *_args: trigger_calls.append(True) or (True, "ok"),
        fetch_libraries=lambda _server: ([{"id": "library-a"}], None),
        get_app_event_loop=lambda: None,
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
        server_mutation_guard=lambda server_id: coordinator.guard(
            [server_mutation_key(server_id)]
        ),
    )
    holder_started = threading.Event()
    release_holder = threading.Event()

    def hold_delete_fence():
        with coordinator.guard([server_mutation_key("server-a")]) as acquired:
            assert acquired is True
            holder_started.set()
            assert release_holder.wait(timeout=2)

    holder = threading.Thread(target=hold_delete_fence)
    holder.start()
    assert holder_started.wait(timeout=1)
    payload, status_code = manager.build_scan_library_tracked_snapshot(
        {"server_id": "server-a", "library_ids": ["library-a"]}
    )
    release_holder.set()
    holder.join(timeout=2)

    assert status_code == 409
    assert payload["success"] is False
    assert trigger_calls == []


def test_group_scan_fails_when_every_remote_trigger_is_rejected():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    server = {"id": "server-a", "name": "Server", "enabled": True}
    manager = EmbyLibraryScanManager(
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=tracker,
        trigger_library_scan=lambda *_args: (False, "upstream rejected"),
        fetch_libraries=lambda _server: ([{"id": "library-a"}], None),
        get_app_event_loop=lambda: None,
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
    )

    payload, status_code = manager.build_scan_group_tracked_snapshot(
        {
            "group_name": "Group",
            "libraries": [{"server_id": "server-a", "library_id": "library-a"}],
        }
    )

    assert status_code == 503
    assert payload["success"] is False
    assert tracker.get_job(payload["job_ids"][0])["status"] == "error"
