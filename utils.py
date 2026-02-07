# utils.py
"""Utility functions used across the application."""

import re
from datetime import datetime, timezone
from typing import Any, Optional, Dict


# --- DICTIONARY MERGE UTILITIES ---

def merge_nested_dict(base: Dict[str, Any], updates: Optional[Dict[str, Any]], *,
                      preserve_none: bool = False,
                      skip_empty_strings: bool = False) -> Dict[str, Any]:
    """
    Recursively merge two nested dictionaries.

    Args:
        base: Base dictionary (will be deep copied to avoid mutations)
        updates: Dictionary with updates to merge into base
        preserve_none: If True, None values in updates will override base values
        skip_empty_strings: If True, empty strings in updates won't override base values

    Returns:
        New dictionary with merged values

    Examples:
        >>> base = {"a": {"b": 1, "c": 2}, "d": 3}
        >>> updates = {"a": {"b": 10}, "e": 4}
        >>> merge_nested_dict(base, updates)
        {"a": {"b": 10, "c": 2}, "d": 3, "e": 4}

        >>> base = {"url": "http://example.com", "api_key": "secret"}
        >>> updates = {"url": "", "enabled": True}
        >>> merge_nested_dict(base, updates, skip_empty_strings=True)
        {"url": "http://example.com", "api_key": "secret", "enabled": True}
    """
    import copy

    if not isinstance(base, dict):
        base = {}

    result = copy.deepcopy(base)

    if not isinstance(updates, dict):
        return result

    for key, value in updates.items():
        # Skip None values unless explicitly allowed
        if value is None and not preserve_none:
            continue

        # Skip empty strings if requested (useful for connection fields)
        if skip_empty_strings and isinstance(value, str) and value == "":
            continue

        # If both base and update values are dicts, merge recursively
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_nested_dict(
                result[key],
                value,
                preserve_none=preserve_none,
                skip_empty_strings=skip_empty_strings
            )
        else:
            # Otherwise, override with the new value
            result[key] = copy.deepcopy(value)

    return result


# --- STRING AND FORM UTILITIES ---

def get_nested(obj, *keys, default=None):
    """
    Safely access nested dictionary values.

    Args:
        obj: Dictionary to navigate
        *keys: Sequence of keys to traverse
        default: Default value if path not found

    Returns:
        Value at nested path or default

    Examples:
        >>> get_nested(config, "EMBY", "SERVERS", default=[])
        [...]
        >>> get_nested(auto_settings, "rss", "enabled", default=False)
        False
        >>> get_nested(server, "status", "server_id")
        'uuid-1234'
    """
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


def normalize_string(value, to_lower=True, default=""):
    """
    Normalize string: convert to str, strip whitespace, optionally lowercase.

    Args:
        value: Value to normalize (can be None, str, int, etc.)
        to_lower: Convert to lowercase (default True)
        default: Default value if input is None/empty (default "")

    Returns:
        Normalized string

    Examples:
        >>> normalize_string("  Hello  ")
        'hello'
        >>> normalize_string("  Hello  ", to_lower=False)
        'Hello'
        >>> normalize_string(None, default="default")
        'default'
    """
    text = str(value or default).strip()
    return text.lower() if to_lower else text


def normalize_path(path, to_lower=True):
    """
    Normalize a file/directory path: strip whitespace and trailing slashes.

    Args:
        path: Path string to normalize
        to_lower: Convert to lowercase (default True)

    Returns:
        Normalized path string

    Examples:
        >>> normalize_path("/path/to/dir/")
        '/path/to/dir'
        >>> normalize_path("C:\\Windows\\System\\")
        'c:/windows/system'
        >>> normalize_path("/PATH/", to_lower=False)
        '/PATH'
    """
    normalized = str(path or "").strip().rstrip('/').rstrip('\\')
    return normalized.lower() if to_lower else normalized


def normalize_url(url):
    """
    Normalize a URL: strip whitespace and trailing slashes.

    Args:
        url: URL string to normalize

    Returns:
        Normalized URL string

    Examples:
        >>> normalize_url("  http://example.com/  ")
        'http://example.com'
        >>> normalize_url("http://example.com/path/")
        'http://example.com/path'
    """
    return str(url or "").strip().rstrip("/")


DEFAULT_RESOLUTION_RULES = {
    "enabled": True,
    "thresholds": {
        "2160p": {"min_height": 2000, "min_width": 3800, "min_scope_height": 1400},
        "1440p": {"min_height": 1200, "min_width": 2500},
        "1080p": {"min_height": 700, "min_width": 1800},
        "720p": {"min_height": 520, "min_width": 1200},
        "576p": {"min_height": 540},
        "480p": {"min_height": 450}
    }
}


