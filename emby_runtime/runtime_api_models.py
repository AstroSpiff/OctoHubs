"""OpenAPI response contracts for the Emby Live runtime snapshots."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class EmbyRuntimeErrorResponse(BaseModel):
    success: Literal[False]
    message: str


class EmbyTaskStopResponse(BaseModel):
    success: Literal[True]
    message: str | None = None


class EmbyTaskStopRequest(StrictRequestModel):
    server_id: str
    task_id: str


class EmbyLiveStream(BaseModel):
    """A live Emby session, retaining provider-specific metadata."""

    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    server_id: str | None = None
    user: str | None = None
    title: str | None = None
    client: str | None = None
    device: str | None = None
    state: str | None = None


class EmbyStreamsServerSnapshot(BaseModel):
    ok: bool
    streams: list[EmbyLiveStream] = Field(default_factory=list)
    error: str | None = None


class EmbyStreamsSnapshotResponse(BaseModel):
    success: Literal[True]
    servers: dict[str, EmbyStreamsServerSnapshot]


class EmbyProbeLibrariesServerSnapshot(BaseModel):
    """Libraries returned by Emby, with forward-compatible metadata."""

    model_config = ConfigDict(extra="allow")

    ok: bool
    libraries: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class EmbyProbeLibrariesResponse(BaseModel):
    success: Literal[True]
    servers: dict[str, EmbyProbeLibrariesServerSnapshot]


class EmbyServerStatusResponse(BaseModel):
    """Live status for one configured Emby server."""

    success: Literal[True]
    status: dict[str, Any]
    running_tasks: list[dict[str, Any]] = Field(default_factory=list)
    tasks_error: str | None = None
    streams: list[EmbyLiveStream] = Field(default_factory=list)
    streams_error: str | None = None


class EmbyStatusServerMeta(BaseModel):
    """Safe configuration metadata included in the Emby Live fallback snapshot."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    enabled: bool
    icon: str
    icon_color: str
    icon_style: str
    url: str | None = None
    last_action: dict[str, str] | None = None


class EmbyStatusSnapshotServer(BaseModel):
    """One server entry from the HTTP fallback of the Emby Live feed."""

    model_config = ConfigDict(extra="allow")

    server: EmbyStatusServerMeta
    status: dict[str, Any] = Field(default_factory=dict)
    running_tasks: list[dict[str, Any]] = Field(default_factory=list)
    tasks_error: str | None = None
    streams: list[EmbyLiveStream] = Field(default_factory=list)
    streams_error: str | None = None
    probe_status: dict[str, Any] | None = None


class EmbyStatusSnapshotResponse(BaseModel):
    """Complete HTTP snapshot used when an external client cannot use SSE."""

    success: Literal[True]
    servers: dict[str, EmbyStatusSnapshotServer] = Field(default_factory=dict)
