"""Filtered OpenAPI contract for external OctoHubs clients."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from web.api_versioning import versioned_external_api_path
from web.session_auth import has_api_scope, required_api_scope


router = APIRouter(tags=["External API"])

_require_auth: Optional[Callable[[Request], Any]] = None
_HTTP_OPERATIONS = frozenset({"get", "put", "post", "delete", "patch", "head", "options"})
EXTERNAL_API_CONTRACT_VERSION = "1.0"
_STANDARD_EXTERNAL_RESPONSES = {
    "401": {"$ref": "#/components/responses/AuthenticationRequired"},
    "403": {"$ref": "#/components/responses/ScopeDenied"},
}
_GENERIC_JSON_RESPONSE_REF = {"$ref": "#/components/schemas/OctoHubsApiGenericJsonResponse"}


class ExternalOpenApiDocument(BaseModel):
    """Self-describing external contract returned as an OpenAPI JSON document."""

    model_config = ConfigDict(extra="allow")

    openapi: str
    info: dict[str, Any]
    paths: dict[str, Any] = Field(default_factory=dict)
    components: dict[str, Any] = Field(default_factory=dict)


def _operation_kind(required_scope: str) -> str:
    """Describe the intent of an operation without duplicating its route."""
    if required_scope.startswith("read:"):
        return "read"
    if required_scope.startswith("write:"):
        return "write"
    if required_scope == "run:operations":
        return "operation"
    return "administration"


def _external_components(source_components: Mapping[str, Any]) -> dict[str, Any]:
    """Keep FastAPI schemas and add the common external authentication errors."""
    components = deepcopy(dict(source_components))
    components["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API token",
            "description": "Token personale OctoHubs con prefisso ohs_",
        }
    }
    schemas = dict(components.get("schemas") or {})
    schemas["OctoHubsApiError"] = {
        "type": "object",
        "required": ["detail"],
        "properties": {
            "detail": {
                "type": "string",
                "description": "Messaggio sicuro leggibile dal client.",
            }
        },
        "additionalProperties": True,
    }
    schemas["OctoHubsApiGenericJsonResponse"] = {
        "type": "object",
        "description": (
            "Risposta JSON valida ma ancora estensibile. Il relativo endpoint "
            "non ha ancora un modello OpenAPI puntuale per ogni campo."
        ),
        "additionalProperties": True,
    }
    components["schemas"] = schemas
    responses = dict(components.get("responses") or {})
    responses["AuthenticationRequired"] = {
        "description": "Token Bearer mancante, non valido, revocato o appartenente a un account disattivato.",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/OctoHubsApiError"},
                "examples": {
                    "authentication_required": {"value": {"detail": "Authentication required"}}
                },
            }
        },
    }
    responses["ScopeDenied"] = {
        "description": "Il token e valido ma non possiede lo scope richiesto dall'operazione.",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/OctoHubsApiError"},
                "examples": {
                    "scope_denied": {
                        "value": {"detail": "API token senza permesso richiesto: write:configuration"}
                    }
                },
            }
        },
    }
    components["responses"] = responses
    return components


def _external_operation(operation: Mapping[str, Any], required_scope: str) -> dict[str, Any]:
    """Attach the shared external-authentication contract to one FastAPI operation."""
    documented = deepcopy(dict(operation))
    documented["security"] = [{"BearerAuth": []}]
    documented["x-octohubs-required-scope"] = required_scope
    documented["x-octohubs-operation-kind"] = _operation_kind(required_scope)
    documented["x-octohubs-csrf"] = "not-required-with-bearer-token"

    responses = dict(documented.get("responses") or {})
    response_contract = "typed"
    for status_code, response in responses.items():
        if not str(status_code).startswith("2") or not isinstance(response, Mapping):
            continue
        content = dict(response.get("content") or {})
        json_content = content.get("application/json")
        if not isinstance(json_content, Mapping):
            continue
        json_content = dict(json_content)
        if not json_content.get("schema"):
            json_content["schema"] = deepcopy(_GENERIC_JSON_RESPONSE_REF)
            content["application/json"] = json_content
            response = dict(response)
            response["content"] = content
            responses[status_code] = response
            response_contract = "generic"
    for status_code, response in _STANDARD_EXTERNAL_RESPONSES.items():
        responses.setdefault(status_code, deepcopy(response))
    documented["responses"] = responses
    documented["x-octohubs-response-contract"] = response_contract
    explicit_request_contract = documented.get("x-octohubs-request-contract")
    if explicit_request_contract:
        documented["x-octohubs-request-contract"] = explicit_request_contract
    elif documented.get("requestBody"):
        documented["x-octohubs-request-contract"] = "declared"
    elif documented.get("parameters"):
        documented["x-octohubs-request-contract"] = "parameters-only"
    else:
        documented["x-octohubs-request-contract"] = "none-declared"
    return documented


def init_external_api_catalog(require_auth: Callable[[Request], Any]) -> None:
    """Inject the shared UI-or-token authentication dependency."""
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request) -> None:
    if _require_auth is None:
        raise RuntimeError("External API catalog not initialized: require_auth missing")
    _require_auth(request)


def _operation_scope(method: str, path: str) -> str:
    return required_api_scope(method.upper(), path)


def build_external_openapi(
    source_schema: Mapping[str, Any],
    granted_scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Filter FastAPI's real schema to operations permitted to the calling client.

    A browser session receives the full public contract. A Bearer-token client
    receives only operations that its own scopes can actually invoke.
    """
    source_paths = dict(source_schema.get("paths") or {})
    filtered_paths: dict[str, Any] = {}
    token_scopes = list(granted_scopes or [])
    is_token_catalog = granted_scopes is not None

    for path, path_item in source_paths.items():
        versioned_path = versioned_external_api_path(path)
        if versioned_path is None or not isinstance(path_item, Mapping):
            continue
        filtered_operations: dict[str, Any] = {}
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_OPERATIONS or not isinstance(operation, Mapping):
                continue
            required_scope = _operation_scope(method, path)
            if is_token_catalog and not has_api_scope(token_scopes, required_scope):
                continue
            filtered_operations[method] = _external_operation(operation, required_scope)
        if filtered_operations:
            filtered_paths[versioned_path] = filtered_operations

    components = _external_components(dict(source_schema.get("components") or {}))
    source_info = dict(source_schema.get("info") or {})

    return {
        "openapi": str(source_schema.get("openapi") or "3.1.0"),
        "info": {
            "title": "OctoHubs External API",
            "version": EXTERNAL_API_CONTRACT_VERSION,
            "description": (
                "Contratto delle route canoniche utilizzabili da tool esterni. "
                "I percorsi /api/v1 raggiungono gli stessi handler della UI, senza duplicare logica. "
                "Con Authorization: Bearer non e richiesto un token CSRF."
            ),
            "x-octohubs-app-version": str(source_info.get("version") or "current"),
        },
        "x-octohubs-contract-version": EXTERNAL_API_CONTRACT_VERSION,
        "paths": filtered_paths,
        "components": components,
    }


@router.get("/api/external/openapi.json", response_model=ExternalOpenApiDocument)
async def external_openapi_route(request: Request):
    """Return the external API contract filtered to the current token scopes."""
    await run_in_threadpool(_require_auth_dep, request)
    state = getattr(request, "state", None)
    token_scopes = getattr(state, "api_token_scopes", None) if state is not None else None
    schema = build_external_openapi(request.app.openapi(), token_scopes)
    return JSONResponse(
        schema,
        headers={
            "Cache-Control": "no-store",
            "Vary": "Authorization",
            "X-OctoHubs-API-Contract": EXTERNAL_API_CONTRACT_VERSION,
        },
    )
