# utils.py
"""Utility functions used across the application."""

import re
import copy
from datetime import datetime, timezone
from typing import Any, Optional


# --- STRING AND FORM UTILITIES ---

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
    text = str(value).strip().lower()
    return text or fallback


def _safe_get_dict_value(obj, key, default=""):
    """Safely get a string value from dict and strip it."""
    if not isinstance(obj, dict):
        return default
    value = obj.get(key)
    if value is None:
        return default
    return str(value).strip()


def _normalize_form_input(form, key):
    """Extract and normalize form input value."""
    value = form.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _form_input_value(form, key):
    """Get form input value as stripped string."""
    value = form.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _apply_form_mapping(form, base_dict, mappings):
    """Apply multiple form field mappings to a dict."""
    result = copy.deepcopy(base_dict) if base_dict else {}
    for form_key, target_key in mappings:
        value = _normalize_form_input(form, form_key)
        if value or target_key not in result:
            result[target_key] = value
    return result


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
    lowered = str(value).strip().lower()
    if lowered in {"movie", "movies", "film"}:
        return "movie"
    if lowered in {"tv", "show", "series", "tvshow"}:
        return "tv"
    return None
