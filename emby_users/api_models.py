"""Request contracts for the public Emby user-management API."""

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from core.emby_identifiers import EMBY_IDENTIFIER_PATTERN
from core.storage.field_limits import (
    EMBY_GROUP_ID_MAX_LENGTH,
    EMBY_STORED_IDENTIFIER_MAX_LENGTH,
    EMBY_USER_NAME_MAX_LENGTH,
    SETTINGS_PRESET_ID_MAX_LENGTH,
    require_emby_username,
)


MAX_USER_BATCH_TARGETS = 100
StoredEmbyIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=EMBY_STORED_IDENTIFIER_MAX_LENGTH,
        pattern=EMBY_IDENTIFIER_PATTERN,
    ),
]
SettingsPresetIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=SETTINGS_PRESET_ID_MAX_LENGTH,
        pattern=r"^[^\x00]*$",
    ),
]


class ApiRequest(BaseModel):
    """Keep request parsing forward-compatible while documenting known fields."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ServerUserTarget(ApiRequest):
    server_id: StoredEmbyIdentifier
    user_id: StoredEmbyIdentifier


class AccessToggleRequest(ServerUserTarget):
    enable: bool


class UserLink(ApiRequest):
    server_id: StoredEmbyIdentifier
    user_id: StoredEmbyIdentifier
    username: str = Field(default="", max_length=EMBY_USER_NAME_MAX_LENGTH)
    is_leader: bool = False


class LinkUsersRequest(ApiRequest):
    links: List[UserLink] = Field(min_length=1, max_length=MAX_USER_BATCH_TARGETS)
    group_id: Optional[str] = Field(default=None, max_length=EMBY_GROUP_ID_MAX_LENGTH)

    @field_validator("links")
    @classmethod
    def reject_duplicate_links(cls, links: List[UserLink]) -> List[UserLink]:
        keys = [(link.server_id, link.user_id) for link in links]
        if len(keys) != len(set(keys)):
            raise ValueError("Ogni utente può comparire una sola volta nel batch")
        return links


class RenameGroupRequest(ApiRequest):
    group_id: str = Field(min_length=1, max_length=EMBY_GROUP_ID_MAX_LENGTH)
    new_name: str = Field(min_length=1, max_length=EMBY_USER_NAME_MAX_LENGTH)


class RenameUserRequest(ServerUserTarget):
    new_name: str = Field(min_length=1, max_length=EMBY_USER_NAME_MAX_LENGTH)


class UserPasswordRequest(ServerUserTarget):
    new_password: str = ""


class GroupPasswordRequest(ApiRequest):
    group_id: str = Field(min_length=1, max_length=EMBY_GROUP_ID_MAX_LENGTH)
    new_password: str = ""


class SettingsPresetRequest(ApiRequest):
    id: Optional[SettingsPresetIdentifier] = None
    label: str = ""
    description: str = ""
    settings: Dict[str, Any] = Field(default_factory=dict)
    apply_libraries: Optional[bool] = None


class SettingsPresetDuplicateRequest(ApiRequest):
    label: str = ""


class UserSettingsRequest(ServerUserTarget):
    settings: Dict[str, Any] = Field(default_factory=dict)


class GroupSettingsRequest(ApiRequest):
    group_id: str = Field(min_length=1, max_length=EMBY_GROUP_ID_MAX_LENGTH)
    settings: Dict[str, Any] = Field(default_factory=dict)


class BulkSettingsTarget(ServerUserTarget):
    pass


class BulkSettingsApplyRequest(ApiRequest):
    targets: List[BulkSettingsTarget] = Field(
        min_length=1,
        max_length=MAX_USER_BATCH_TARGETS,
    )
    settings: Dict[str, Any]
    apply_libraries: bool = False

    @field_validator("targets")
    @classmethod
    def reject_duplicate_targets(
        cls,
        targets: List[BulkSettingsTarget],
    ) -> List[BulkSettingsTarget]:
        keys = [(target.server_id, target.user_id) for target in targets]
        if len(keys) != len(set(keys)):
            raise ValueError("Ogni utente può comparire una sola volta nel batch")
        return targets


class GroupSyncSettingsRequest(ApiRequest):
    group_id: str = Field(min_length=1, max_length=EMBY_GROUP_ID_MAX_LENGTH)
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
    group_id: str = Field(min_length=1, max_length=EMBY_GROUP_ID_MAX_LENGTH)


class CheckUserRequest(ApiRequest):
    server_id: StoredEmbyIdentifier
    username: str = Field(min_length=1, max_length=EMBY_USER_NAME_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def validate_normalized_username(cls, username: str) -> str:
        return require_emby_username(username)


class CreateUserTarget(ApiRequest):
    server_id: StoredEmbyIdentifier
    username: str = Field(min_length=1, max_length=EMBY_USER_NAME_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def validate_normalized_username(cls, username: str) -> str:
        return require_emby_username(username)


class CreateUsersRequest(ApiRequest):
    targets: List[CreateUserTarget] = Field(
        min_length=1,
        max_length=MAX_USER_BATCH_TARGETS,
    )
    settings: Dict[str, Any] = Field(default_factory=dict)
    preset_id: Optional[SettingsPresetIdentifier] = None
    apply_libraries: bool = False
    password: str = ""
    link_group: bool = False
    group_name: str = ""

    @field_validator("targets")
    @classmethod
    def reject_duplicate_create_targets(
        cls,
        targets: List[CreateUserTarget],
    ) -> List[CreateUserTarget]:
        keys = [(target.server_id, target.username.casefold()) for target in targets]
        if len(keys) != len(set(keys)):
            raise ValueError("Ogni utente può comparire una sola volta nel batch")
        return targets


class DeleteUserRequest(ServerUserTarget):
    expected_name: str = ""


class DeleteGroupUsersRequest(GroupIdRequest):
    expected_name: str = ""


class CloneUserRequest(ApiRequest):
    source_server_id: StoredEmbyIdentifier
    source_user_id: StoredEmbyIdentifier
    target_server_id: StoredEmbyIdentifier
    new_username: Optional[str] = Field(default=None, max_length=EMBY_USER_NAME_MAX_LENGTH)
    sync_config: bool = True
    sync_playstate: bool = True
    sync_resume: bool = False
    sync_library_access: bool = False
    sync_favorites: bool = False
    sync_playlists: bool = False
    link_group: bool = False
    config_categories: List[str] = Field(default_factory=list)
