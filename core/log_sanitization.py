"""Focused redaction helpers for diagnostic logs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit


REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "passwd",
    "secret",
    "token",
)
_URL_PATTERN = re.compile(r"(?:https?|wss?)://[^\s'\"<>]+|magnet:\?[^\s'\"<>]+", re.IGNORECASE)


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _sensitive_key(value: Any) -> bool:
    normalized = _normalized_key(value)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_netloc(parsed: Any) -> str:
    hostname = parsed.hostname or ""
    if not hostname:
        return REDACTED
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return REDACTED
    if port is not None:
        host = f"{host}:{port}"
    if parsed.username is not None or parsed.password is not None:
        return f"{REDACTED}@{host}"
    return host


def sanitize_url_for_log(value: Any) -> str:
    """Keep URL structure while removing credentials and query values."""
    raw = str(value or "").strip()
    if not raw:
        return raw
    if raw.lower().startswith("magnet:"):
        return f"magnet:{REDACTED}"

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return REDACTED
    if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
        return raw

    query_parts = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        encoded_key = quote_plus(key)
        query_parts.append(f"{encoded_key}={REDACTED}" if item else f"{encoded_key}=")
    return urlunsplit(
        (
            parsed.scheme,
            _safe_netloc(parsed),
            parsed.path,
            "&".join(query_parts),
            REDACTED if parsed.fragment else "",
        )
    )


def sanitize_download_reference_for_log(value: Any) -> str:
    """Describe a torrent reference without infohash, passkey, tracker, or title."""
    raw = str(value or "").strip()
    if not raw:
        return raw
    if raw.lower().startswith("magnet:"):
        return f"magnet:{REDACTED}"

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return REDACTED
    if parsed.scheme.lower() in {"http", "https"}:
        suffix = ".torrent" if parsed.path.lower().endswith(".torrent") else ""
        return urlunsplit(
            (
                parsed.scheme,
                _safe_netloc(parsed),
                f"/{REDACTED}{suffix}",
                "",
                "",
            )
        )
    return REDACTED


def sanitize_text_for_log(value: Any) -> str:
    """Redact URL-shaped secrets embedded in exception or status text."""
    return _URL_PATTERN.sub(lambda match: sanitize_url_for_log(match.group(0)), str(value or ""))


def redact_mapping_for_log(value: Any, *, _key: Any = None) -> Any:
    """Copy nested log data while replacing values under secret-bearing keys."""
    if _key is not None and _sensitive_key(_key):
        return REDACTED if value not in (None, "", [], {}, ()) else value
    if isinstance(value, Mapping):
        return {
            key: redact_mapping_for_log(item, _key=key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_mapping_for_log(item) for item in value)
    if isinstance(value, str) and value.lower().startswith(("http://", "https://", "ws://", "wss://", "magnet:")):
        return sanitize_url_for_log(value)
    return value
