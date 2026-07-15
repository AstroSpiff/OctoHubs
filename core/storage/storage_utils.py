"""Utility helpers for storage parsing and normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _normalize_text_array(value: Any) -> Optional[List[str]]:
    if isinstance(value, list):
        cleaned: List[str] = []
        for item in value:
            text = _normalize_text_value(item)
            if text is None:
                continue
            cleaned.append(text)
        return cleaned or None
    return None


def _normalize_int_array(value: Any) -> Optional[List[int]]:
    if isinstance(value, list):
        cleaned: List[int] = []
        for item in value:
            try:
                cleaned.append(int(item))
            except (TypeError, ValueError):
                continue
        return cleaned
    return None


def _parse_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_text_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if "\x00" in text:
        text = text.replace("\x00", "")
    return text if text != "" else None


def _truncate_text_value(value: Any, max_len: Optional[int]) -> Optional[str]:
    text = _normalize_text_value(value)
    if text is None:
        return None
    if max_len and len(text) > max_len:
        return text[:max_len]
    return text


def _build_connection_url(settings: Dict[str, Any]) -> str:
    if settings.get("URL"):
        return settings["URL"]
    driver = settings.get("DRIVER") or "postgresql+psycopg2"
    host = settings.get("HOST") or "localhost"
    port = settings.get("PORT") or 5432
    database = settings.get("NAME") or "jellychecker"
    user = settings.get("USER") or ""
    password = settings.get("PASSWORD") or ""
    auth = ""
    if user:
        auth = user
        if password:
            from urllib.parse import quote_plus

            auth += f":{quote_plus(password)}"
        auth += "@"
    params = settings.get("PARAMS") or ""
    suffix = f"?{params}" if params else ""
    return f"{driver}://{auth}{host}:{port}/{database}{suffix}"
