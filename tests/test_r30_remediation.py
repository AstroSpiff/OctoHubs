"""Deterministic canaries for the thirtieth-pass remediation."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.storage import StorageError
from emby_users.favorites_manager import FavoritesManager
from emby_users.playlists_manager import PlaylistsManager


def _favorite_merge_manager(fetch):
    writes = []
    manager = FavoritesManager(
        get_server_by_id=lambda server_id: {"id": server_id, "name": server_id},
        fetch_favorites=fetch,
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args, **_kwargs: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        set_favorite=lambda *args: (writes.append(args) or True, None),
    )
    return manager, writes


def _playlist_merge_manager(fetch_playlists, fetch_items):
    mutations = []
    manager = PlaylistsManager(
        get_server_by_id=lambda server_id: {"id": server_id, "name": server_id},
        fetch_playlists=fetch_playlists,
        fetch_playlist_items=fetch_items,
        fetch_all_media_for_user=lambda *_args: ([], None),
        fetch_items_by_provider_ids=lambda *_args: ([], None),
        fetch_items_by_safe_fallback=lambda *_args: ([], None),
        create_playlist=lambda *args: (mutations.append(("create", args)) or True, {"Id": "p"}),
        add_playlist_items=lambda *args: (mutations.append(("add", args)) or True, None),
        remove_playlist_entries=lambda *args: (mutations.append(("remove", args)) or True, None),
        delete_playlist=lambda *args: (mutations.append(("delete", args)) or True, None),
    )
    return manager, mutations


@pytest.mark.parametrize("domain", ["favorites", "playlists"])
def test_merge_bootstrap_has_an_all_sources_read_barrier(domain):
    if domain == "favorites":
        manager, mutations = _favorite_merge_manager(
            lambda server, _user: ([{"ProviderIds": {"Tmdb": "1"}}], None)
            if server["id"] == "good" else ([], "unavailable")
        )
        result = manager.sync_merge_favorites([("good", "a"), ("bad", "b")])
    else:
        manager, mutations = _playlist_merge_manager(
            lambda server, _user: ([{"Id": "p", "Name": "Keep"}], None)
            if server["id"] == "good" else ([], "unavailable"),
            lambda *_args: ([{"ProviderIds": {"Tmdb": "1"}}], None),
        )
        result = manager.sync_merge_playlists([("good", "a"), ("bad", "b")])

    assert "incomplete source snapshot" in result["error"]
    assert mutations == []


def test_request_scan_does_not_replace_data_when_jellyseerr_is_unavailable():
    from services.request_scan_pipeline import run_request_scan

    with patch("services.request_scan_pipeline.get_jellyseerr_requests", return_value=([], False)), patch(
        "services.request_scan_pipeline.load_results_file"
    ) as load, patch("services.request_scan_pipeline.save_results") as save:
        with pytest.raises(RuntimeError, match="dataset unavailable"):
            run_request_scan({}, search_executor=lambda *_args, **_kwargs: None)
    load.assert_not_called()
    save.assert_not_called()


def test_dashboard_refresh_does_not_persist_an_unavailable_jellyseerr_dataset():
    from core.tasks import AutoScheduler

    saved = []
    completed = []
    scheduler = AutoScheduler()
    scheduler.set_callbacks(
        process_requests_func=lambda *_args, **_kwargs: None,
        refresh_snapshot_func=lambda _config: (_ for _ in ()).throw(
            RuntimeError("Jellyseerr unavailable")
        ),
    )
    try:
        assert scheduler._trigger_refresh({}, completion_callback=completed.append)
        assert scheduler._worker_pool.wait(2)
        assert saved == []
        assert completed == [False]
    finally:
        scheduler.stop()
        scheduler.wait(2)


@pytest.mark.parametrize("operation", ["load", "save"])
def test_scan_result_storage_failures_propagate(operation):
    from services import scan_results

    backend = SimpleNamespace(
        load_last_result=lambda: (_ for _ in ()).throw(StorageError("read failed")),
        save_scan_result=lambda _value: (_ for _ in ()).throw(StorageError("write failed")),
    )
    with patch("services.scan_results._ensure_db_backend", return_value=backend):
        with pytest.raises(StorageError):
            scan_results.load_results_file() if operation == "load" else scan_results.save_results({})


def test_probe_workflow_rejects_partial_and_stale_terminal_outcomes(monkeypatch):
    from services import workflows

    state = {
        "combo_recent": {
            "run_id": "current",
            "running": False,
            "last_run": {"run_id": "current", "status": "partial"},
        }
    }
    monkeypatch.setattr(workflows, "get_probe_manager", lambda: SimpleNamespace(
        _global_workers={}, get_status=lambda _server_id: state
    ))
    monkeypatch.setattr(workflows, "load_config", lambda: (
        {"EMBY": {"SERVERS": [{"id": "s1", "enabled": True}]}}, True
    ))

    with pytest.raises(RuntimeError, match="verificare il completamento Probe"):
        workflows._wf_check_probe({"_probe_run_id": "current", "_probe_server_ids": ["s1"]})
    state["combo_recent"]["last_run"] = {"run_id": "old", "status": "completed"}
    with pytest.raises(RuntimeError, match="verificare il completamento Probe"):
        workflows._wf_check_probe({"_probe_run_id": "current", "_probe_server_ids": ["s1"]})


def test_workflow_joins_exact_latest_refresh_outcome(monkeypatch):
    from services import workflows

    class Manager:
        progress_tracker = SimpleNamespace(get_snapshot=lambda: {})
        def is_refreshing(self): return True
        def active_refresh_generation(self): return 7
        def wait_for_refresh(self, generation, _timeout):
            assert generation == 7
            return {"generation": 7, "payload": None, "error": "run seven failed"}
        def get_snapshot(self, mode="batch"): return {"payload": {"old": True}}

    monkeypatch.setattr(workflows, "load_config", lambda: ({}, True))
    monkeypatch.setattr("emby_latest.settings._load_latest_settings", lambda: {"SETTINGS": {}})
    monkeypatch.setattr(workflows, "get_emby_latest_manager", Manager)
    monkeypatch.setattr("services.latest_jellyseerr.refresh_latest_jellyseerr_requests", lambda _config: ({"success": True}, 200))
    with pytest.raises(RuntimeError, match="run seven failed"):
        workflows._wf_refresh_cache({})


def test_latest_refresh_waiter_receives_only_its_generation():
    from emby_latest.manager import EmbyLatestManager

    manager = EmbyLatestManager.__new__(EmbyLatestManager)
    manager._lock = threading.Lock()
    manager._refresh_condition = threading.Condition(manager._lock)
    manager._refreshing = False
    manager._refresh_generation = 0
    manager._refresh_outcomes = {}
    generation = manager._begin_refresh()
    assert generation == 1
    manager._finish_refresh(1, None, "failed")
    manager._refresh_outcomes[2] = {"generation": 2, "payload": {"new": True}, "error": None}
    assert manager.wait_for_refresh(1, 0.1)["error"] == "failed"


def test_probe_csv_fails_before_200_when_a_later_page_fails(monkeypatch):
    from emby_probe import routes

    def page(_server, _retry, _error, _scope, _limit, offset):
        if offset == "0":
            return {"blacklist": [], "next_offset": 1}, 200
        return {"success": False, "message": "page unavailable"}, 503

    monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 1)
    monkeypatch.setattr(routes, "load_config", lambda: ({}, True))
    monkeypatch.setattr(routes, "_probe_blacklist_get_snapshot", page)
    response = asyncio.run(routes.probe_export_csv(SimpleNamespace(
        query_params={"server_id": "s1", "scope": "libraries"}
    )))
    assert response.status_code == 503


def test_collection_image_url_logs_are_redacted_and_single_line(caplog):
    from emby_collections.collection_emby import _set_collection_poster

    caplog.set_level(logging.INFO)
    with patch("emby_collections.collection_emby._call_emby_api", return_value=(True, {})):
        _set_collection_poster({}, "collection\nforged", "https://u:p@example.test/p.jpg?token=SECRET#frag")
    text = caplog.text
    assert "SECRET" not in text and "u:p" not in text and "\nforged" not in text


def test_provider_info_urls_allow_only_credential_free_http():
    from search.download_references import protect_download_references

    with patch("search.download_references._normalize_owner_id", return_value=1):
        assert "web" not in protect_download_references({"web": "data:text/html,boom"}, 1)
        assert "web" not in protect_download_references({"web": "https://u:p@example.test/x"}, 1)
        assert protect_download_references({"web": "https://example.test/x"}, 1)["web"].startswith("https://")


def test_chunked_oversized_image_is_rejected_before_streaming():
    from emby_libraries.image_snapshots import _MAX_IMAGE_BYTES, _build_emby_image_stream

    class Response:
        headers = {"Content-Type": "image/jpeg"}
        is_redirect = is_permanent_redirect = False
        def raise_for_status(self): pass
        def iter_content(self, chunk_size):
            yield b"x" * (_MAX_IMAGE_BYTES // 2 + 1)
            yield b"y" * (_MAX_IMAGE_BYTES // 2 + 1)
        def close(self): pass

    config = {"EMBY": {"SERVERS": [{"id": "s1", "url": "https://emby.test", "api_key": "key"}]}}
    with patch("emby_libraries.image_snapshots.load_config", return_value=(config, True)), patch(
        "emby_libraries.image_snapshots.requests.get", return_value=Response()
    ):
        stream, _content_type, error, status = _build_emby_image_stream("s1", "item")
    assert stream is None and status == 502 and error["message"] == "Immagine troppo grande"


def test_removed_legacy_storage_shim_stays_absent():
    assert not (Path(__file__).resolve().parents[1] / "core" / "storage_utils.py").exists()


@pytest.mark.parametrize("module_name", ["storage_models.py", "storage_errors.py"])
def test_all_removed_legacy_storage_shims_stay_absent(module_name):
    assert not (Path(__file__).resolve().parents[1] / "core" / module_name).exists()


def test_application_sources_do_not_import_removed_legacy_storage_modules():
    project_root = Path(__file__).resolve().parents[1]
    source_roots = [
        project_root / name
        for name in (
            "core",
            "emby_actions",
            "emby_collections",
            "emby_latest",
            "emby_libraries",
            "emby_probe",
            "emby_runtime",
            "emby_users",
            "realtime",
            "runtime",
            "search",
            "services",
            "telegram",
            "web",
        )
    ]
    forbidden_imports = (
        "core.storage_models",
        "core.storage_errors",
        "core.storage_utils",
    )

    violations = []
    for source_root in source_roots:
        for source_path in source_root.rglob("*.py"):
            source = source_path.read_text(encoding="utf-8")
            if any(module_name in source for module_name in forbidden_imports):
                violations.append(str(source_path.relative_to(project_root)))

    assert violations == []
