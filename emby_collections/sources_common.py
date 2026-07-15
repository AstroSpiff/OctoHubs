"""Common helpers and constants for Emby collection sources."""

from __future__ import annotations

import html
from typing import Any, Dict, Sequence

PROVIDER_PRIORITY: Sequence[tuple[str, str]] = (
    ("tmdb", "Tmdb"),
    ("imdb", "Imdb"),
)
PROVIDER_LABEL_MAP: Dict[str, str] = {key: label for key, label in PROVIDER_PRIORITY}


def _clean_title(value: Any) -> str:
    if not value:
        return ""
    return html.unescape(str(value)).strip()


def _extract_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if len(trimmed) >= 4 and trimmed[:4].isdigit():
            try:
                return int(trimmed[:4])
            except ValueError:
                return None
        if trimmed.isdigit():
            try:
                return int(trimmed)
            except ValueError:
                return None
    return None
