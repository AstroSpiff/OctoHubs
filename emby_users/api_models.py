"""Request contracts for the public Emby user-management API."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiRequest(BaseModel):
    """Keep request parsing forward-compatible while documenting known fields."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ServerUserTarget(ApiRequest):
    server_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class AccessToggleRequest(ServerUserTarget):
    enable: bool


class UserLink(ApiRequest):
    server_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    username: str = ""
    is_leader: bool = False


class LinkUsersRequest(ApiRequest):
    links: List[UserLink] = Field(min_length=1)
    group_id: Optional[str] = None


class RenameGroupRequest(ApiRequest):
    group_id: str = Field(min_length=1)
    new_name: str = Field(min_length=1)


class RenameUserRequest(ServerUserTarget):
    new_name: str = Field(min_length=1)


class UserPasswordRequest(ServerUserTarget):
    new_password: str = ""


class GroupPasswordRequest(ApiRequest):
    group_id: str = Field(min_length=1)
    new_password: str = ""


class SettingsPresetRequest(ApiRequest):
    id: Optional[str] = None
    label: str = ""
    description: str = ""
    settings: Dict[str, Any] = Field(default_factory=dict)
    apply_libraries: Optional[bool] = None


class SettingsPresetDuplicateRequest(ApiRequest):
    label: str = ""


class UserSettingsRequest(ServerUserTarget):
    settings: Dict[str, Any] = Field(default_factory=dict)


class GroupSettingsRequest(ApiRequest):
    group_id: str = Field(min_length=1)
    settings: Dict[str, Any] = Field(default_factory=dict)


class BulkSettingsTarget(ServerUserTarget):
    pass


class BulkSettingsApplyRequest(ApiRequest):
    targets: List[BulkSettingsTarget] = Field(min_length=1)
    settings: Dict[str, Any]
    apply_libraries: bool = False


class GroupSyncSettingsRequest(ApiRequest):
    group_id: str = Field(min_length=1)
    auto_sync: bool = False
    sync_type: Literal["merge", "one_way"] = "merge"
    sync_resume: bool = False
    sync_playstate: bool = True
    sync_config: bool = False
    sync_library_access: bool = False
    sync_favorites: bool = False
    sync_playlists: bool = False
    config_categories: List[str] = Field(default_factory=list)
    playstate_bootstrap_done: bool = False
    favorites_bootstrap_done: bool = False
    playlists_bootstrap_done: bool = False


class GroupIdRequest(ApiRequest):
    group_id: str = Field(min_length=1)


class CheckUserRequest(ApiRequest):
    server_id: str = Field(min_length=1)
    username: str = Field(min_length=1)


class CreateUserTarget(ApiRequest):
    server_id: str = Field(min_length=1)
    username: str = Field(min_length=1)


class CreateUsersRequest(ApiRequest):
    targets: List[CreateUserTarget] = Field(min_length=1)
    settings: Dict[str, Any] = Field(default_factory=dict)
    preset_id: Optional[str] = None
    apply_libraries: bool = False
    password: str = ""
    link_group: bool = False
    group_name: str = ""


class DeleteUserRequest(ServerUserTarget):
    expected_name: str = ""


class DeleteGroupUsersRequest(GroupIdRequest):
    expected_name: str = ""


class CloneUserRequest(ApiRequest):
    source_server_id: str = Field(min_length=1)
    source_user_id: str = Field(min_length=1)
    target_server_id: str = Field(min_length=1)
    new_username: Optional[str] = None
    sync_config: bool = True
    sync_playstate: bool = True
    sync_resume: bool = False
    sync_library_access: bool = False
    sync_favorites: bool = False
    sync_playlists: bool = False
    link_group: bool = False
    config_categories: List[str] = Field(default_factory=list)
