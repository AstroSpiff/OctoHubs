"""Regression coverage for blocking snapshot builders used by async routes."""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request


def _request(query_string: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": query_string,
        }
    )


async def _assert_builder_runs_off_event_loop(monkeypatch, module, attribute, route_call):
    started = threading.Event()
    release = threading.Event()

    def blocking_builder(*_args, **_kwargs):
        started.set()
        release.wait(timeout=1)
        return {"success": True}, 200

    monkeypatch.setattr(module, attribute, blocking_builder)
    route_task = asyncio.create_task(route_call())
    assert await asyncio.to_thread(started.wait, 0.5)

    await asyncio.sleep(0)
    assert route_task.done() is False

    release.set()
    response = await asyncio.wait_for(route_task, timeout=0.5)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_emby_runtime_snapshot_does_not_block_event_loop(monkeypatch):
    from emby_runtime import routes

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    await _assert_builder_runs_off_event_loop(
        monkeypatch,
        routes,
        "_build_emby_streams_snapshot",
        lambda: routes.emby_streams_api(_request()),
    )


@pytest.mark.anyio
async def test_service_connection_check_does_not_block_event_loop(monkeypatch):
    from services import manager, routes

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    await _assert_builder_runs_off_event_loop(
        monkeypatch,
        manager,
        "_build_test_connections_snapshot",
        lambda: routes.test_connections_api(_request()),
    )


@pytest.mark.anyio
async def test_search_snapshot_does_not_block_event_loop(monkeypatch):
    from search import routes

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    await _assert_builder_runs_off_event_loop(
        monkeypatch,
        routes,
        "_build_tmdb_search_snapshot",
        lambda: routes.tmdb_search(_request(), query="example", page=1),
    )


@pytest.mark.anyio
async def test_emby_library_snapshot_does_not_block_event_loop(monkeypatch):
    from emby_libraries import routes

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    await _assert_builder_runs_off_event_loop(
        monkeypatch,
        routes,
        "_build_grouped_libraries_snapshot",
        lambda: routes.grouped_libraries(_request()),
    )


@pytest.mark.anyio
async def test_latest_snapshot_does_not_block_event_loop(monkeypatch):
    from emby_latest import routes

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    await _assert_builder_runs_off_event_loop(
        monkeypatch,
        routes.api_handlers,
        "build_latest_snapshot_payload",
        lambda: routes.emby_latest(_request()),
    )


@pytest.mark.anyio
async def test_emby_server_list_storage_is_offloaded(monkeypatch):
    from emby_runtime import server_routes

    event_loop_thread = threading.get_ident()

    def load_servers():
        assert threading.get_ident() != event_loop_thread
        return []

    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(server_routes, "_load_stored_servers", load_servers)

    response = await server_routes.emby_servers_api(_request())

    assert response.status_code == 200


@pytest.mark.anyio
async def test_emby_action_targets_storage_is_offloaded(monkeypatch):
    from emby_actions import routes

    event_loop_thread = threading.get_ident()

    def targets():
        assert threading.get_ident() != event_loop_thread
        return []

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(routes, "_api_action_targets", targets)

    response = await routes.emby_action_targets(_request())

    assert response.status_code == 200


@pytest.mark.anyio
async def test_collection_options_reuses_the_offloaded_configuration(monkeypatch):
    from emby_collections import routes

    event_loop_thread = threading.get_ident()
    config = {"EMBY": {"SERVERS": []}, "MDBLIST_API_KEYS": ["key"]}

    def load():
        assert threading.get_ident() != event_loop_thread
        return config, True

    monkeypatch.setattr(routes, "load_config", load)
    monkeypatch.setattr(routes, "_active_trakt_settings", lambda: {})
    monkeypatch.setattr(
        routes,
        "is_mdblist_enabled",
        lambda supplied: supplied is config,
    )

    response = await routes.api_emby_collections_options(user={"id": 1})

    assert response["mdblist_enabled"] is True


