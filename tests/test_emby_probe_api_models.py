"""OpenAPI regression coverage for the Media Probe public contract."""

from __future__ import annotations

from fastapi import FastAPI

from emby_probe.routes import router


def _response_schema(operation: dict) -> dict:
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def _parameter_names(operation: dict) -> set[str]:
    return {parameter["name"] for parameter in operation.get("parameters", [])}


def test_probe_configuration_and_stored_state_publish_typed_contracts():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    config_get = paths["/api/emby/probe/config"]["get"]
    config_save = paths["/api/emby/probe/config"]["post"]
    queue = paths["/api/emby/probe/queue"]["get"]
    history = paths["/api/emby/probe/history"]["get"]
    blacklist = paths["/api/emby/probe/blacklist"]["get"]

    assert _response_schema(config_get)["$ref"] == "#/components/schemas/ProbeConfigResponse"
    assert _parameter_names(config_get) == {"server_id"}
    assert "config" in config_save["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert _response_schema(queue)["$ref"] == "#/components/schemas/ProbeQueueResponse"
    assert _response_schema(history)["$ref"] == "#/components/schemas/ProbeHistoryResponse"
    assert _response_schema(blacklist)["$ref"] == "#/components/schemas/ProbeBlacklistResponse"
    assert _parameter_names(history) == {"server_id", "limit", "scope"}


def test_probe_commands_and_queue_mutations_publish_bodies_and_operation_result():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    discovery = paths["/api/emby/probe/discovery/start"]["post"]
    workflow = paths["/api/emby/probe/recent/combo/start"]["post"]
    retry = paths["/api/emby/probe/retry"]["post"]
    delete_queue = paths["/api/emby/probe/queue"]["delete"]
    stop_all = paths["/api/emby/probe/recent/combo/stop-all"]["post"]

    assert _response_schema(discovery)["$ref"] == "#/components/schemas/ProbeActionResponse"
    assert {"server_id", "libraries"} <= set(
        discovery["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"server_id", "mode"} <= set(
        workflow["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"server_id", "item_id", "scope"} <= set(
        retry["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"server_id", "item_id", "media_source_id"} <= set(
        delete_queue["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert "requestBody" not in stop_all


def test_probe_debug_endpoint_publishes_its_required_server_and_item_shape():
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"]["/api/emby/probe/debug-recent-items"]["get"]

    assert _response_schema(operation)["$ref"] == "#/components/schemas/ProbeDebugRecentResponse"
    assert _parameter_names(operation) == {"server_id", "limit"}
