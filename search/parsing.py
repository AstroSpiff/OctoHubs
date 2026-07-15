"""Parsing helpers for search titles."""

from __future__ import annotations

import re
from typing import Optional, Tuple


def _try_parse_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_year_from_title(title):
    if not title:
        return None
    match = re.search(r"(19|20)\d{2}", str(title))
    if not match:
        return None
    return match.group(0)


def _extract_season_hint_from_title(title) -> Tuple[Optional[int], Optional[str]]:
    if not title:
        return None, None
    text = str(title)
    range_patterns = [
        r"[Ss](\d{1,2})\s*[-–]\s*[Ss]?(\d{1,2})",
        r"Season\s*(\d{1,2})\s*[-–]\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})\s*[-–]\s*(\d{1,2})",
    ]
    for pattern in range_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = _try_parse_int(match.group(1))
            end = _try_parse_int(match.group(2))
            if start is not None and end is not None:
                return None, f"S{start:02d}-S{end:02d}"
    single_patterns = [
        r"(?:^|\b)[Ss](\d{1,2})(?!\d)",
        r"Season\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})",
    ]
    for pattern in single_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            season = _try_parse_int(match.group(1))
            if season is not None:
                return season, f"S{season:02d}"
    return None, None
