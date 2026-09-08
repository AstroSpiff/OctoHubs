"""Request contracts for the public Emby user-icon API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.storage.field_limits import (
    ICON_BINDING_TARGET_ID_MAX_LENGTH,
    ICON_PROFILE_ID_MAX_LENGTH,
    ICON_PROFILE_LABEL_MAX_LENGTH,
    ICON_RULE_COLUMN_KEY_MAX_LENGTH,
    require_icon_target_id,
)


class IconApiRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class IconProfileRequest(IconApiRequest):
    profile_id: str = Field(default="", max_length=ICON_PROFILE_ID_MAX_LENGTH)
    label: str = Field(min_length=1, max_length=ICON_PROFILE_LABEL_MAX_LENGTH)
    is_group_profile: bool = False


class IconProfileDeleteRequest(IconApiRequest):
    profile_id: str = Field(min_length=1, max_length=ICON_PROFILE_ID_MAX_LENGTH)


class IconBindingRequest(IconApiRequest):
    target_type: Literal["user", "group"]
    target_id: str = Field(min_length=1, max_length=ICON_BINDING_TARGET_ID_MAX_LENGTH)
    profile_id: str = Field(default="", max_length=ICON_PROFILE_ID_MAX_LENGTH)

    @model_validator(mode="after")
    def validate_user_target(self) -> "IconBindingRequest":
        self.target_id = require_icon_target_id(self.target_type, self.target_id)
        return self


class IconRuleDeleteRequest(IconApiRequest):
    profile_id: str = Field(min_length=1, max_length=ICON_PROFILE_ID_MAX_LENGTH)
    column_key: str = Field(min_length=1, max_length=ICON_RULE_COLUMN_KEY_MAX_LENGTH)


class IconRuleCoordinates(IconApiRequest):
    """Validate multipart coordinates again for direct route invocation tests."""

    profile_id: str = Field(min_length=1, max_length=ICON_PROFILE_ID_MAX_LENGTH)
    column_key: str = Field(min_length=1, max_length=ICON_RULE_COLUMN_KEY_MAX_LENGTH)
