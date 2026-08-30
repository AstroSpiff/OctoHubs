"""OpenAPI response contracts for Emby users, groups and profile icons."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.operations_api_models import (
    ClearCompletedOperationsResponse,
    OperationsSnapshotResponse,
    OperationsUnavailableResponse,
)


class UserApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: Literal[False] | None = None
    error: str | None = None


class UserApiSuccessResponse(BaseModel):
    """Common successful mutation result with optional operation metadata."""

    model_config = ConfigDict(extra="allow")

    ok: Literal[True]
    result: dict[str, Any] | None = None


class EmbyUsersDashboardResponse(BaseModel):
    """User/group dashboard; group and user fields are extensible by design."""

    model_config = ConfigDict(extra="allow")

    groups: list[dict[str, Any]] = Field(default_factory=list)
    servers: list[dict[str, Any]] = Field(default_factory=list)


class UserExistsResponse(BaseModel):
    exists: bool


class UserGroupLinkResponse(UserApiSuccessResponse):
    group_id: str
    group_health: dict[str, Any] | None = None


class UserSettingsPresetListResponse(BaseModel):
    ok: Literal[True]
    presets: list[dict[str, Any]] = Field(default_factory=list)


class UserSettingsPresetResponse(UserApiSuccessResponse):
    preset: dict[str, Any] | None = None


class UserPasswordInfoResponse(BaseModel):
    """Saved-password state with its value limited to callers allowed to modify it."""

    model_config = ConfigDict(extra="allow")

    ok: Literal[True]
    group_id: str
    saved: bool
    updated_at: str | None = None
    # Present only for non-viewer sessions or Bearer tokens with write:users.
    password: str | None = None


class UserSettingsSchemaResponse(BaseModel):
    """Extensible schema used by the user settings editor."""

    model_config = ConfigDict(extra="allow")

    schema_version: str | int
    categories: list[dict[str, Any]] = Field(default_factory=list)
    library_groups: list[dict[str, Any]] = Field(default_factory=list)


class UserSettingsInfoResponse(BaseModel):
    """Resolved user or group settings, including their Emby source state."""

    model_config = ConfigDict(extra="allow")

    ok: bool
    saved: bool = False
    group_id: str | None = None
    server_id: str | None = None
    user_id: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None
    from_emby: bool = False
    library_items: list[dict[str, Any]] = Field(default_factory=list)
    feature_items: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class UserDetailsResponse(BaseModel):
    """Extended Emby metadata displayed by the user details dialog."""

    last_activity_date: str | None = None
    date_created: str | None = None
    last_played_date: str | None = None
    last_played_title: str | None = None
    has_password: bool = False
    connect_user_name: str | None = None
    connect_link_type: str | None = None
    error: str | None = None


class UserIconConfigResponse(BaseModel):
    """Profile/icon dashboard returned by the icon manager."""

    model_config = ConfigDict(extra="allow")


class UserIconProfileMutationResponse(UserApiSuccessResponse):
    profile_id: str | None = None


__all__ = [
    "ClearCompletedOperationsResponse",
    "EmbyUsersDashboardResponse",
    "OperationsSnapshotResponse",
    "OperationsUnavailableResponse",
    "UserApiErrorResponse",
    "UserApiSuccessResponse",
    "UserExistsResponse",
    "UserGroupLinkResponse",
    "UserIconConfigResponse",
    "UserIconProfileMutationResponse",
    "UserDetailsResponse",
    "UserSettingsPresetListResponse",
    "UserSettingsPresetResponse",
    "UserPasswordInfoResponse",
    "UserSettingsInfoResponse",
    "UserSettingsSchemaResponse",
]
