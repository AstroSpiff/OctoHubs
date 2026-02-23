from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def _parse_emby_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_int_range(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < min_value:
        return min_value
    if number > max_value:
        return max_value
    return number


def _coerce_threshold(value: Any, default: float) -> float:
    if value is None:
        return default
    text = str(value).strip().replace("%", "")
    if not text:
        return default
    try:
        threshold = float(text)
    except ValueError:
        return default
    if threshold > 1:
        threshold = threshold / 100.0
    if threshold < 0.5:
        return 0.5
    if threshold > 1:
        return 1.0
    return threshold
