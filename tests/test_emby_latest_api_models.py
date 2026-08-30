"""OpenAPI regression coverage for Latest Publications endpoints."""

from __future__ import annotations

from fastapi import FastAPI

from emby_latest.routes import router


def _response_schema(operation: dict, code: str = "200") -> dict:
    return operation["responses"][code]["content"]["application/json"]["schema"]


def _parameter_names(operation: dict) -> set[str]:
    return {parameter["name"] for parameter in operation.get("parameters", [])}


def test_latest_read_models_and_query_parameters_are_published():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    snapshot = paths["/api/emby/latest"]["get"]
    refresh = paths["/api/emby/latest/refresh"]["post"]
    progress = paths["/api/emby/latest/progress"]["get"]
    configuration = paths["/api/emby/latest/config"]["get"]

    assert _response_schema(snapshot)["$ref"] == "#/components/schemas/LatestSnapshotResponse"
    assert _parameter_names(snapshot) == {"limit", "per_server_limit", "cache_only", "view"}
    assert _response_schema(refresh, "202")["$ref"] == "#/components/schemas/LatestRefreshResponse"
    assert _parameter_names(refresh) == {"limit", "per_server_limit", "full"}
    assert _response_schema(progress)["$ref"] == "#/components/schemas/LatestProgressResponse"
    assert _response_schema(configuration)["$ref"] == "#/components/schemas/LatestConfigurationResponse"


def test_latest_configuration_and_actions_publish_typed_bodies():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    preset = paths["/api/emby/latest/presets"]["post"]
    rule = paths["/api/emby/latest/rules"]["post"]
    rule_enabled = paths["/api/emby/latest/rules/{rule_id}/enabled"]["post"]
    preview = paths["/api/emby/latest/preview"]["post"]
    enrich = paths["/api/emby/latest/enrich"]["post"]
    notify = paths["/api/emby/latest/notify"]["post"]

    assert _response_schema(preset)["$ref"] == "#/components/schemas/LatestConfigurationResponse"
    assert {"name", "template"} <= set(
        preset["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"name", "server_ids", "preset_id", "telegram_config_id"} <= set(
        rule["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert "enabled" in rule_enabled["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert {"template", "payload", "items"} <= set(
        preview["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"item", "force_omdb"} <= set(
        enrich["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
    assert {"per_server_limit", "server_filter", "server_id"} <= set(
        notify["requestBody"]["content"]["application/json"]["schema"]["properties"]
    )
