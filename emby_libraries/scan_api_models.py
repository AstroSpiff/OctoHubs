"""OpenAPI contracts for Emby library scan and tracking routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from core.emby_identifiers import OpaqueEmbyIdentifier, OpaqueEmbyServerIdentifier
from emby_libraries.scan_limits import (
    MAX_SCAN_LIBRARIES_PER_REQUEST,
    MAX_SCAN_LIBRARIES_PER_SERVER,
    normalize_group_libraries,
    normalize_library_ids,
)
from web.request_validation import StrictRequestModel


class LibraryScanApiModel(BaseModel):
    """Keep tracker metadata extensible while documenting the stable control data."""

    model_config = ConfigDict(extra="allow")


class ScanLibraryState(LibraryScanApiModel):
    job_id: str | None = None
    server_id: str | None = None
    library_id: str
    scan_type: Literal["content", "metadata"] | None = None
    status: str
    progress: float = 0.0
    message: str = ""
    updated_at: str
    queue_position: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanGroupSession(LibraryScanApiModel):
    job_id: str | None = None
    group_name: str
    scan_type: Literal["content", "metadata"] | None = None
    status: str
    server_id: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    updated_at: str
    progress: float = 0.0


class ActiveLibraryScansResponse(LibraryScanApiModel):
    success: Literal[True]
    scans: list[ScanLibraryState] = Field(default_factory=list)
    sessions: list[ScanGroupSession] = Field(default_factory=list)
    now: str


class ScanJob(LibraryScanApiModel):
    id: str
    server_id: str | None = None
    library_ids: list[str] = Field(default_factory=list)
    status: str
    group_name: str | None = None
    scan_type: Literal["content", "metadata"] | None = None
    progress: float | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class ScanJobResponse(LibraryScanApiModel):
    success: Literal[True]
    job: ScanJob


class ScanJobsResponse(LibraryScanApiModel):
    success: Literal[True]
    jobs: list[ScanJob] = Field(default_factory=list)


class ActiveScanJob(LibraryScanApiModel):
    job_id: str
    server_id: str
    library_ids: list[str] = Field(default_factory=list)
    group_name: str | None = None
    scan_type: Literal["content", "metadata"] = "content"
    status: str
    progress: float = 0.0
    started_at: str
    updated_at: str


class ActiveScanJobsResponse(LibraryScanApiModel):
    success: Literal[True]
    jobs: list[ActiveScanJob] = Field(default_factory=list)
    count: int


class EmbyScheduledScan(LibraryScanApiModel):
    server_id: str
    server_name: str
    task_name: str
    progress: float = 0.0
    task_id: str = ""


class ActiveEmbyScansResponse(LibraryScanApiModel):
    success: Literal[True]
    active_scans: list[EmbyScheduledScan] = Field(default_factory=list)


class ScanLibraryRequest(StrictRequestModel):
    server_id: OpaqueEmbyServerIdentifier
    library_id: OpaqueEmbyIdentifier


class TrackedScanLibraryRequest(StrictRequestModel):
    server_id: OpaqueEmbyServerIdentifier
    library_ids: list[OpaqueEmbyIdentifier] = Field(
        min_length=1,
        max_length=MAX_SCAN_LIBRARIES_PER_SERVER,
    )
    group_name: str | None = None
    scan_type: Literal["content", "metadata"] = "content"

    @field_validator("library_ids")
    @classmethod
    def deduplicate_library_ids(cls, values: list[str]) -> list[str]:
        return normalize_library_ids(values)


class GroupScanLibrary(StrictRequestModel):
    server_id: OpaqueEmbyServerIdentifier
    library_id: OpaqueEmbyIdentifier


class TrackedGroupScanRequest(StrictRequestModel):
    group_name: str
    libraries: list[GroupScanLibrary] = Field(
        min_length=1,
        max_length=MAX_SCAN_LIBRARIES_PER_REQUEST,
    )
    scan_type: Literal["content", "metadata"] = "content"

    @model_validator(mode="after")
    def enforce_scan_quotas(self) -> "TrackedGroupScanRequest":
        normalized = normalize_group_libraries(
            [entry.model_dump() for entry in self.libraries]
        )
        self.libraries = [GroupScanLibrary.model_validate(entry) for entry in normalized]
        return self


class LibraryScanActionResponse(LibraryScanApiModel):
    success: bool
    message: str
    queued: bool | None = None
    queue_position: int | None = None
    job_id: str | None = None
    job_ids: list[str] | None = None
    group_name: str | None = None
    scan_type: Literal["content", "metadata"] | None = None
    failed_servers: list[str] | None = None


class LibraryScanResetResponse(LibraryScanApiModel):
    success: bool
    message: str


class LibraryEntry(LibraryScanApiModel):
    server_id: str
    server_name: str | None = None
    server_alias: str | None = None
    server_icon: str | None = None
    server_icon_style: str | None = None
    server_icon_color: str | None = None
    collection_type: str | None = None
    library_id: str | None = None
    id: str | None = None
    library_name: str | None = None


class LibraryGroup(LibraryScanApiModel):
    group_name: str
    collection_type: str
    servers: list[str] = Field(default_factory=list)
    libraries: list[LibraryEntry] = Field(default_factory=list)


class GroupedLibrariesResponse(LibraryScanApiModel):
    success: Literal[True]
    groups: list[LibraryGroup] = Field(default_factory=list)


class LibraryAssociation(StrictRequestModel):
    server_id: str
    library_id: str
    group_name: str


class LibraryAssociationsRequest(RootModel[list[LibraryAssociation]]):
    pass


class LibraryAssociationsResponse(LibraryScanApiModel):
    success: bool
    associations: list[LibraryAssociation] = Field(default_factory=list)


class LibraryGroupOrderEntry(StrictRequestModel):
    collection_type: str
    group_name: str
    position: int


class LibraryGroupOrderRequest(RootModel[list[LibraryGroupOrderEntry]]):
    pass


class LibraryGroupOrderResponse(LibraryScanApiModel):
    success: bool
    order: list[LibraryGroupOrderEntry] = Field(default_factory=list)


class ServerOrderRequest(RootModel[list[str]]):
    pass


class LibraryMutationSuccessResponse(LibraryScanApiModel):
    success: bool
    message: str | None = None


def request_body_schema(model: type[BaseModel]) -> dict:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }
