"""Small reusable OpenAPI fragments for explicit external API inputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def json_request_body(model: type[BaseModel], *, required: bool = True) -> dict[str, Any]:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": required,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


def query_parameters(*items: tuple[str, bool, str]) -> dict[str, Any]:
    """Publish Request-based query parameters without changing their parser."""
    return {
        "parameters": [
            {
                "name": name,
                "in": "query",
                "required": required,
                "schema": {"type": value_type},
            }
            for name, required, value_type in items
        ]
    }


def no_request_body() -> dict[str, str]:
    """Mark an action as intentionally bodyless instead of merely undocumented."""
    return {"x-octohubs-request-contract": "none-intentional"}
