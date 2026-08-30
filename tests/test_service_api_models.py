"""OpenAPI regression coverage for Telegram and service integration routes."""

from __future__ import annotations

from fastapi import FastAPI

from services.routes import router as service_router
from telegram.api_routes import router as telegram_router


def _response_schema(operation: dict) -> dict:
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_service_checks_and_trakt_device_flow_publish_typed_contracts():
    app = FastAPI()
    app.include_router(service_router)
    paths = app.openapi()["paths"]

    connections = paths["/api/test-connections"]["post"]
    start = paths["/api/trakt/device/start"]["post"]
    poll = paths["/api/trakt/device/poll"]["post"]
    clear = paths["/api/trakt/clear"]["post"]

    assert _response_schema(connections)["$ref"] == "#/components/schemas/ConnectionCheckResponse"
    assert _response_schema(start)["$ref"] == "#/components/schemas/TraktDeviceStartResponse"
    assert _response_schema(poll)["$ref"] == "#/components/schemas/TraktDevicePollResponse"
    assert _response_schema(clear)["$ref"] == "#/components/schemas/TraktClearResponse"
    assert "client_id" in start["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert {"client_secret", "device_code"} <= set(
        poll["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )


def test_telegram_snapshot_and_action_publish_typed_contracts():
    app = FastAPI()
    app.include_router(telegram_router)
    paths = app.openapi()["paths"]

    settings = paths["/api/telegram/settings"]["get"]
    action = paths["/api/telegram/action"]["post"]

    assert _response_schema(settings)["$ref"] == "#/components/schemas/TelegramSettingsResponse"
    assert _response_schema(action)["$ref"] == "#/components/schemas/TelegramSettingsResponse"
    schema = action["requestBody"]["content"]["application/json"]["schema"]
    assert {"action", "data"} <= set(schema["properties"])
