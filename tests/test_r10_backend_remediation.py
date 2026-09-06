"""Regression tests for tenth-pass backend and container remediations."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_refuses_to_run_with_an_unpersistable_generated_secret(tmp_path):
    (tmp_path / ".env").mkdir()
    command_marker = tmp_path / "command-ran"
    environment = os.environ.copy()
    environment["PATH"] = f"{PROJECT_ROOT / 'venv' / 'bin'}:{environment.get('PATH', '')}"
    environment.update(
        {
            "OCTOHUBS_CONFIG_DIR": str(tmp_path),
            "OCTOHUBS_DB_HOST": "database.example.test",
            "SECRET_KEY": "change-this-secret-key",
            "PASSWORD_SECRET": "stable-password-secret-for-tests",
        }
    )

    result = subprocess.run(
        [
            "sh",
            str(PROJECT_ROOT / "docker-entrypoint.sh"),
            "/usr/bin/touch",
            str(command_marker),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "refusing an ephemeral session key" in result.stdout
    assert not command_marker.exists()


def test_password_secret_pair_is_atomic_when_persistence_fails(tmp_path):
    env_file = tmp_path / ".env"
    original = "SECRET_KEY=stable-session-secret-for-tests!\n"
    env_file.write_text(original, encoding="utf-8")
    command_marker = tmp_path / "command-ran"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_mv = fake_bin / "mv"
    fake_mv.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_mv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = (
        f"{fake_bin}:{PROJECT_ROOT / 'venv' / 'bin'}:{environment.get('PATH', '')}"
    )
    environment.update(
        {
            "OCTOHUBS_CONFIG_DIR": str(tmp_path),
            "OCTOHUBS_DB_HOST": "database.example.test",
            "SECRET_KEY": "stable-session-secret-for-tests!",
        }
    )
    environment.pop("PASSWORD_SECRET", None)
    environment.pop("PASSWORD_SECRET_PREVIOUS", None)

    result = subprocess.run(
        [
            "sh",
            str(PROJECT_ROOT / "docker-entrypoint.sh"),
            "/usr/bin/touch",
            str(command_marker),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "refusing an ephemeral encryption key" in result.stdout
    assert env_file.read_text(encoding="utf-8") == original
    assert not command_marker.exists()


@pytest.mark.parametrize(
    "identifier",
    [
        "../../System/Shutdown",
        "..%2f..%2fSystem%2fShutdown",
        "library/child",
        r"library\\child",
        "library?Recursive=false",
        "library#fragment",
    ],
)
def test_emby_path_identifiers_reject_delimiters_and_encoded_traversal(identifier):
    from emby_libraries.scan_api_models import ScanLibraryRequest
    from emby_runtime.runtime_api_models import EmbyTaskStopRequest

    with pytest.raises(ValidationError):
        ScanLibraryRequest.model_validate(
            {"server_id": "green", "library_id": identifier}
        )
    with pytest.raises(ValidationError):
        EmbyTaskStopRequest.model_validate(
            {"server_id": "green", "task_id": identifier}
        )


def test_emby_clients_reject_unsafe_identifiers_without_outbound_requests(monkeypatch):
    from emby_runtime import api_clients_emby

    outbound: list[str] = []
    monkeypatch.setattr(
        api_clients_emby,
        "_call_emby_api",
        lambda _server, path, **_kwargs: outbound.append(path) or (True, {}),
    )

    assert api_clients_emby._trigger_library_scan(
        {"id": "green"}, "../../System/Shutdown"
    )[0] is False
    assert api_clients_emby._stop_emby_task(
        {"id": "green"}, "task/../../System/Shutdown"
    )[0] is False
    assert outbound == []


def test_library_scan_requires_current_inventory_membership():
    from emby_libraries.scan_manager import EmbyLibraryScanManager

    outbound: list[str] = []
    manager = EmbyLibraryScanManager(
        load_config=lambda: (
            {"EMBY": {"SERVERS": [{"id": "green", "enabled": True}]}},
            True,
        ),
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=SimpleNamespace(),
        trigger_library_scan=lambda _server, library_id, _scan_type="content": (
            outbound.append(library_id) or True,
            "ok",
        ),
        fetch_libraries=lambda _server: ([{"id": "known-library"}], None),
        get_app_event_loop=lambda: None,
        emby_api_client_cls=object,
        log_flush=lambda _message: None,
    )

    payload, status = manager.build_scan_library_snapshot(
        {"server_id": "green", "library_id": "unknown-library"}
    )

    assert status == 404
    assert payload["success"] is False
    assert outbound == []

    success_payload, success_status = manager.build_scan_library_snapshot(
        {"server_id": "green", "library_id": "known-library"}
    )
    assert success_status == 200
    assert success_payload["success"] is True
    assert outbound == ["known-library"]


def test_stop_task_requires_a_current_running_task(monkeypatch):
    from emby_runtime import snapshots

    stopped: list[str] = []
    monkeypatch.setattr(
        snapshots,
        "load_config",
        lambda: ({"EMBY": {"SERVERS": [{"id": "green", "enabled": True}]}}, True),
    )
    monkeypatch.setattr(
        snapshots,
        "_fetch_emby_scheduled_tasks",
        lambda _server: ([{"id": "running-task", "is_running": True}], None),
    )
    monkeypatch.setattr(
        snapshots,
        "_stop_emby_task",
        lambda _server, task_id: (stopped.append(task_id) or True, {}),
    )

    payload, status = snapshots._build_emby_stop_task_snapshot(
        {"server_id": "green", "task_id": "other-task"}
    )

    assert status == 404
    assert payload["success"] is False
    assert stopped == []

    success_payload, success_status = snapshots._build_emby_stop_task_snapshot(
        {"server_id": "green", "task_id": "running-task"}
    )
    assert success_status == 200
    assert success_payload["success"] is True
    assert stopped == ["running-task"]


def test_scan_batches_are_deduplicated_and_bounded():
    from emby_libraries.scan_api_models import (
        TrackedGroupScanRequest,
        TrackedScanLibraryRequest,
    )
    from emby_libraries.scan_limits import MAX_SCAN_LIBRARIES_PER_SERVER

    request = TrackedScanLibraryRequest.model_validate(
        {
            "server_id": "green",
            "library_ids": ["movies", "movies", "series"],
        }
    )
    assert request.library_ids == ["movies", "series"]

    with pytest.raises(ValidationError):
        TrackedGroupScanRequest.model_validate(
            {
                "group_name": "oversized",
                "libraries": [
                    {"server_id": "green", "library_id": f"library-{index}"}
                    for index in range(MAX_SCAN_LIBRARIES_PER_SERVER + 1)
                ],
            }
        )


def _auth_request(*, method: str, bearer: str, session: dict[str, int]):
    return SimpleNamespace(
        method=method,
        session=session,
        scope={"type": "http", "path": "/api/configuration/services"},
        headers={"Authorization": f"Bearer {bearer}"},
        state=SimpleNamespace(),
    )


@pytest.mark.parametrize("dependency_name", ["require_auth", "get_current_user_optional"])
def test_invalid_bearer_never_falls_back_to_a_valid_cookie(
    monkeypatch,
    dependency_name,
):
    from web import session_auth

    session_lookup: list[int] = []
    monkeypatch.setattr("core.auth.verify_api_token", lambda _token: None)
    monkeypatch.setattr(
        "core.auth.get_user_by_id",
        lambda user_id: session_lookup.append(user_id)
        or SimpleNamespace(id=user_id, is_active=True, auth_epoch=0),
    )
    dependency = getattr(session_auth, dependency_name)

    with pytest.raises(HTTPException) as error:
        dependency(_auth_request(method="GET", bearer="revoked", session={"user_id": 7}))

    assert error.value.status_code == 401
    assert session_lookup == []


@pytest.mark.anyio
async def test_valid_bearer_with_cookie_is_not_blocked_by_csrf(monkeypatch):
    from web.csrf_protection import SessionCsrfProtectionMiddleware

    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {
            "user": user,
            "token": SimpleNamespace(id=910_003),
            "scopes": ["write:configuration"],
        },
    )
    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/configuration/services",
            "raw_path": b"/api/configuration/services",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer valid-token")],
            "scheme": "http",
            "server": ("testserver", 80),
            "session": {"user_id": 7},
        }
    )
    middleware = SessionCsrfProtectionMiddleware(lambda *_args, **_kwargs: None)
    reached_route = False

    async def call_next(_request: Request) -> Response:
        nonlocal reached_route
        reached_route = True
        return Response(status_code=204)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 204
    assert reached_route is True
    assert request.state.auth_method == "api_token"


@pytest.mark.anyio
async def test_invalid_bearer_with_cookie_is_rejected_before_csrf(monkeypatch):
    from web.csrf_protection import SessionCsrfProtectionMiddleware

    monkeypatch.setattr("core.auth.verify_api_token", lambda _token: None)
    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/configuration/services",
            "raw_path": b"/api/configuration/services",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer revoked-token")],
            "scheme": "http",
            "server": ("testserver", 80),
            "session": {"user_id": 7},
        }
    )
    middleware = SessionCsrfProtectionMiddleware(lambda *_args, **_kwargs: None)
    reached_route = False

    async def call_next(_request: Request) -> Response:
        nonlocal reached_route
        reached_route = True
        return Response(status_code=204)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    assert reached_route is False


def test_account_update_contract_rejects_explicit_null_active_state():
    from web.account_api_models import AccountUpdateRequest

    assert AccountUpdateRequest.model_validate({}).model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        AccountUpdateRequest.model_validate({"is_active": None})
