"""Shared strength policy for operator-supplied application secrets."""

from __future__ import annotations


MIN_SECRET_BYTES = 32
MIN_SECRET_UNIQUE_CHARACTERS = 4


def is_strong_secret(value: object) -> bool:
    """Return whether a secret meets the minimum non-trivial strength policy."""
    raw = str(value or "")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return False
    normalized = raw.strip()
    return (
        len(normalized.encode("utf-8")) >= MIN_SECRET_BYTES
        and len(set(normalized)) >= MIN_SECRET_UNIQUE_CHARACTERS
    )


__all__ = ["MIN_SECRET_BYTES", "MIN_SECRET_UNIQUE_CHARACTERS", "is_strong_secret"]
