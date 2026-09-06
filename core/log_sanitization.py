"""Focused redaction helpers for diagnostic logs."""

from __future__ import annotations

import logging
import re
import threading
import traceback
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
_URL_PATTERN = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://[^\s'\"<>]+|magnet:\?[^\s'\"<>]+)",
    re.IGNORECASE,
)
_TELEGRAM_BOT_PATH_PATTERN = re.compile(r"(?i)(/bot)[^/]+")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|cookie|credential|password|passwd|secret|token)"
    r"\b[\"']?\s*[:=]\s*)([\"']?)([^\"'\s,;}\]]+)([\"']?)"
)
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
_LOG_FACTORY_LOCK = threading.Lock()


class TrustedDiagnosticText(str):
    """Already-redacted diagnostic text whose traceback layout is intentional."""


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
    if not parsed.scheme or not parsed.netloc:
        return raw

    query_parts = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        encoded_key = quote_plus(key)
        query_parts.append(f"{encoded_key}={REDACTED}" if item else f"{encoded_key}=")
    return urlunsplit(
        (
            parsed.scheme,
            _safe_netloc(parsed),
            _TELEGRAM_BOT_PATH_PATTERN.sub(r"\1[REDACTED]", parsed.path),
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
    """Redact URL-shaped and key/value secrets in diagnostic text."""
    sanitized = _URL_PATTERN.sub(
        lambda match: sanitize_url_for_log(match.group(0)),
        str(value or ""),
    )
    return _SENSITIVE_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}{match.group(4)}",
        sanitized,
    )


def sanitize_diagnostic_text(value: Any, *, max_length: int = 240) -> str:
    """Return a single-line, redacted and bounded diagnostic label."""
    sanitized = sanitize_text_for_log(value)
    sanitized = _CONTROL_CHARACTER_PATTERN.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split())
    limit = max(1, int(max_length))
    if len(sanitized) <= limit:
        return sanitized
    return f"{sanitized[: max(1, limit - 1)]}…"


def format_exception_for_log(error: BaseException) -> str:
    """Keep trusted traceback structure while neutralizing exception values."""
    rendered: list[str] = []
    seen: set[int] = set()

    def append_exception(current: BaseException) -> None:
        identity = id(current)
        if identity in seen:
            return
        seen.add(identity)
        if current.__cause__ is not None:
            append_exception(current.__cause__)
            rendered.append("\nThe above exception was the direct cause of the following exception:\n\n")
        elif current.__context__ is not None and not current.__suppress_context__:
            append_exception(current.__context__)
            rendered.append("\nDuring handling of the above exception, another exception occurred:\n\n")
        if current.__traceback__ is not None:
            rendered.append("Traceback (most recent call last):\n")
        rendered.extend(traceback.format_tb(current.__traceback__))
        type_name = f"{type(current).__module__}.{type(current).__qualname__}"
        rendered.append(
            f"{type_name}: {sanitize_diagnostic_text(current, max_length=2000)}\n"
        )

    append_exception(error)
    return TrustedDiagnosticText(sanitize_text_for_log("".join(rendered)).rstrip())


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
    if isinstance(value, str):
        return sanitize_text_for_log(value)
    return value


def sanitize_log_argument(value: Any) -> Any:
    """Neutralize arbitrary logger arguments while preserving useful structure."""
    if isinstance(value, TrustedDiagnosticText):
        return value
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _sensitive_key(key) and item not in (None, "", [], {}, ())
            else sanitize_log_argument(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_log_argument(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_log_argument(item) for item in value)
    if isinstance(value, set):
        return {sanitize_log_argument(item) for item in value}
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) or isinstance(value, BaseException):
        return sanitize_diagnostic_text(value, max_length=2000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_diagnostic_text(value, max_length=2000)


def install_log_record_sanitizer() -> None:
    """Install one process-wide boundary for every standard logging argument."""
    with _LOG_FACTORY_LOCK:
        current_factory = logging.getLogRecordFactory()
        if getattr(current_factory, "_octohubs_sanitizes_arguments", False):
            return

        def sanitized_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = current_factory(*args, **kwargs)
            if isinstance(record.args, Mapping):
                record.args = sanitize_log_argument(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_log_argument(item) for item in record.args)
            if (
                not record.args
                and isinstance(record.msg, str)
                and not isinstance(record.msg, TrustedDiagnosticText)
            ):
                # Interpolated f-strings and direct user-controlled messages do
                # not have separate logging arguments, so guard that boundary
                # as well. Trusted traceback arguments retain their layout.
                record.msg = sanitize_diagnostic_text(record.msg, max_length=4000)
            return record

        sanitized_factory._octohubs_sanitizes_arguments = True  # type: ignore[attr-defined]
        logging.setLogRecordFactory(sanitized_factory)


__all__ = [
    "REDACTED",
    "TrustedDiagnosticText",
    "format_exception_for_log",
    "install_log_record_sanitizer",
    "redact_mapping_for_log",
    "sanitize_diagnostic_text",
    "sanitize_download_reference_for_log",
    "sanitize_log_argument",
    "sanitize_text_for_log",
    "sanitize_url_for_log",
]
