"""External OpenAPI contract tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _source_schema():
    return {
        "openapi": "3.1.0",
        "info": {"title": "Internal schema", "version": "test"},
        "paths": {
            "/api/system/status": {"get": {"summary": "Status"}},
            "/api/telegram/action": {"post": {"summary": "Telegram"}},
            "/api/emby/servers": {"get": {"summary": "Servers"}},
            "/api/emby/event-bridge/events": {"post": {"summary": "Plugin hook"}},
            "/api/emby/events-stream": {"get": {"summary": "Browser feed"}},
            "/api/emby/status-stream": {"get": {"summary": "Emby live feed"}},
            "/api/emby/transcode-guard/player-event": {"post": {"summary": "Guard plugin hook"}},
            "/api/workflow/events": {"get": {"summary": "Workflow feed"}},
            "/api/account/me": {"get": {"summary": "Account"}},
            "/api/search/manual": {"post": {"summary": "Retired"}},
            "/login": {"get": {"summary": "Login"}},
        },
        "components": {
            "schemas": {
                "Server": {"type": "object", "properties": {"id": {"type": "string"}}},
            }
        },
    }


def test_external_openapi_exposes_only_canonical_control_routes():
    from web.external_api_catalog import build_external_openapi

    schema = build_external_openapi(_source_schema())

    assert schema["info"]["title"] == "OctoHubs External API"
    assert set(schema["paths"]) == {
        "/api/v1/system/status",
        "/api/v1/telegram/action",
        "/api/v1/emby/servers",
        "/api/v1/account/me",
    }
    assert schema["paths"]["/api/v1/system/status"]["get"]["x-octohubs-required-scope"] == "read:status"
    assert schema["paths"]["/api/v1/telegram/action"]["post"]["x-octohubs-required-scope"] == "write:configuration"
    assert schema["paths"]["/api/v1/account/me"]["get"]["x-octohubs-required-scope"] == "read:account"
    assert schema["paths"]["/api/v1/system/status"]["get"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/api/v1/system/status"]["get"]["x-octohubs-operation-kind"] == "read"
    assert schema["paths"]["/api/v1/telegram/action"]["post"]["x-octohubs-operation-kind"] == "write"
    assert schema["paths"]["/api/v1/system/status"]["get"]["x-octohubs-csrf"] == "not-required-with-bearer-token"
    assert schema["paths"]["/api/v1/system/status"]["get"]["responses"]["401"] == {
        "$ref": "#/components/responses/AuthenticationRequired"
    }
    assert schema["paths"]["/api/v1/telegram/action"]["post"]["responses"]["403"] == {
        "$ref": "#/components/responses/ScopeDenied"
    }
    assert schema["components"]["schemas"]["Server"]["type"] == "object"
    assert "OctoHubsApiError" in schema["components"]["schemas"]
    assert "AuthenticationRequired" in schema["components"]["responses"]
    assert "BearerAuth" in schema["components"]["securitySchemes"]
    assert schema["info"]["version"] == "1.0"
    assert schema["x-octohubs-contract-version"] == "1.0"
    assert "/api/v1/emby/event-bridge/events" not in schema["paths"]
    assert "/api/v1/emby/events-stream" not in schema["paths"]
    assert "/api/v1/emby/status-stream" not in schema["paths"]
    assert "/api/v1/emby/transcode-guard/player-event" not in schema["paths"]
    assert "/api/v1/workflow/events" not in schema["paths"]


def test_external_openapi_filters_operations_to_the_calling_token_scopes():
    from web.external_api_catalog import build_external_openapi

    schema = build_external_openapi(_source_schema(), ["read:status"])

    assert set(schema["paths"]) == {"/api/v1/system/status"}

    configuration_schema = build_external_openapi(_source_schema(), ["write:configuration"])
    assert set(configuration_schema["paths"]) == {
        "/api/v1/telegram/action",
        "/api/v1/emby/servers",
    }


def test_external_openapi_document_has_a_declared_response_model():
    from fastapi import FastAPI
    from web.external_api_catalog import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()

    response = schema["paths"]["/api/external/openapi.json"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/ExternalOpenApiDocument"


@pytest.mark.anyio
async def test_external_openapi_route_uses_shared_auth_and_token_scope_filter():
    from web import external_api_catalog

    authenticated = []
    external_api_catalog.init_external_api_catalog(lambda request: authenticated.append(request))
    request = SimpleNamespace(
        state=SimpleNamespace(api_token_scopes=["read:status"]),
        app=SimpleNamespace(openapi=_source_schema),
    )

    response = await external_api_catalog.external_openapi_route(request)
    payload = json.loads(response.body.decode("utf-8"))

    assert authenticated == [request]
    assert set(payload["paths"]) == {"/api/v1/system/status"}
    assert response.headers["X-OctoHubs-API-Contract"] == "1.0"
    assert response.headers["Vary"] == "Authorization"
