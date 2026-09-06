"""Secret-redaction coverage for service health checks."""

from __future__ import annotations

import json
import threading

import pytest
import requests


CANARY_SECRET = "health-canary-secret"
CANARY_URL = f"https://remote.example/status?apikey={CANARY_SECRET}"


def _http_error_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 401
    response.url = CANARY_URL
    response.request = requests.Request("GET", CANARY_URL).prepare()
    response._content = f"rejected {CANARY_SECRET}".encode()
    return response


def _raise_canary_error():
    raise RuntimeError(CANARY_URL)


def test_mdblist_and_omdb_errors_never_include_request_secrets(monkeypatch):
    from services import health

    monkeypatch.setattr(health.requests, "get", lambda *_args, **_kwargs: _http_error_response())

    mdblist = health._ping_mdblist({"MDBLIST_API_KEYS": [CANARY_SECRET]})
    omdb = health._ping_omdb({"OMDB_API_KEYS": [CANARY_SECRET]})
    serialized = json.dumps({"mdblist": mdblist, "omdb": omdb})

    assert mdblist[0] is False
    assert omdb[0] is False
    assert "HTTP 401" in serialized
    assert CANARY_SECRET not in serialized
    assert CANARY_URL not in serialized


def test_connection_snapshot_and_console_output_hide_request_secrets(
    monkeypatch,
    capsys,
):
    from app_state import set_connection_check_state
    from core import config_manager
    from services import health, manager

    config = {
        "MDBLIST_API_KEYS": [CANARY_SECRET],
        "OMDB_API_KEYS": [CANARY_SECRET],
        "DATABASE": {"ENABLED": False},
    }
    monkeypatch.setattr(config_manager, "load_config", lambda: (config, True))
    monkeypatch.setattr(health.requests, "get", lambda *_args, **_kwargs: _http_error_response())
    monkeypatch.setattr(health, "_ping_jellyseerr", lambda _config: (True, "Connessione OK"))
    monkeypatch.setattr(health, "_ping_prowlarr", lambda _config: (True, "Connessione OK"))
    monkeypatch.setattr(health, "_ping_database", lambda _config: (True, "Connessione OK", True))
    monkeypatch.setattr(health, "_ping_trakt", lambda _config: (False, "Non configurato", False))
    monkeypatch.setattr(health, "_ping_jackett", lambda _config: (False, "Non configurato", False))
    monkeypatch.setattr(health, "_ping_justwatch", lambda _config: (False, "Non configurato", False))

    try:
        payload, status_code = manager._build_test_connections_snapshot()
        health._check_service_connection(
            health._ping_mdblist,
            config,
            "MDBList",
            "MDBList non risponde",
        )
    finally:
        set_connection_check_state({}, None)

    exposed = json.dumps(payload) + capsys.readouterr().out
    assert status_code == 200
    assert CANARY_SECRET not in exposed
    assert CANARY_URL not in exposed


def test_system_status_uses_a_generic_message_when_health_collection_fails(
    monkeypatch,
):
    from services import manager
    from web.config_routes import _system_services_section

    monkeypatch.setattr(
        manager,
        "_build_test_connections_snapshot",
        _raise_canary_error,
    )

    section = _system_services_section({}, check_services=True)
    serialized = json.dumps(section)

    assert "Verifica dei servizi non riuscita" in serialized
    assert CANARY_SECRET not in serialized
    assert CANARY_URL not in serialized


@pytest.mark.anyio
async def test_connection_check_api_uses_a_generic_message_when_collection_fails(
    monkeypatch,
):
    from services import manager, routes

    routes.init_service_routes(require_auth=lambda _request: {"username": "admin"})
    monkeypatch.setattr(
        manager,
        "_build_test_connections_snapshot",
        _raise_canary_error,
    )

    response = await routes.test_connections_api(object())
    serialized = response.body.decode("utf-8")

    assert response.status_code == 500
    assert "Verifica dei servizi non riuscita" in serialized
    assert CANARY_SECRET not in serialized
    assert CANARY_URL not in serialized


def test_live_connection_checks_are_singleflight_and_cached(monkeypatch):
    from services.connection_check_guard import ConnectionCheckCoordinator

    monkeypatch.setenv("SERVICE_CONNECTION_CHECK_COOLDOWN_SECONDS", "30")
    coordinator = ConnectionCheckCoordinator()
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def build():
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(1)
        return {"success": True, "statuses": {}}, 200

    first_result = []
    worker = threading.Thread(target=lambda: first_result.append(coordinator.run(build)))
    worker.start()
    assert entered.wait(0.5)
    duplicate_payload, duplicate_status = coordinator.run(build)
    assert duplicate_status == 409
    assert duplicate_payload["success"] is False
    release.set()
    worker.join(1)

    assert first_result == [({"success": True, "statuses": {}}, 200)]
    assert coordinator.run(build) == ({"success": True, "statuses": {}}, 200)
    assert calls == 1


def test_connection_check_cache_is_not_reused_after_builder_replacement():
    from services.connection_check_guard import ConnectionCheckCoordinator

    coordinator = ConnectionCheckCoordinator()
    assert coordinator.run(lambda: ({"success": True}, 200)) == (
        {"success": True},
        200,
    )

    def replacement():
        raise RuntimeError("replacement failed")

    with pytest.raises(RuntimeError, match="replacement failed"):
        coordinator.run(replacement)


def test_live_health_checks_bound_provider_key_lists(monkeypatch):
    from services import health

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"title": "Example", "Title": "Example", "Response": "True"}

    monkeypatch.setattr(
        health.requests,
        "get",
        lambda *_args, **kwargs: calls.append(kwargs["params"]) or Response(),
    )
    assert health._ping_mdblist({"MDBLIST_API_KEYS": [str(i) for i in range(50)]})[0]
    assert len(calls) == health.SERVICE_HEALTH_MAX_API_KEYS

    calls.clear()
    assert health._ping_omdb({"OMDB_API_KEYS": [str(i) for i in range(50)]})[0]
    assert len(calls) == health.SERVICE_HEALTH_MAX_API_KEYS


def test_connection_check_coordinator_resets_between_lifespans(monkeypatch):
    from services.connection_check_guard import ConnectionCheckCoordinator

    monkeypatch.setenv("SERVICE_CONNECTION_CHECK_COOLDOWN_SECONDS", "30")
    coordinator = ConnectionCheckCoordinator()
    calls = []

    def build():
        calls.append(len(calls) + 1)
        return {"success": True, "generation": calls[-1]}, 200

    assert coordinator.run(build)[0]["generation"] == 1
    assert coordinator.run(build)[0]["generation"] == 1
    coordinator.reset()  # shutdown of lifespan one
    coordinator.reset()  # startup of lifespan two
    assert coordinator.run(build)[0]["generation"] == 2
    assert calls == [1, 2]
