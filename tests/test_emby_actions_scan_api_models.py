"""OpenAPI coverage for Emby actions and library scan control routes."""

from __future__ import annotations

from fastapi import FastAPI

from emby_actions.routes import router as actions_router
from emby_libraries.routes import router as libraries_router


def _json_schema(operation: dict) -> dict:
    return operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_emby_action_routes_publish_typed_targets_and_execution_contracts():
    app = FastAPI()
    app.include_router(actions_router)
    schema = app.openapi()

    targets = schema["paths"]["/api/emby/actions/targets"]["get"]
    action = schema["paths"]["/api/emby/actions"]["post"]

    assert _json_schema(targets)["$ref"] == "#/components/schemas/EmbyActionTargetsResponse"
    assert _json_schema(action)["$ref"] == "#/components/schemas/EmbyActionResponse"
    assert set(action["requestBody"]["content"]["application/json"]["schema"]["properties"]) >= {
        "action",
        "server_id",
    }


def test_library_scan_routes_publish_typed_reads_and_mutation_bodies():
    app = FastAPI()
    app.include_router(libraries_router)
    schema = app.openapi()
    paths = schema["paths"]

    assert _json_schema(paths["/api/emby/active-library-scans"]["get"])["$ref"] == (
        "#/components/schemas/ActiveLibraryScansResponse"
    )
    assert _json_schema(paths["/api/emby/active-scan-jobs"]["get"])["$ref"] == (
        "#/components/schemas/ActiveScanJobsResponse"
    )
    assert _json_schema(paths["/api/emby/active-scans"]["get"])["$ref"] == (
        "#/components/schemas/ActiveEmbyScansResponse"
    )
    assert _json_schema(paths["/api/emby/scan-jobs"]["get"])["$ref"] == (
        "#/components/schemas/ScanJobsResponse"
    )

    tracked = paths["/api/emby/scan-library-tracked"]["post"]
    grouped = paths["/api/emby/scan-group-tracked"]["post"]
    reset = paths["/api/emby/scan-jobs/reset"]["post"]

    assert "library_ids" in tracked["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "libraries" in grouped["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert _json_schema(reset)["$ref"] == "#/components/schemas/LibraryScanResetResponse"


def test_library_configuration_routes_publish_grouping_and_order_contracts():
    app = FastAPI()
    app.include_router(libraries_router)
    schema = app.openapi()
    paths = schema["paths"]

    assert _json_schema(paths["/api/emby/grouped-libraries"]["get"])["$ref"] == (
        "#/components/schemas/GroupedLibrariesResponse"
    )
    assert _json_schema(paths["/api/emby/associations"]["get"])["$ref"] == (
        "#/components/schemas/LibraryAssociationsResponse"
    )
    assert _json_schema(paths["/api/emby/group-order"]["get"])["$ref"] == (
        "#/components/schemas/LibraryGroupOrderResponse"
    )

    associations = paths["/api/emby/associations"]["post"]
    servers = paths["/api/emby/server-order"]["post"]
    groups = paths["/api/emby/group-order"]["post"]

    assert associations["requestBody"]["content"]["application/json"]["schema"]["type"] == "array"
    assert servers["requestBody"]["content"]["application/json"]["schema"]["type"] == "array"
    assert groups["requestBody"]["content"]["application/json"]["schema"]["type"] == "array"


def test_emby_media_lookup_routes_publish_typed_payloads_and_query_contracts():
    app = FastAPI()
    app.include_router(libraries_router)
    schema = app.openapi()
    paths = schema["paths"]

    assert _json_schema(paths["/api/emby/movie-versions"]["get"])["$ref"] == (
        "#/components/schemas/MovieVersionsResponse"
    )
    assert _json_schema(paths["/api/emby/series-seasons"]["get"])["$ref"] == (
        "#/components/schemas/SeriesSeasonsResponse"
    )
    assert _json_schema(paths["/api/emby/season-episodes"]["get"])["$ref"] == (
        "#/components/schemas/SeasonEpisodesResponse"
    )
    assert _json_schema(paths["/api/emby/lookup"]["get"])["$ref"] == (
        "#/components/schemas/EmbyLookupResponse"
    )
    assert _json_schema(paths["/api/emby/item-details"]["get"])["$ref"] == (
        "#/components/schemas/ItemDetailsResponse"
    )
    assert _json_schema(paths["/api/emby/availability"]["post"])["$ref"] == (
        "#/components/schemas/EmbyAvailabilityResponse"
    )

    versions = paths["/api/emby/movie-versions"]["get"]
    availability = paths["/api/emby/availability"]["post"]

    assert {item["name"] for item in versions["parameters"]} == {"server_id", "tmdb_id"}
    assert set(availability["requestBody"]["content"]["application/json"]["schema"]["properties"]) >= {
        "tmdb_id",
        "media_type",
    }
