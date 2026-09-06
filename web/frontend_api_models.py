"""Stable request and response contracts for the private React UI API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrontendApiModel(BaseModel):
    """Allow compatible response extensions while documenting known fields."""

    model_config = ConfigDict(extra="allow")


class FrontendUser(FrontendApiModel):
    id: int | None
    username: str
    email: str = ""
    role: Literal["admin", "user", "viewer"]


class NavigationPreferences(FrontendApiModel):
    primary_navigation: Literal["top", "sidebar"] = "top"
    secondary_navigation: Literal["tabs", "sidebar"] = "tabs"


class FrontendSessionResponse(FrontendApiModel):
    ok: Literal[True]
    user: FrontendUser
    preferences: NavigationPreferences
    csrf_token: str


class FrontendPreferencesRequest(BaseModel):
    """Partial preference update; at least one field is enforced by the route."""

    model_config = ConfigDict(extra="ignore", json_schema_extra=lambda schema: _preferences_patch_schema(schema))

    primary_navigation: Literal["top", "sidebar"] | None = None
    secondary_navigation: Literal["tabs", "sidebar"] | None = None

    @model_validator(mode="after")
    def validate_non_empty_non_null_patch(self):
        supplied = self.model_fields_set & {
            "primary_navigation",
            "secondary_navigation",
        }
        if not supplied or any(getattr(self, field) is None for field in supplied):
            raise ValueError("At least one non-null navigation preference is required")
        return self


class FrontendPreferencesResponse(FrontendApiModel):
    success: Literal[True]
    preferences: NavigationPreferences


class FrontendTabOrderQuery(BaseModel):
    page: str = Field(min_length=1, max_length=80)


class FrontendTabOrderEntry(FrontendApiModel):
    tab_key: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=0)


class FrontendTabOrderRequestEntry(FrontendApiModel):
    """Tolerant input entry; position is accepted but canonicalized by the server."""

    tab_key: Any = None
    position: Any = None


class FrontendTabOrderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: str = Field(min_length=1, max_length=80)
    order: list[FrontendTabOrderRequestEntry]


class FrontendTabOrderResponse(FrontendApiModel):
    success: Literal[True]
    order: list[FrontendTabOrderEntry] = Field(default_factory=list)


def _preferences_patch_schema(schema: dict[str, Any]) -> None:
    """Express omitted-or-non-null patch fields exactly in JSON Schema."""

    for name in ("primary_navigation", "secondary_navigation"):
        property_schema = schema["properties"][name]
        variants = property_schema.pop("anyOf", None)
        if variants:
            non_null = [variant for variant in variants if variant.get("type") != "null"]
            if len(non_null) == 1:
                property_schema.update(non_null[0])
            else:
                property_schema["anyOf"] = non_null
        property_schema.pop("default", None)
    schema["anyOf"] = [
        {"required": ["primary_navigation"]},
        {"required": ["secondary_navigation"]},
    ]


def request_body_contract(model: type[BaseModel]) -> dict[str, object]:
    """Build an OpenAPI request body without changing legacy validation errors."""

    schema = model.model_json_schema()
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _inline_local_refs(schema)}},
        }
    }


def query_contract(model: type[BaseModel]) -> dict[str, object]:
    """Build OpenAPI query parameters from a small Pydantic query model."""

    schema = model.model_json_schema()
    required = set(schema.get("required", []))
    return {
        "parameters": [
            {
                "name": name,
                "in": "query",
                "required": name in required,
                "schema": property_schema,
            }
            for name, property_schema in schema.get("properties", {}).items()
        ]
    }


def _inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic-local ``$defs`` before embedding a schema in OpenAPI.

    A ``#/$defs/...`` reference is relative to the complete OpenAPI document once
    embedded through ``openapi_extra``. OpenAPI has no root ``$defs``, so leaving
    those references intact produces an invalid contract.
    """

    definitions = schema.get("$defs", {})

    def visit(value: Any, resolving: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [visit(item, resolving) for item in value]
        if not isinstance(value, dict):
            return value

        reference = value.get("$ref")
        prefix = "#/$defs/"
        if isinstance(reference, str) and reference.startswith(prefix):
            name = reference.removeprefix(prefix)
            if name in resolving or name not in definitions:
                raise ValueError(f"Unresolvable local schema reference: {reference}")
            resolved = visit(definitions[name], resolving | {name})
            siblings = {
                key: visit(item, resolving)
                for key, item in value.items()
                if key != "$ref"
            }
            return {**resolved, **siblings}

        return {
            key: visit(item, resolving)
            for key, item in value.items()
            if key != "$defs"
        }

    return visit(schema)
