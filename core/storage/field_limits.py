"""Canonical text limits shared by storage models and their input boundaries."""

from __future__ import annotations

from typing import Any

from core.emby_identifiers import EMBY_IDENTIFIER_MAX_LENGTH, normalize_emby_identifier


EMBY_STORED_IDENTIFIER_MAX_LENGTH = EMBY_IDENTIFIER_MAX_LENGTH
INTERNAL_SERVER_ID_MAX_LENGTH = 36
EMBY_USER_NAME_MAX_LENGTH = 255
EMBY_GROUP_ID_MAX_LENGTH = 255
UNLINKED_GROUP_ID_PREFIX = "unlinked_"
SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH = (
    len(UNLINKED_GROUP_ID_PREFIX) + (2 * EMBY_IDENTIFIER_MAX_LENGTH) + 1
)
EMBY_BACKUP_TYPE_MAX_LENGTH = 50

ICON_PROFILE_ID_MAX_LENGTH = 36
ICON_PROFILE_LABEL_MAX_LENGTH = 255
ICON_RULE_COLUMN_KEY_MAX_LENGTH = 100
ICON_BINDING_TARGET_TYPE_MAX_LENGTH = 20
ICON_BINDING_TARGET_ID_MAX_LENGTH = (2 * EMBY_IDENTIFIER_MAX_LENGTH) + 1
ICON_BINDING_TARGET_TYPES = frozenset({"user", "group"})


def require_bounded_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    """Normalize and reject a value before it reaches a bounded SQL column."""
    normalized = str(value or "").strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def require_icon_target_type(value: Any) -> str:
    normalized = require_bounded_text(
        value,
        field="target_type",
        max_length=ICON_BINDING_TARGET_TYPE_MAX_LENGTH,
    )
    if normalized not in ICON_BINDING_TARGET_TYPES:
        raise ValueError("target_type must be 'user' or 'group'")
    return normalized


def require_emby_identifier(value: Any, *, field: str) -> str:
    normalized_input = require_bounded_text(
        value,
        field=field,
        max_length=EMBY_STORED_IDENTIFIER_MAX_LENGTH,
    )
    normalized = normalize_emby_identifier(normalized_input)
    if normalized != normalized_input:
        raise ValueError(f"{field} is not a valid Emby identifier")
    assert normalized is not None
    return normalized


def optional_emby_identifier(value: Any, *, field: str) -> str | None:
    """Validate an optional persisted remote Emby identifier."""
    if value is None or value == "":
        return None
    return require_emby_identifier(value, field=field)


def require_icon_target_id(target_type: Any, value: Any) -> str:
    normalized_type = require_icon_target_type(target_type)
    maximum = (
        EMBY_GROUP_ID_MAX_LENGTH
        if normalized_type == "group"
        else ICON_BINDING_TARGET_ID_MAX_LENGTH
    )
    normalized = require_bounded_text(
        value,
        field="target_id",
        max_length=maximum,
    )
    if normalized_type == "user":
        if normalized.count(":") != 1:
            raise ValueError("user target_id must be '<server_id>:<user_id>'")
        server_id, user_id = normalized.split(":", 1)
        if server_id != server_id.strip() or user_id != user_id.strip():
            raise ValueError("user target_id must be '<server_id>:<user_id>'")
        try:
            require_emby_identifier(server_id, field="server_id")
            require_emby_identifier(user_id, field="user_id")
        except ValueError:
            raise ValueError("user target_id must be '<server_id>:<user_id>'")
    return normalized


def require_emby_username(value: Any) -> str:
    normalized = require_bounded_text(
        value,
        field="username",
        max_length=EMBY_USER_NAME_MAX_LENGTH,
    )
    if len(normalized.casefold()) > EMBY_USER_NAME_MAX_LENGTH:
        raise ValueError(
            f"normalized username exceeds {EMBY_USER_NAME_MAX_LENGTH} characters"
        )
    return normalized


def build_unlinked_group_id(server_id: Any, user_id: Any) -> str:
    """Build the canonical synthetic password key for one unlinked user."""
    server = require_emby_identifier(server_id, field="server_id")
    user = require_emby_identifier(user_id, field="user_id")
    return f"{UNLINKED_GROUP_ID_PREFIX}{server}_{user}"


def require_group_password_id(value: Any) -> str:
    return require_bounded_text(
        value,
        field="group_id",
        max_length=SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH,
    )


__all__ = [
    "EMBY_BACKUP_TYPE_MAX_LENGTH",
    "EMBY_GROUP_ID_MAX_LENGTH",
    "EMBY_STORED_IDENTIFIER_MAX_LENGTH",
    "EMBY_USER_NAME_MAX_LENGTH",
    "ICON_BINDING_TARGET_ID_MAX_LENGTH",
    "ICON_BINDING_TARGET_TYPE_MAX_LENGTH",
    "ICON_BINDING_TARGET_TYPES",
    "ICON_PROFILE_ID_MAX_LENGTH",
    "ICON_PROFILE_LABEL_MAX_LENGTH",
    "ICON_RULE_COLUMN_KEY_MAX_LENGTH",
    "INTERNAL_SERVER_ID_MAX_LENGTH",
    "SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH",
    "UNLINKED_GROUP_ID_PREFIX",
    "build_unlinked_group_id",
    "require_bounded_text",
    "require_emby_username",
    "require_emby_identifier",
    "optional_emby_identifier",
    "require_icon_target_id",
    "require_icon_target_type",
    "require_group_password_id",
]