def _resolution_label_from_dims(width: Any, height: Any, rules: Optional[dict] = None) -> str:
    if not width or not height:
        return ""
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        return ""
    if w <= 0 or h <= 0:
        return ""
    w, h = (w, h) if w >= h else (h, w)

    active_rules = rules if isinstance(rules, dict) else DEFAULT_RESOLUTION_RULES
    enabled = _coerce_request_bool(active_rules.get("enabled"), True)
    thresholds = active_rules.get("thresholds") if isinstance(active_rules.get("thresholds"), dict) else None
    if not isinstance(thresholds, dict):
        thresholds = DEFAULT_RESOLUTION_RULES["thresholds"]

    def _threshold(res_key: str, key: str, fallback: int) -> int:
        value = thresholds.get(res_key, {}).get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    if not enabled:
        if h >= 2160:
            return "2160p"
        if h >= 1440:
            return "1440p"
        if h >= 1080:
            return "1080p"
        if h >= 720:
            return "720p"
        pal_min = _threshold("576p", "min_height", 540)
        ntsc_min = _threshold("480p", "min_height", 450)
        if h >= pal_min:
            return "576p"
        if h >= ntsc_min:
            return "480p"
        return f"{h}p"

    uhd_min_height = _threshold("2160p", "min_height", 2000)
    uhd_min_width = _threshold("2160p", "min_width", 3800)
    uhd_scope_min_height = _threshold("2160p", "min_scope_height", 1400)
    qhd_min_height = _threshold("1440p", "min_height", 1200)
    qhd_min_width = _threshold("1440p", "min_width", 2500)
    fhd_min_height = _threshold("1080p", "min_height", 700)
    fhd_min_width = _threshold("1080p", "min_width", 1800)
    hd_min_height = _threshold("720p", "min_height", 520)
    hd_min_width = _threshold("720p", "min_width", 1200)
    pal_min = _threshold("576p", "min_height", 540)
    ntsc_min = _threshold("480p", "min_height", 450)

    if h >= uhd_min_height or (w >= uhd_min_width and h >= uhd_scope_min_height):
        return "2160p"
    if w >= qhd_min_width and h >= qhd_min_height:
        return "1440p"
    if w >= fhd_min_width and h >= fhd_min_height:
        return "1080p"
    if w >= hd_min_width and h >= hd_min_height:
        return "720p"
    if h >= pal_min:
        return "576p"
    if h >= ntsc_min:
        return "480p"
    return f"{h}p"

def _split_csv_field(value: Optional[str]) -> list[str]:
    """Splits a comma-separated string into a list of cleaned-up strings."""
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def _coerce_request_bool(value: Any, default: bool) -> bool:
    """Coerces a form input value to a boolean, with a default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("", "none"):
            return default
        if normalized in ("1", "true", "yes", "y", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return bool(value)


def _coerce_request_int(value: Any, default: int = 0, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """Coerces a value to an integer with optional bounds."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None:
        number = max(min_value, number)
    if max_value is not None:
        number = min(max_value, number)
    return number


def _normalize_alt_language(value: Any, fallback: str) -> str:
    """Normalizes an alternative language code."""
    if value is None:
        return fallback
    text = normalize_string(value)
    return text or fallback


def _sanitize_terms_list(value):
    """Sanitize a list of terms (from CSV string or list)."""
    if not value:
        return []
    if isinstance(value, str):
        return _split_csv_field(value)
    sanitized = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                sanitized.append(text)
    return sanitized


# --- SEASON AND TARGET NORMALIZATION ---

def _normalize_season_spec(value):
    """Normalize season specification to a set of integers."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = int(value)
        return {parsed}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return {int(stripped)}
        except ValueError:
            return None
    if isinstance(value, bool):
        return None
    seasons = set()
    for entry in value:
        if entry is None:
            return None
        try:
            seasons.add(int(entry))
        except (TypeError, ValueError):
            continue
    return seasons or None


def _normalize_scan_targets(entries):
    """Normalize scan targets into a dict mapping request_id to spec."""
    if not entries:
        return None
    normalized = {}
    if isinstance(entries, dict) and "request_id" in entries:
        entries = [entries]
    if isinstance(entries, (int, str)):
        entries = [entries]

    for entry in entries:
        force = False
        seasons = None
        if isinstance(entry, (int, str)):
            request_id = str(entry).strip()
        elif isinstance(entry, dict):
            request_id = entry.get("request_id") or entry.get("id")
            if request_id is None:
                continue
            request_id = str(request_id).strip()
            seasons = _normalize_season_spec(entry.get("seasons"))
            force = bool(entry.get("force"))
        else:
            continue
        if not request_id:
            continue
        current = normalized.get(request_id)
        if current:
            if current["seasons"] is None or seasons is None:
                current["seasons"] = None
            else:
                current["seasons"].update(seasons)
            current["force"] = current["force"] or bool(force)
        else:
            normalized[request_id] = {
                "seasons": seasons,
                "force": bool(force)
            }
    return normalized or None


def _serialize_target_map(target_map):
    """Serialize a target map to a JSON-compatible format."""
    if not target_map:
        return None
    serialized = []
    for req_id, spec in target_map.items():
        seasons = spec.get("seasons")
        serialized.append({
            "request_id": req_id,
            "seasons": sorted(seasons) if seasons else None,
            "force": bool(spec.get("force"))
        })
    return serialized


# --- DATE AND TIME UTILITIES ---

def _parse_date_value(value):
    """Parse a date string into a UTC datetime object."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "." in normalized:
        match = re.match(
            r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d+))?(?P<tz>[+-]\d{2}:\d{2})?$",
            normalized
        )
        if match:
            base = match.group("base")
            fraction = match.group("fraction")
            tz_part = match.group("tz") or ""
            if fraction and len(fraction) > 6:
                fraction = fraction[:6]
            if fraction:
                normalized = f"{base}.{fraction}{tz_part}"
            else:
                normalized = f"{base}{tz_part}"
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


