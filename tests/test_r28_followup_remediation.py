from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, cast

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from starlette.requests import Request

from emby_libraries import routes as library_routes
from emby_libraries.scan_coordination import scan_lifecycle_guard
from emby_libraries.scan_manager import EmbyLibraryScanManager
from emby_libraries.tracker import LibraryScanTracker
from emby_runtime import server_routes
from emby_users.api_models import CloneUserRequest, CreateUsersRequest


def _request(method: str) -> Request:
    return Request({"type": "http", "method": method, "path": "/", "headers": []})


def _prepare_server_route(monkeypatch) -> None:
    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: None)
    monkeypatch.setattr(server_routes, "_validate_json_csrf", lambda _request: None)
    monkeypatch.setattr(server_routes, "_require_valid_configuration", lambda: None)


def test_server_save_wins_fence_before_delete_quiesces(monkeypatch):
    _prepare_server_route(monkeypatch)
    save_started = threading.Event()
    release_save = threading.Event()
    quiesced: list[str] = []
    save_result: list[tuple[dict[str, str], bool]] = []

    def save_guarded(_values, server_id):
        save_started.set()
        assert release_save.wait(timeout=2)
        return {"id": server_id or "new-server"}, False

    async def quiesce(server_id):
        quiesced.append(server_id)

    monkeypatch.setattr(server_routes, "_save_server_values_guarded", save_guarded)
    monkeypatch.setattr(server_routes, "_quiesce_server", quiesce)

    worker = threading.Thread(
        target=lambda: save_result.append(
            server_routes._save_server_values({}, "server-a")
        )
    )
    worker.start()
    assert save_started.wait(timeout=1)
    try:
        with pytest.raises(HTTPException) as raised:
            asyncio.run(server_routes.delete_emby_server_api("server-a", _request("DELETE")))
        assert raised.value.status_code == 409
        assert quiesced == []
    finally:
        release_save.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert save_result == [({"id": "server-a"}, False)]


def test_server_delete_wins_fence_prevents_late_save_and_runtime_allow(monkeypatch):
    _prepare_server_route(monkeypatch)
    delete_quiescing = threading.Event()
    release_delete = threading.Event()
    runtime_allows: list[str] = []
    delete_responses = []

    async def quiesce(_server_id):
        delete_quiescing.set()
        await asyncio.to_thread(release_delete.wait, 2)

    monkeypatch.setattr(server_routes, "_quiesce_server", quiesce)
    monkeypatch.setattr(
        server_routes,
        "_remove_server_value",
        lambda server_id: {"id": server_id, "name": "Server"},
    )
    monkeypatch.setattr(server_routes, "_allow_server_runtime", runtime_allows.append)
    monkeypatch.setattr(
        server_routes,
        "_save_server_values_guarded",
        lambda *_args: pytest.fail("Il salvataggio non deve superare la fence DELETE"),
    )

    def delete_server():
        delete_responses.append(
            asyncio.run(server_routes.delete_emby_server_api("server-a", _request("DELETE")))
        )

    worker = threading.Thread(target=delete_server)
    worker.start()
    assert delete_quiescing.wait(timeout=1)
    try:
        with pytest.raises(server_routes.EmbyServerLifecycleBusyError):
            server_routes._save_server_values({}, "server-a")
        assert runtime_allows == []
    finally:
        release_delete.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert delete_responses[0].status_code == 200
    assert runtime_allows == []


def test_scan_reset_cannot_cross_reserve_trigger_schedule_transaction(monkeypatch):
    trigger_started = threading.Event()
    release_trigger = threading.Event()
    reset_calls: list[bool] = []
    scan_result = []
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    server = {"id": "server-a", "name": "Server", "enabled": True}

    class RunningLoop:
        @staticmethod
        def is_running():
            return True

    class Poller:
        @staticmethod
        def schedule_tracking_library(*_args, **_kwargs):
            return True

    def trigger(
        server: dict[str, Any],
        library_id: str,
        scan_type: str = "content",
    ):
        del server, library_id, scan_type
        trigger_started.set()
        assert release_trigger.wait(timeout=2)
        return True, "ok"

    def fetch_libraries(server: dict[str, Any]):
        del server
        return [{"id": "library-a"}], None

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
        trigger_library_scan=trigger,
        fetch_libraries=fetch_libraries,
        get_app_event_loop=lambda: cast(asyncio.AbstractEventLoop, RunningLoop()),
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
    )
    monkeypatch.setattr(
        "emby_runtime.library_poller.get_library_poller",
        lambda: Poller(),
    )
    monkeypatch.setattr(library_routes, "_require_auth", lambda _request: None)
    monkeypatch.setattr(library_routes, "_validate_csrf", lambda *_args: True)
    monkeypatch.setattr(library_routes, "_load_config", lambda: ({"EMBY": {}}, True))
    monkeypatch.setattr(library_routes, "_ensure_db_backend", lambda: object())

    async def clear_state():
        reset_calls.append(True)

    monkeypatch.setattr(library_routes, "_clear_library_scan_state", clear_state)

    worker = threading.Thread(
        target=lambda: scan_result.append(
            manager.build_scan_library_tracked_snapshot(
                {"server_id": "server-a", "library_ids": ["library-a"]}
            )
        )
    )
    worker.start()
    assert trigger_started.wait(timeout=1)
    try:
        response = asyncio.run(library_routes.scan_jobs_reset(_request("POST")))
        assert response.status_code == 409
        assert json.loads(bytes(response.body))["success"] is False
        assert reset_calls == []
    finally:
        release_trigger.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    payload, status_code = scan_result[0]
    assert status_code == 200
    assert tracker.get_job(payload["job_id"]) is not None


def test_group_scan_uses_same_reset_fence():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)

    def trigger(
        server: dict[str, Any],
        library_id: str,
        scan_type: str = "content",
    ):
        del server, library_id, scan_type
        return True, "ok"

    def fetch_libraries(server: dict[str, Any]):
        del server
        return [], None

    manager = EmbyLibraryScanManager(
        load_config=lambda: ({"EMBY": {"SERVERS": []}}, True),
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=tracker,
        trigger_library_scan=trigger,
        fetch_libraries=fetch_libraries,
        get_app_event_loop=lambda: None,
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
    )

    with scan_lifecycle_guard() as acquired:
        assert acquired is True
        payload, status_code = manager.build_scan_group_tracked_snapshot(
            {
                "group_name": "Group",
                "libraries": [{"server_id": "server-a", "library_id": "library-a"}],
            }
        )

    assert status_code == 409
    assert payload["success"] is False
    assert tracker.get_all_jobs() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"targets": [{"server_id": "s" * 900_000, "username": "alice"}]},
        {
            "source_server_id": "s" * 900_000,
            "source_user_id": "user-a",
            "target_server_id": "server-b",
        },
        {
            "source_server_id": "server-a",
            "source_user_id": "user-a",
            "target_server_id": "t" * 900_000,
        },
    ],
)
def test_user_mutation_models_reject_unbounded_server_ids(payload):
    model = CreateUsersRequest if "targets" in payload else CloneUserRequest

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_user_mutation_models_accept_canonical_server_id_boundary():
    server_id = "s" * 128

    request = CreateUsersRequest.model_validate(
        {"targets": [{"server_id": server_id, "username": "alice"}]}
    )

    assert request.targets[0].server_id == server_id
