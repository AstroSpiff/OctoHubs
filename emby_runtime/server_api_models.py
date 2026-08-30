"""OpenAPI input and output contracts for Emby server configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmbyServerInput(BaseModel):
    """Writable Emby server settings; an empty API key never overwrites one."""

    alias: str = ""
    url: str = Field(min_length=1)
    api_key: str | None = None
    clear_api_key: bool = False
    enabled: bool = True
    notes: str = ""
    icon: str = "fa-server"
    icon_color: str = "#3b82f6"
    icon_style: str = "solid"


class EmbyServerResponse(BaseModel):
    """Safe Emby server data returned to browser and external clients."""

    id: str
    name: str
    original_name: str
    alias: str
    url: str
    enabled: bool
    notes: str
    icon: str
    icon_color: str
    icon_style: str
    api_key_configured: bool


class EmbyServersResponse(BaseModel):
    """List response for configured Emby servers."""

    success: bool
    servers: list[EmbyServerResponse]


class EmbyServerMutationResponse(BaseModel):
    """Successful create or update response for one Emby server."""

    success: bool
    message: str
    server: EmbyServerResponse


class EmbyServerDeleteResponse(BaseModel):
    """Successful deletion response, including any non-blocking cleanup issue."""

    success: bool
    message: str
    cleanup_error: str | None = None
