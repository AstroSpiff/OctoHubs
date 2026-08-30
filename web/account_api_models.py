"""OpenAPI contracts for external account and access-management operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from web.request_validation import StrictRequestModel


class AccountApiModel(BaseModel):
    """Shared base for stable account API payloads."""

    model_config = ConfigDict(extra="allow")


class AccountRecord(AccountApiModel):
    id: int
    username: str
    email: str = ""
    role: Literal["admin", "user", "viewer"]
    is_active: bool
    created_at: str | None = None
    last_login: str | None = None


class CurrentAccountRecord(AccountRecord):
    preferences: dict[str, str] = Field(default_factory=dict)


class CurrentAccountResponse(AccountApiModel):
    account: CurrentAccountRecord


class AccountActionResponse(AccountApiModel):
    success: bool
    message: str | None = None


class AccountMutationResponse(AccountActionResponse):
    account: AccountRecord


class AccountListResponse(AccountApiModel):
    accounts: list[AccountRecord] = Field(default_factory=list)


class ApiTokenAuditSummary(AccountApiModel):
    action: str
    at: str | None = None
    method: str = ""
    path: str = ""
    required_scope: str = ""
    result: Literal["allowed", "denied"] | str = "allowed"


class ApiTokenRecord(AccountApiModel):
    id: int
    name: str
    prefix: str
    scopes: list[str] = Field(default_factory=list)
    permission_profile: Literal["read_only", "operator", "administrator"] | None = None
    is_active: bool
    is_expired: bool
    status: Literal["active", "expired", "revoked"]
    created_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None
    expires_at: str | None = None
    last_action: ApiTokenAuditSummary | None = None


class ApiTokenPermissionProfile(AccountApiModel):
    id: Literal["read_only", "operator", "administrator"]
    scopes: list[str] = Field(default_factory=list)


class ApiTokenListResponse(AccountApiModel):
    available_permission_profiles: list[ApiTokenPermissionProfile] = Field(default_factory=list)
    tokens: list[ApiTokenRecord] = Field(default_factory=list)


class ApiTokenSecretResponse(AccountActionResponse):
    token: ApiTokenRecord
    secret: str


class ApiTokenAuditEvent(AccountApiModel):
    id: int
    at: str | None = None
    token_id: int
    token_name: str
    token_prefix: str
    action: str
    result: Literal["allowed", "denied"]
    required_scope: str
    method: str
    path: str
    api_version: Literal["v1", "legacy", "unknown"]
    ip_address: str
    user_agent: str


class ApiTokenAuditFilters(AccountApiModel):
    token_id: int | None = None
    result: Literal["allowed", "denied"] | None = None
    api_version: Literal["v1", "legacy"] | None = None
    limit: int | None = None


class ApiTokenAuditListResponse(AccountApiModel):
    events: list[ApiTokenAuditEvent] = Field(default_factory=list)
    filters: ApiTokenAuditFilters


class ApiTokenAuditExportResponse(AccountApiModel):
    generated_at: str
    filters: ApiTokenAuditFilters
    events: list[ApiTokenAuditEvent] = Field(default_factory=list)


class PasswordUpdateRequest(StrictRequestModel):
    current_password: str
    new_password: str


class ApiTokenCreateRequest(StrictRequestModel):
    name: str
    permission_profile: Literal["read_only", "operator", "administrator"]
    expires_in_days: int | None = None


class AccountCreateRequest(StrictRequestModel):
    username: str
    password: str
    email: str | None = None
    role: Literal["admin", "user", "viewer"] = "user"


class AccountUpdateRequest(StrictRequestModel):
    email: str | None = None
    role: Literal["admin", "user", "viewer"] | None = None
    is_active: bool | None = None
    password: str | None = None
