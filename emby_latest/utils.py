"""
Utility functions for Latest Publications system.
Provides formatting, validation, and helper functions.
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


def is_blank_value(value: Any) -> bool:
    """
    Check if a value is considered blank/empty.

    Args:
        value: Value to check

    Returns:
        True if value is None, empty string, empty list, or whitespace-only string
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def format_date(value: Any) -> str:
    """
    Format date value to "DD.MM.'YY" format.

    Args:
        value: Date value (datetime, string, or None)

    Returns:
        Formatted date string, or empty string if invalid
    """
    from utils import _parse_date_value

    parsed = _parse_date_value(value)
    if not parsed:
        return ""
    local = parsed.astimezone()
    return f"{local.day:02d}.{local.month:02d}.'{local.year % 100:02d}"


def format_runtime(minutes: Optional[int]) -> str:
    """
    Format runtime in minutes to "Xh Ym" format.

    Args:
        minutes: Runtime in minutes

    Returns:
        Formatted runtime string (e.g., "1h 30m"), or empty string if invalid
    """
    if minutes is None:
        return ""
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours = total // 60
    mins = total % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def format_size(value: Optional[int]) -> str:
    """
    Format file size to human-readable format.

    Args:
        value: Size in bytes

    Returns:
        Formatted size string (e.g., "1.2 GB"), or empty string if invalid
    """
    if value is None:
        return ""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""

    # Convert to appropriate unit
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size_float = float(size)

    while size_float >= 1024 and unit_index < len(units) - 1:
        size_float /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size_float)} {units[unit_index]}"
    else:
        return f"{size_float:.1f} {units[unit_index]}"


def limit_by_server(items: Any, per_server_limit: int) -> Any:
    """
    Limit number of items per server.

    Args:
        items: Dict of server_id -> list of items
        per_server_limit: Maximum items per server

    Returns:
        Items dict with limited items per server
    """
    if per_server_limit <= 0:
        return items

    if isinstance(items, list):
        counts: Dict[str, int] = {}
        output: List[Any] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            server_id = str(item.get("server_id") or "unknown")
            current = counts.get(server_id, 0)
            if current >= per_server_limit:
                continue
            counts[server_id] = current + 1
            output.append(item)
        return output

    if isinstance(items, dict):
        limited: Dict[str, Any] = {}
        for server_id, item_list in items.items():
            if isinstance(item_list, list):
                limited[server_id] = item_list[:per_server_limit]
            else:
                limited[server_id] = item_list
        return limited

    return items


def prune_items(
    items: Dict[str, Any],
    max_count: int,
    retention_days: int
) -> Dict[str, Any]:
    """
    Prune old items based on count and age limits.

    Args:
        items: Items dict with movies and series lists
        max_count: Maximum total items to keep
        retention_days: Maximum age in days

    Returns:
        Pruned items dict
    """
    from utils import _parse_date_value

    if not isinstance(items, dict):
        return items

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Prune movies
    movies = items.get("movies", [])
    if isinstance(movies, list):
        # Filter by date
        if retention_days > 0:
            filtered_movies = []
            for m in movies:
                if not isinstance(m, dict):
                    continue
                parsed = _parse_date_value(m.get("added_at"))
                if parsed and parsed >= cutoff_date:
                    filtered_movies.append(m)
            movies = filtered_movies
        # Limit by count
        if max_count > 0 and len(movies) > max_count:
            # Sort by date descending
            movies.sort(
                key=lambda m: _parse_date_value(m.get("added_at")) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True
            )
            movies = movies[:max_count]

    # Prune series
    series = items.get("series", [])
    if isinstance(series, list):
        if retention_days > 0:
            filtered_series = []
            for s in series:
                if not isinstance(s, dict):
                    continue
                parsed = _parse_date_value(s.get("added_at"))
                if parsed and parsed >= cutoff_date:
                    filtered_series.append(s)
            series = filtered_series
        if max_count > 0 and len(series) > max_count:
            series.sort(
                key=lambda s: _parse_date_value(s.get("added_at")) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True
            )
            series = series[:max_count]

    return {
        "movies": movies,
        "series": series,
        "errors": items.get("errors", [])
    }


def _get_omdb_cache_hours(config: Optional[Dict[str, Any]]) -> int:
    default_hours = 12
    if not isinstance(config, dict):
        return default_hours
    try:
        hours = int(config.get("OMDB_CACHE_HOURS") or 0)
    except (TypeError, ValueError):
        return default_hours
    if hours <= 0:
        return default_hours
    return hours


def debug_enabled(settings_cfg: Optional[Dict] = None) -> bool:
    """
    Check if debug mode is enabled for Latest Publications.

    Checks:
    1. OCTOHUB_LATEST_DEBUG environment variable
    2. debug_latest setting in config

    Args:
        settings_cfg: Optional settings config dict

    Returns:
        True if debug mode is enabled
    """
    from utils import normalize_string

    env_flag = normalize_string(os.getenv("OCTOHUB_LATEST_DEBUG", ""))
    if env_flag in ("1", "true", "yes", "on"):
        return True

    if settings_cfg and isinstance(settings_cfg, dict):
        cfg_flag = normalize_string(settings_cfg.get("debug_latest") or "")
        return cfg_flag in ("1", "true", "yes", "on")

    return False


def debug(enabled: bool, message: str) -> None:
    """
    Print debug message if debug is enabled.

    Args:
        enabled: Whether debug is enabled
        message: Message to print
    """
    if not enabled:
        return
    print(f"[LATEST_DEBUG] {message}")
