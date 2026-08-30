"""OpenAPI contracts for Emby media lookup and availability reads."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class EmbyMediaApiModel(BaseModel):
    """Document stable media fields while allowing Emby metadata to evolve."""

    model_config = ConfigDict(extra="allow")


class MovieVersion(EmbyMediaApiModel):
    item_id: str | None = None
    name: str | None = None
    resolutions: list[str] = Field(default_factory=list)


class MovieVersionsResponse(EmbyMediaApiModel):
    success: Literal[True]
    versions: list[MovieVersion] = Field(default_factory=list)


class SeriesSeason(EmbyMediaApiModel):
    season_id: str | None = None
    season_number: int | None = None
    name: str | None = None
    episode_count: int = 0


class SeriesSeasonsResponse(EmbyMediaApiModel):
    success: Literal[True]
    seasons: list[SeriesSeason] = Field(default_factory=list)


class MediaResolution(EmbyMediaApiModel):
    label: str
    item_id: str | None = None
    source_index: int = 0


class SeasonEpisode(EmbyMediaApiModel):
    episode_id: str | None = None
    episode_number: int | None = None
    name: str | None = None
    year: int | None = None
    resolutions: list[MediaResolution] = Field(default_factory=list)


class SeasonEpisodesResponse(EmbyMediaApiModel):
    success: Literal[True]
    episodes: list[SeasonEpisode] = Field(default_factory=list)


class EmbyItemDetails(EmbyMediaApiModel):
    title: str | None = None
    year: int | None = None
    server: str | None = None
    server_icon: str | None = None
    server_icon_color: str | None = None
    server_icon_style: str | None = None
    resolution: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    bitrate: int | float | None = None
    bitrate_mbps: int | float | None = None
    path: str = ""
    audio_tracks: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    item_id: str | None = None
    item_type: str | None = None


class ItemDetailsResponse(EmbyMediaApiModel):
    success: Literal[True]
    details: EmbyItemDetails


class EmbyLookupResponse(EmbyMediaApiModel):
    success: Literal[True]
    found: bool
    message: str | None = None
    details: EmbyItemDetails | None = None


class EmbyAvailabilityRequest(StrictRequestModel):
    tmdb_id: int
    media_type: Literal["movie", "tv"] | str | None = None


class EmbyAvailabilityResponse(EmbyMediaApiModel):
    success: Literal[True]
    available_on: list[dict[str, Any]] = Field(default_factory=list)


class VirtualFolderRefreshData(EmbyMediaApiModel):
    name: str | None = None
    id: str | None = None
    refresh_status: str | None = None
    refresh_progress: float | int | None = None


class DebugVirtualFoldersServer(EmbyMediaApiModel):
    server: str
    error: str | None = None
    total_folders: int | None = None
    folders_with_refresh_data: list[VirtualFolderRefreshData] = Field(default_factory=list)
    sample_folder_keys: list[str] = Field(default_factory=list)


class DebugVirtualFoldersResponse(EmbyMediaApiModel):
    success: Literal[True]
    results: list[DebugVirtualFoldersServer] = Field(default_factory=list)


def request_body_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Publish the model enforced by a Request-based JSON route."""
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": model.model_json_schema()}},
        }
    }


def query_parameters(*items: tuple[str, bool, str]) -> dict[str, Any]:
    """Add query fields to routes that deliberately parse Request themselves."""
    return {
        "parameters": [
            {
                "name": name,
                "in": "query",
                "required": required,
                "schema": {"type": schema_type},
            }
            for name, required, schema_type in items
        ]
    }
