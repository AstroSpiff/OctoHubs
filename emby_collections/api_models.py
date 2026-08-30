"""OpenAPI response contracts for collection definitions and source inventory."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class CollectionErrorResponse(BaseModel):
    success: Literal[False]
    error: str


class CollectionDefinition(BaseModel):
    """A collection definition with source-specific metadata kept extensible."""

    model_config = ConfigDict(extra="allow")

    id: str


class CollectionDefinitionRequest(StrictRequestModel):
    """Writable collection fields accepted by the React editor."""

    id: str | None = None
    name: str
    sort_name: str | None = None
    source_type: str
    source_value: str
    source_origin: str | None = None
    server_ids: list[str] = Field(default_factory=list)
    poster_url: str | None = None
    background_url: str | None = None
    season_start: str | None = None
    season_end: str | None = None
    refresh_metadata: bool = False
    collection_description: str | None = None
    collection_sort_name: str | None = None
    use_source_description: bool = False
    enabled: bool = True
    auto_enabled: bool = False
    auto_frequency: int = Field(default=100, ge=0, le=100)


class CollectionSourceInventoryRequest(StrictRequestModel):
    """A manually saved external-list source for the collection inventory."""

    id: str | None = None
    name: str | None = None
    source_type: str | None = None
    source_value: str
    source_link: str | None = None


class CollectionEnabledRequest(StrictRequestModel):
    enabled: bool


class CollectionsListResponse(BaseModel):
    success: Literal[True]
    collections: list[CollectionDefinition] = Field(default_factory=list)


class CollectionServerOption(BaseModel):
    id: str
    name: str
    icon: str
    icon_color: str
    icon_style: str


class CollectionsOptionsResponse(BaseModel):
    success: Literal[True]
    source_types: dict[str, Any] | list[Any]
    servers: list[CollectionServerOption] = Field(default_factory=list)
    trakt_enabled: bool
    mdblist_enabled: bool


class CollectionMutationResponse(BaseModel):
    success: Literal[True]
    collection: CollectionDefinition | dict[str, Any] | None = None


class CollectionSuccessResponse(BaseModel):
    """Successful collection action that may include an operation or result."""

    model_config = ConfigDict(extra="allow")

    success: Literal[True]


class CollectionBackgroundOperationResponse(CollectionSuccessResponse):
    background: Literal[True]
    operation_id: str | None = None
    message: str


class CollectionSyncResponse(CollectionMutationResponse):
    details: dict[str, Any] | list[Any] | None = None


class CollectionSyncDetailsResponse(BaseModel):
    success: Literal[True]
    details: dict[str, Any] | list[Any]


class CollectionSourceListsResponse(BaseModel):
    success: Literal[True]
    lists: list[dict[str, Any]] = Field(default_factory=list)


class CollectionSourceInventoryResponse(BaseModel):
    success: Literal[True]
    items: list[dict[str, Any]] = Field(default_factory=list)
