"""Canonical public identity contract for cancellable operations."""

from __future__ import annotations

from typing import Any


MAX_PUBLIC_OPERATION_ID_LENGTH = 128
PUBLIC_OPERATION_ID_PATTERN = r"^[^\x00-\x1f\x7f]*$"


def is_valid_public_operation_id(value: Any) -> bool:
    """Return whether an operation ID can safely cross the public API boundary."""
    return bool(
        isinstance(value, str)
        and 0 < len(value) <= MAX_PUBLIC_OPERATION_ID_LENGTH
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


__all__ = [
    "MAX_PUBLIC_OPERATION_ID_LENGTH",
    "PUBLIC_OPERATION_ID_PATTERN",
    "is_valid_public_operation_id",
]