@pytest.mark.anyio
async def test_emby_server_create_storage_and_probe_are_offloaded(monkeypatch):
    from emby_runtime import server_routes
    from emby_runtime.server_api_models import EmbyServerInput

    event_loop_thread = threading.get_ident()
    offloaded_calls = []

    def valid_configuration():
        assert threading.get_ident() != event_loop_thread
        offloaded_calls.append("config")

    def save_server(_values, _server_id):
        assert threading.get_ident() != event_loop_thread
        offloaded_calls.append("save")
        return {"id": "green", "alias": "Green", "enabled": True}, True

    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(server_routes, "_validate_csrf", lambda _request, _token: True)
    monkeypatch.setattr(server_routes, "_require_valid_configuration", valid_configuration)
    monkeypatch.setattr(server_routes, "_save_server_values", save_server)

    response = await server_routes.create_emby_server_api(
        _request(),
        EmbyServerInput(url="http://green:8096", alias="Green"),
    )

    assert response.status_code == 201
    assert offloaded_calls == ["config", "save"]


@pytest.mark.anyio
async def test_emby_server_update_storage_and_probe_are_offloaded(monkeypatch):
    from emby_runtime import server_routes
    from emby_runtime.server_api_models import EmbyServerInput

    event_loop_thread = threading.get_ident()
    offloaded_calls = []
    existing = {"id": "green", "url": "http://green:8096", "enabled": True}

    def valid_configuration():
        assert threading.get_ident() != event_loop_thread
        offloaded_calls.append("config")

    def load_servers():
        assert threading.get_ident() != event_loop_thread
        offloaded_calls.append("load")
        return [existing]

    def save_server(_values, server_id):
        assert threading.get_ident() != event_loop_thread
        offloaded_calls.append("save")
        return {**existing, "id": server_id}, False

    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(server_routes, "_validate_csrf", lambda _request, _token: True)
    monkeypatch.setattr(server_routes, "_require_valid_configuration", valid_configuration)
    monkeypatch.setattr(server_routes, "_load_stored_servers", load_servers)
    monkeypatch.setattr(server_routes, "_save_server_values", save_server)

    response = await server_routes.update_emby_server_api(
        "green",
        _request(),
        EmbyServerInput(url="http://green:8096"),
    )

    assert response.status_code == 200
    assert offloaded_calls == ["config", "load", "save"]


@pytest.mark.anyio
async def test_sync_authentication_dependency_is_offloaded(monkeypatch):
    from emby_runtime import routes

    event_loop_thread = threading.get_ident()

    def blocking_auth(_request):
        assert threading.get_ident() != event_loop_thread
        return 1

    monkeypatch.setattr(routes, "_require_auth", blocking_auth)
    monkeypatch.setattr(
        routes,
        "_build_emby_streams_snapshot",
        lambda: ({"success": True, "streams": []}, 200),
    )

    response = await routes.emby_streams_api(_request())

    assert response.status_code == 200


@pytest.mark.anyio
async def test_realtime_websocket_authentication_is_offloaded(monkeypatch):
    from realtime import routes

    event_loop_thread = threading.get_ident()

    def blocking_auth(_websocket):
        assert threading.get_ident() != event_loop_thread
        return 1

    class _WebSocket:
        headers = {}

        async def close(self, code=1000):
            self.close_code = code

    monkeypatch.setattr(routes, "_require_auth", blocking_auth)

    assert await routes._authorize_websocket(_WebSocket()) == 1


