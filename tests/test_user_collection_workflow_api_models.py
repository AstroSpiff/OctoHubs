"""OpenAPI contract coverage for the remaining operational domains."""

from __future__ import annotations

from fastapi import FastAPI

from emby_collections.routes import router as collections_router
from emby_libraries.routes import router as libraries_router
from emby_probe.routes import router as probe_router
from emby_users.icon_routes import router as icons_router
from emby_users.routes import router as users_router
from services.workflow_routes import router as workflow_router


def _response_ref(schema: dict, path: str, method: str, status: str = "200") -> str:
    return schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def test_users_and_icons_publish_external_response_contracts():
    app = FastAPI()
    app.include_router(users_router)
    app.include_router(icons_router)
    schema = app.openapi()

    assert _response_ref(schema, "/api/emby/users/list", "get") == "#/components/schemas/EmbyUsersDashboardResponse"
    assert _response_ref(schema, "/api/emby/users/operations", "get") == "#/components/schemas/OperationsSnapshotResponse"
    assert _response_ref(schema, "/api/emby/users/check", "post") == "#/components/schemas/UserExistsResponse"
    assert _response_ref(schema, "/api/emby/icons/config", "get") == "#/components/schemas/UserIconConfigResponse"


def test_collection_and_workflow_routes_publish_external_response_contracts():
    app = FastAPI()
    app.include_router(collections_router)
    app.include_router(workflow_router)
    schema = app.openapi()

    assert _response_ref(schema, "/api/emby/collections", "get") == "#/components/schemas/CollectionsListResponse"
    assert _response_ref(schema, "/api/emby/collections/options", "get") == "#/components/schemas/CollectionsOptionsResponse"
    assert _response_ref(schema, "/api/emby/collections/{collection_id}/sync", "post", "202") == "#/components/schemas/CollectionBackgroundOperationResponse"
    assert _response_ref(schema, "/api/workflow/start", "post") == "#/components/schemas/WorkflowSuccessResponse"
    stop = schema["paths"]["/api/workflow/stop"]["post"]
    assert stop["requestBody"]["required"] is True
    assert stop["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/WorkflowStopRequest"
    assert _response_ref(schema, "/api/workflow/stop", "post", "409") == "#/components/schemas/WorkflowErrorResponse"


def test_external_binary_routes_publish_their_real_media_types():
    app = FastAPI()
    app.include_router(collections_router)
    app.include_router(icons_router)
    app.include_router(libraries_router)
    app.include_router(probe_router)
    schema = app.openapi()

    assert set(schema["paths"]["/api/emby/collections/{collection_id}/poster"]["get"]["responses"]["200"]["content"]) == {"image/*"}
    assert set(schema["paths"]["/api/emby/collections/{collection_id}/backdrop"]["get"]["responses"]["200"]["content"]) == {"image/*"}
    assert set(schema["paths"]["/api/emby/icons/image/{profile_id}/{column_key}"]["get"]["responses"]["200"]["content"]) == {"image/*"}
    assert set(schema["paths"]["/api/emby/image"]["get"]["responses"]["200"]["content"]) == {"image/*"}
    assert set(schema["paths"]["/api/emby/probe/export-csv"]["get"]["responses"]["200"]["content"]) == {"text/csv"}
    assert {parameter["name"] for parameter in schema["paths"]["/api/emby/image"]["get"]["parameters"]} >= {"server_id", "item_id"}
