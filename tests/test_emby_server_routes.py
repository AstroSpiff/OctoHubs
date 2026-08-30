from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from emby_runtime import server_routes
from emby_runtime.server_api_models import (
    EmbyServerDeleteResponse,
    EmbyServerInput,
    EmbyServerMutationResponse,
    EmbyServersResponse,
)


def test_server_routes_publish_input_and_output_contracts():
    routes = [route for route in server_routes.router.routes if isinstance(route, APIRoute)]
    list_routes = [
        route
        for route in routes
        if route.path == "/api/emby/servers" and "GET" in route.methods
    ]
    mutation_routes = [
        route
        for route in routes
        if route.path == "/api/emby/servers" and "POST" in route.methods
    ]
    delete_routes = [
        route
        for route in routes
        if route.path == "/api/emby/servers/{server_id}" and "DELETE" in route.methods
    ]

    assert list_routes[0].responses[200]["model"] is EmbyServersResponse
    assert mutation_routes[0].responses[201]["model"] is EmbyServerMutationResponse
    assert mutation_routes[0].body_field.type_ is EmbyServerInput
    assert delete_routes[0].responses[200]["model"] is EmbyServerDeleteResponse

    app = FastAPI()
    app.include_router(server_routes.router)
    schema = app.openapi()
    create_responses = schema["paths"]["/api/emby/servers"]["post"]["responses"]
    assert set(create_responses) == {"201", "422"}
    assert create_responses["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EmbyServerMutationResponse"


def test_emby_server_input_requires_a_server_url():
    assert EmbyServerInput(url="http://green:8096").url == "http://green:8096"


def test_public_server_payload_does_not_expose_api_key():
    payload = server_routes._public_server_payload({
        "id": "green",
        "alias": "Green",
        "url": "http://green:8096",
        "api_key": "secret-value",
        "enabled": True,
    })

    assert payload["name"] == "Green"
    assert payload["api_key_configured"] is True
    assert "api_key" not in payload


def test_json_server_values_preserve_existing_key_when_password_is_empty():
    values = server_routes._json_server_values(
        {"alias": "Green", "url": "http://green:8096", "enabled": True},
        {"id": "green", "api_key": "existing-key"},
    )

    assert "server_api_key" not in values


def test_json_server_values_can_explicitly_clear_existing_key():
    values = server_routes._json_server_values(
        {"alias": "Green", "url": "http://green:8096", "enabled": True, "clear_api_key": True},
        {"id": "green", "api_key": "existing-key"},
    )

    assert values["server_api_key"] == ""


def test_save_server_values_reuses_existing_server_and_refreshes_identity(monkeypatch):
    existing = {
        "id": "green",
        "alias": "Old Green",
        "url": "http://green:8096",
        "api_key": "existing-key",
        "enabled": True,
    }
    saved = {}
    websocket_updates = []
    published = []

    class _WebSocketManager:
        def get_connection(self, _server_id):
            return None

        def upsert_server(self, server_id, url, api_key):
            websocket_updates.append((server_id, url, api_key))

        def remove_server(self, _server_id):
            raise AssertionError("Un server abilitato non deve essere rimosso")

    monkeypatch.setattr(server_routes, "_load_stored_servers", lambda: [existing])
    monkeypatch.setattr(server_routes, "_fetch_emby_status", lambda _server: {"ok": True, "name": "Green", "server_id": "emby-green"})
    monkeypatch.setattr(server_routes, "_save_emby_settings_to_db", lambda payload: saved.update(payload))
    monkeypatch.setattr(server_routes, "_load_config", lambda: ({}, True))
    monkeypatch.setattr(server_routes, "get_websocket_manager", _WebSocketManager)
    monkeypatch.setattr(server_routes, "publish_configuration_update", published.append)

    server, created = server_routes._save_server_values({
        "server_alias": "Green",
        "server_url": "http://green:8096",
        "server_enabled": "1",
    }, "green")

    assert created is False
    assert server["api_key"] == "existing-key"
    assert server["original_name"] == "Green"
    assert saved["SERVERS"][0]["emby_server_id"] == "emby-green"
    assert websocket_updates == [("green", "http://green:8096", "existing-key")]
    assert published == ["servers"]


def test_save_server_values_stops_websocket_when_server_is_disabled(monkeypatch):
    existing = {
        "id": "green",
        "alias": "Green",
        "url": "http://green:8096",
        "api_key": "existing-key",
        "enabled": True,
    }
    removed = []

    class _WebSocketManager:
        def get_connection(self, server_id):
            return object() if server_id == "green" else None

        def upsert_server(self, *_args):
            raise AssertionError("Un server disabilitato non deve avviare il WebSocket")

        def remove_server(self, server_id):
            removed.append(server_id)

    monkeypatch.setattr(server_routes, "_load_stored_servers", lambda: [existing])
    monkeypatch.setattr(server_routes, "_fetch_emby_status", lambda _server: {"ok": True})
    monkeypatch.setattr(server_routes, "_save_emby_settings_to_db", lambda _payload: None)
    monkeypatch.setattr(server_routes, "_load_config", lambda: ({}, True))
    monkeypatch.setattr(server_routes, "get_websocket_manager", _WebSocketManager)

    server, _created = server_routes._save_server_values(
        {"server_alias": "Green", "server_url": "http://green:8096", "server_enabled": "0"},
        "green",
    )

    assert server["enabled"] is False
    assert removed == ["green"]