@pytest.mark.anyio
async def test_workflow_start_storage_is_offloaded(monkeypatch):
    from services import workflow_routes
    from services.workflow_api_models import WorkflowStartRequest

    event_loop_thread = threading.get_ident()

    def is_running():
        assert threading.get_ident() != event_loop_thread
        return False

    def start(**_kwargs):
        assert threading.get_ident() != event_loop_thread
        return True

    monkeypatch.setattr(workflow_routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(
        workflow_routes,
        "_success_response",
        lambda **payload: JSONResponse({"success": True, **payload}),
    )
    monkeypatch.setattr(workflow_routes.workflow_manager, "is_running", is_running)
    monkeypatch.setattr(workflow_routes.workflow_manager, "start", start)

    response = await workflow_routes.workflow_start(
        _request(),
        WorkflowStartRequest(type="full", context={}),
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_workflow_stop_storage_is_offloaded(monkeypatch):
    from services import workflow_routes

    event_loop_thread = threading.get_ident()
    calls = []

    def is_running():
        assert threading.get_ident() != event_loop_thread
        return True

    def stop():
        assert threading.get_ident() != event_loop_thread
        calls.append("stop")

    monkeypatch.setattr(workflow_routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(
        workflow_routes,
        "_success_response",
        lambda **payload: JSONResponse({"success": True, **payload}),
    )
    monkeypatch.setattr(workflow_routes.workflow_manager, "is_running", is_running)
    monkeypatch.setattr(workflow_routes.workflow_manager, "stop", stop)

    response = await workflow_routes.workflow_stop(_request())

    assert response.status_code == 200
    assert calls == ["stop"]


@pytest.mark.anyio
async def test_workflow_sse_status_storage_is_offloaded(monkeypatch):
    from realtime import routes

    event_loop_thread = threading.get_ident()

    class _Lease:
        def release(self):
            return None

    def get_status():
        assert threading.get_ident() != event_loop_thread
        return {"status": "completed"}

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(routes, "acquire_connection", lambda _subject, _kind: _Lease())
    monkeypatch.setattr(routes.workflow_manager, "get_status", get_status)

    response = await routes.workflow_events(_request())
    first_event = await anext(response.body_iterator)
    await response.body_iterator.aclose()

    assert '"status": "completed"' in first_event


@pytest.mark.anyio
async def test_torrent_zip_compression_is_offloaded(monkeypatch):
    from search import routes
    from web.research_api_models import LinkBatchPayload

    started = threading.Event()
    release = threading.Event()
    event_loop_thread = threading.get_ident()

    def blocking_archive(_downloads):
        assert threading.get_ident() != event_loop_thread
        started.set()
        release.wait(timeout=1)
        return b"archive", 1, []

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(routes, "_validate_csrf", lambda _request, _token: True)
    monkeypatch.setattr(
        routes,
        "_download_torrent_file",
        lambda _link, _max_bytes: (b"torrent", "file.torrent", None),
    )
    monkeypatch.setattr(routes, "_build_torrent_archive", blocking_archive)

    task = asyncio.create_task(
        routes.torrent_zip_api(
            _request(),
            LinkBatchPayload(links=["https://indexer.example/file.torrent"]),
        )
    )
    assert await asyncio.to_thread(started.wait, 0.5)
    await asyncio.sleep(0)
    assert task.done() is False
    release.set()

    response = await asyncio.wait_for(task, timeout=0.5)
    assert response.body == b"archive"


@pytest.mark.anyio
async def test_torrent_zip_stops_downloading_when_aggregate_budget_is_exhausted(monkeypatch):
    from search import routes
    from web.research_api_models import LinkBatchPayload

    chunk = b"x" * (10 * 1024 * 1024)
    calls: list[tuple[str, int]] = []

    def bounded_download(link, max_bytes):
        calls.append((link, max_bytes))
        assert max_bytes >= len(chunk)
        return chunk, f"{len(calls)}.torrent", None

    monkeypatch.setattr(routes, "_require_auth", lambda _request: 1)
    monkeypatch.setattr(routes, "_validate_csrf", lambda _request, _token: True)
    monkeypatch.setattr(routes, "_download_torrent_file", bounded_download)

    response = await routes.torrent_zip_api(
        _request(),
        LinkBatchPayload(links=[f"https://indexer.example/{index}" for index in range(25)]),
    )

    assert response.status_code == 200
    assert len(calls) == 5
    assert [remaining for _link, remaining in calls] == [
        50 * 1024 * 1024,
        40 * 1024 * 1024,
        30 * 1024 * 1024,
        20 * 1024 * 1024,
        10 * 1024 * 1024,
    ]