# --- MEDIA TYPE NORMALIZATION ---

def _normalize_media_type(value):
    """Normalize media type string to 'movie' or 'tv'."""
    if not value:
        return None
    lowered = normalize_string(value)
    if lowered in {"movie", "movies", "film"}:
        return "movie"
    if lowered in {"tv", "show", "series", "tvshow"}:
        return "tv"
    return None


# --- HTTP RESPONSE UTILITIES ---

def json_error(message, status_code=400, **extra):
    """
    Create a standard JSON error response.

    Args:
        message: Error message to return
        status_code: HTTP status code (default 400)
        **extra: Additional fields to include in response

    Returns:
        Tuple of (dict, status_code)

    Examples:
        >>> json_error("Invalid request")
        ({"success": False, "message": "Invalid request"}, 400)
        >>> json_error("Not found", 404)
        ({"success": False, "message": "Not found"}, 404)
        >>> json_error("Failed", 500, errors=["err1", "err2"])
        ({"success": False, "message": "Failed", "errors": ["err1", "err2"]}, 500)
    """
    return {"success": False, "message": message, **extra}, status_code


def json_success(message=None, status_code=200, **extra):
    """
    Create a standard JSON success response.

    Args:
        message: Optional success message
        status_code: HTTP status code (default 200)
        **extra: Additional fields to include in response

    Returns:
        Tuple of (dict, status_code)

    Examples:
        >>> json_success()
        ({"success": True}, 200)
        >>> json_success("Operation completed")
        ({"success": True, "message": "Operation completed"}, 200)
        >>> json_success(data={"id": 123}, status_code=201)
        ({"success": True, "data": {"id": 123}}, 201)
    """
    response = {"success": True, **extra}
    if message is not None:
        response["message"] = message
    return response, status_code


# --- CONFIG VALIDATION UTILITIES ---

def validate_jellyseerr_config(config):
    """
    Validate Jellyseerr configuration.

    Args:
        config: Configuration dictionary

    Returns:
        bool: True if Jellyseerr is properly configured

    Examples:
        >>> validate_jellyseerr_config({"JELLYSEERR_URL": "http://...", "JELLYSEERR_API_KEY": "key"})
        True
        >>> validate_jellyseerr_config({})
        False
    """
    return bool(config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"))


def find_server_by_id(servers, server_id):
    """
    Find a server in a list by its ID.

    Args:
        servers: List of server dictionaries
        server_id: Server ID to find

    Returns:
        dict or None: Server dictionary if found, None otherwise

    Examples:
        >>> servers = [{"id": "123", "name": "Server1"}, {"id": "456", "name": "Server2"}]
        >>> find_server_by_id(servers, "123")
        {"id": "123", "name": "Server1"}
        >>> find_server_by_id(servers, "999")
        None
    """
    if not servers or not server_id:
        return None
    for server in servers:
        if server.get("id") == server_id:
            return server
    return None


def get_emby_servers(config, enabled_only=False):
    """
    Get Emby servers from configuration.

    Args:
        config: Configuration dictionary
        enabled_only: If True, return only enabled servers

    Returns:
        list: List of server dictionaries

    Examples:
        >>> config = {"EMBY": {"SERVERS": [{"id": "1", "enabled": True}, {"id": "2", "enabled": False}]}}
        >>> get_emby_servers(config)
        [{"id": "1", "enabled": True}, {"id": "2", "enabled": False}]
        >>> get_emby_servers(config, enabled_only=True)
        [{"id": "1", "enabled": True}]
    """
    servers = config.get("EMBY", {}).get("SERVERS", [])
    if enabled_only:
        return [s for s in servers if s.get("enabled")]
    return servers
