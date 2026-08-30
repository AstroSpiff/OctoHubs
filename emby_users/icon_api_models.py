"""Request contracts for the public Emby user-icon API."""

from pydantic import BaseModel, ConfigDict, Field


class IconApiRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class IconProfileRequest(IconApiRequest):
    profile_id: str = ""
    label: str = Field(min_length=1)
    is_group_profile: bool = False


class IconProfileDeleteRequest(IconApiRequest):
    profile_id: str = Field(min_length=1)


class IconBindingRequest(IconApiRequest):
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    profile_id: str = ""


class IconRuleDeleteRequest(IconApiRequest):
    profile_id: str = Field(min_length=1)
    column_key: str = Field(min_length=1)
