"""OpenAPI coverage for Configuration and Event Bridge control routes."""

from __future__ import annotations

from fastapi import FastAPI

from web.configuration_api_routes import router as configuration_router
from web.event_bridge_api_routes import router as event_bridge_router


def test_configuration_routes_publish_typed_snapshots_and_request_bodies():
    app = FastAPI()
    app.include_router(configuration_router)
    schema = app.openapi()

    settings = schema["paths"]["/api/configuration/settings"]["get"]["responses"]["200"]
    automations = schema["paths"]["/api/configuration/automations"]["put"]
    services = schema["paths"]["/api/configuration/services"]["put"]

    assert settings["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/ConfigurationSettingsResponse"
    assert automations["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ConfigurationAutomationsPayload"
    )
    assert "tasks" in schema["components"]["schemas"]["ConfigurationAutomationsPayload"]["properties"]
    assert services["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ConfigurationServicesUpdateRequest"
    )
    services_input = schema["components"]["schemas"]["ConfigurationServicesUpdateRequest"]
    assert "database" not in services_input["properties"]
    assert services_input["additionalProperties"] is False
    assert "422" in services["responses"]


def test_event_bridge_routes_publish_typed_status_and_request_bodies():
    app = FastAPI()
    app.include_router(event_bridge_router)
    schema = app.openapi()

    status = schema["paths"]["/api/event-bridge/status"]["get"]["responses"]["200"]
    settings = schema["paths"]["/api/event-bridge/settings"]["put"]
    secret = schema["paths"]["/api/event-bridge/webhook-secret"]["put"]
    credential = schema["paths"]["/api/event-bridge/servers/{server_id}/credential"]["post"]

    assert status["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EventBridgeStatusResponse"
    assert "servers" in settings["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "requestBody" not in secret
    assert "requestBody" not in credential
    assert credential["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/EventBridgeCredentialProvisionResponse"
    )
