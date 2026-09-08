"""Projection helpers for descriptive text stored in bounded SQL columns."""

from __future__ import annotations

from typing import Any


def project_persisted_text(
    value: Any,
    max_length: int | None = None,
    *,
    empty_as_none: bool = True,
) -> str | None:
    """Remove PostgreSQL-illegal NULs and bound non-identity display text."""
    if value is None:
        return None
    projected = str(value).replace("\x00", "")
    if max_length is not None:
        projected = projected[:max_length]
    if not projected and empty_as_none:
        return None
    return projected


def require_persisted_text(value: Any, *, field: str) -> str:
    """Reject an empty or PostgreSQL-illegal unbounded identity string."""
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if "\x00" in normalized:
        raise ValueError(f"{field} contains a NUL character")
    return normalized


__all__ = ["project_persisted_text", "require_persisted_text"]
