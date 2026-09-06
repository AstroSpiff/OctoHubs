"""Canonical validation and projection for library group names."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal, overload

from pydantic import BeforeValidator, Field, StringConstraints


MAX_LIBRARY_GROUP_NAME_LENGTH = 500
LIBRARY_GROUP_NAME_PATTERN = (
    r"^[^\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]*$"
)
def _is_forbidden_character(character: str) -> bool:
    category = unicodedata.category(character)
    return category in {"Cc", "Cf", "Zl", "Zp"}


def _reject_forbidden_characters(value: Any) -> Any:
    if isinstance(value, str) and any(_is_forbidden_character(char) for char in value):
        raise ValueError("group_name contiene caratteri di controllo o invisibili")
    return value

LibraryGroupName = Annotated[
    str,
    BeforeValidator(_reject_forbidden_characters),
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_LIBRARY_GROUP_NAME_LENGTH,
    ),
    Field(json_schema_extra={"pattern": LIBRARY_GROUP_NAME_PATTERN}),
]

BoundedLibraryGroupName = Annotated[
    str,
    BeforeValidator(_reject_forbidden_characters),
    StringConstraints(
        strip_whitespace=True,
        max_length=MAX_LIBRARY_GROUP_NAME_LENGTH,
    ),
    Field(json_schema_extra={"pattern": LIBRARY_GROUP_NAME_PATTERN}),
]


@overload
def normalize_library_group_name(
    value: Any,
    *,
    optional: Literal[False] = False,
) -> str: ...


@overload
def normalize_library_group_name(
    value: Any,
    *,
    optional: Literal[True],
) -> str | None: ...


def normalize_library_group_name(
    value: Any,
    *,
    optional: bool = False,
) -> str | None:
    """Validate a mutation value before it reaches fan-out or storage."""
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("group_name non valido")
    if any(_is_forbidden_character(character) for character in value):
        raise ValueError("group_name contiene caratteri di controllo o invisibili")
    normalized = value.strip()
    if not normalized:
        raise ValueError("group_name mancante")
    if len(normalized) > MAX_LIBRARY_GROUP_NAME_LENGTH:
        raise ValueError(
            f"group_name supera {MAX_LIBRARY_GROUP_NAME_LENGTH} caratteri"
        )
    return normalized


def project_library_group_name(value: Any) -> str:
    """Bound a non-authoritative upstream name for response and workflow use."""
    if not isinstance(value, str):
        return ""
    normalized = "".join(
        " " if _is_forbidden_character(character) else character
        for character in value
    ).strip()
    return normalized[:MAX_LIBRARY_GROUP_NAME_LENGTH].rstrip()


__all__ = [
    "BoundedLibraryGroupName",
    "LIBRARY_GROUP_NAME_PATTERN",
    "LibraryGroupName",
    "MAX_LIBRARY_GROUP_NAME_LENGTH",
    "normalize_library_group_name",
    "project_library_group_name",
]
