"""Validation helpers for opaque identifiers interpolated into Emby paths."""

from __future__ import annotations

import re
from typing import Annotated, Any, TypeAlias
from urllib.parse import quote

from pydantic import StringConstraints


EMBY_IDENTIFIER_MAX_LENGTH = 128
EMBY_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$"
_EMBY_IDENTIFIER_RE = re.compile(EMBY_IDENTIFIER_PATTERN)

OpaqueEmbyIdentifier: TypeAlias = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=EMBY_IDENTIFIER_MAX_LENGTH,
        pattern=EMBY_IDENTIFIER_PATTERN,
    ),
]

# Server IDs and remote object IDs share the same opaque, single-path-segment
# contract. Keep a semantic alias so request models cannot accidentally fall
# back to an unbounded plain string before allocating coordination keys.
OpaqueEmbyServerIdentifier: TypeAlias = OpaqueEmbyIdentifier


def normalize_emby_identifier(value: Any) -> str | None:
    """Return a safe single path segment, or ``None`` for unsafe input."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not _EMBY_IDENTIFIER_RE.fullmatch(normalized):
        return None
    return normalized


def quote_emby_identifier(value: Any) -> str | None:
    """Validate and quote one identifier without allowing path delimiters."""
    normalized = normalize_emby_identifier(value)
    if normalized is None:
        return None
    return quote(normalized, safe="")
