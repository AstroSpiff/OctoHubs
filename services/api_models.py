"""OpenAPI contracts for service checks and Trakt device authorization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class ServiceApiModel(BaseModel):
    """Stable public service fields, without returning saved credentials."""

    model_config = ConfigDict(extra="allow")


class ConnectionStatus(ServiceApiModel):
    ok: bool
    message: str
    configured: bool | None = None


class ConnectionCheckResponse(ServiceApiModel):
    success: Literal[True]
    statuses: dict[str, ConnectionStatus] = Field(default_factory=dict)


class TraktDeviceStartRequest(StrictRequestModel):
    client_id: str


class TraktDeviceStartResponse(ServiceApiModel):
    success: Literal[True]
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class TraktDevicePollRequest(StrictRequestModel):
    client_id: str | None = None
    client_secret: str | None = None
    device_code: str


class TraktDevicePollResponse(ServiceApiModel):
    success: bool | None = None
    status: Literal["pending", "authorized"] | None = None
    expires_at: str | None = None
    message: str | None = None


class TraktClearResponse(ServiceApiModel):
    success: bool
    message: str


def request_body_schema(model: type[BaseModel]) -> dict[str, object]:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
