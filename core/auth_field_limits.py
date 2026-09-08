"""Canonical persistence limits for authentication records."""

from __future__ import annotations

from typing import Any


ACCOUNT_EMAIL_MAX_LENGTH = 120
ACCOUNT_USERNAME_MAX_LENGTH = 80
API_TOKEN_NAME_MAX_LENGTH = 120


def normalize_account_email(value: Any) -> str | None:
    """Normalize an optional email and reject values the schema cannot store."""
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if "\x00" in normalized:
        raise ValueError("email contains a NUL character")
    if len(normalized) > ACCOUNT_EMAIL_MAX_LENGTH:
        raise ValueError(
            f"email exceeds {ACCOUNT_EMAIL_MAX_LENGTH} characters"
        )
    return normalized


def require_account_username(value: Any) -> str:
    """Normalize an account identity and reject values the schema cannot store."""
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("username is required")
    if "\x00" in normalized:
        raise ValueError("username contains a NUL character")
    if len(normalized) > ACCOUNT_USERNAME_MAX_LENGTH:
        raise ValueError(
            f"username exceeds {ACCOUNT_USERNAME_MAX_LENGTH} characters"
        )
    return normalized


def require_api_token_name(value: Any) -> str:
    """Normalize a token label without silently changing its persisted identity."""
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("token name is required")
    if "\x00" in normalized:
        raise ValueError("token name contains a NUL character")
    if len(normalized) > API_TOKEN_NAME_MAX_LENGTH:
        raise ValueError(
            f"token name exceeds {API_TOKEN_NAME_MAX_LENGTH} characters"
        )
    return normalized


__all__ = [
    "ACCOUNT_EMAIL_MAX_LENGTH",
    "ACCOUNT_USERNAME_MAX_LENGTH",
    "API_TOKEN_NAME_MAX_LENGTH",
    "normalize_account_email",
    "require_account_username",
    "require_api_token_name",
]
