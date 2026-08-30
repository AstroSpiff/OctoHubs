"""OpenAPI contracts for direct Emby maintenance actions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class EmbyActionApiModel(BaseModel):
    """Preserve forward-compatible action payloads without hiding core fields."""

    model_config = ConfigDict(extra="allow")


class EmbyActionDefinition(EmbyActionApiModel):
    id: Literal["refresh_libraries", "refresh_metadata"]
    label: str


class EmbyActionTarget(EmbyActionApiModel):
    id: str
    name: str
    url: str = ""
    icon: str = "fa-server"
    icon_style: str = "solid"
    icon_color: str = "#3b82f6"


class EmbyActionTargetsResponse(EmbyActionApiModel):
    success: Literal[True]
    actions: list[EmbyActionDefinition] = Field(default_factory=list)
    servers: list[EmbyActionTarget] = Field(default_factory=list)


class EmbyActionRequest(StrictRequestModel):
    action: Literal["restart_server", "refresh_libraries", "refresh_metadata"]
    server_id: str = ""


class EmbyActionServerResult(EmbyActionApiModel):
    server_id: str
    server_name: str
    success: bool
    message: str


class EmbyActionResponse(EmbyActionApiModel):
    success: bool
    partial: bool = False
    message: str
    results: list[EmbyActionServerResult] = Field(default_factory=list)


def request_body_schema(model: type[BaseModel]) -> dict:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
