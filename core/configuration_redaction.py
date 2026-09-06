"""Keep connection settings useful in the UI without exposing credentials."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote_plus, urlsplit, urlunsplit


PUBLIC_REDACTION = "[REDACTED]"
_SENSITIVE_PARAMETER_KEYS = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "auth",
        "authorization",
        "authtoken",
        "bearer",
        "clientsecret",
        "cookie",
        "credential",
        "key",
        "passfile",
        "passkey",
        "passwd",
        "password",
        "privatekey",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "sslpassword",
        "token",
    }
)


def _parameter_key_segments(value: Any) -> tuple[str, ...]:
    decoded = unquote_plus(str(value or "")).strip()
    with_camel_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", decoded)
    return tuple(re.findall(r"[a-z0-9]+", with_camel_boundaries.lower()))


def _sensitive_parameter_key(value: Any) -> bool:
    segments = _parameter_key_segments(value)
    normalized = "".join(segments)
    if normalized in _SENSITIVE_PARAMETER_KEYS:
        return True
    return any(segment in _SENSITIVE_PARAMETER_KEYS for segment in segments)


def _redact_parameter_string(value: str) -> tuple[str, bool]:
    """Redact only credential values while preserving every ordinary pair."""
    redacted_parts: list[str] = []
    changed = False
    for part in value.split("&"):
        key, separator, _item = part.partition("=")
        if separator and _sensitive_parameter_key(key):
            redacted_parts.append(f"{key}={PUBLIC_REDACTION}")
            changed = True
        else:
            redacted_parts.append(part)
    return "&".join(redacted_parts), changed


def public_connection_url(value: Any) -> str:
    """Return a browser-safe URL, leaving normal URL text byte-for-byte intact."""
    raw = str(value or "").strip()
    if not raw:
        return raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return PUBLIC_REDACTION

    query, query_changed = _redact_parameter_string(parsed.query)
    fragment, fragment_changed = _redact_parameter_string(parsed.fragment)
    has_userinfo = parsed.username is not None or parsed.password is not None
    if not has_userinfo and not query_changed and not fragment_changed:
        return raw

    netloc = parsed.netloc.rsplit("@", 1)[-1] if has_userinfo else parsed.netloc
    if has_userinfo:
        netloc = f"{PUBLIC_REDACTION}@{netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))


def connection_url_has_credentials(value: Any) -> bool:
    """Return whether a URL embeds userinfo or a credential-shaped parameter."""
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return True
    _query, query_changed = _redact_parameter_string(parsed.query)
    _fragment, fragment_changed = _redact_parameter_string(parsed.fragment)
    return bool(
        parsed.username is not None
        or parsed.password is not None
        or query_changed
        or fragment_changed
    )


def submitted_connection_url(value: Any, fallback: Any = "") -> str:
    """Reject new embedded credentials but retain an existing redacted setting."""
    submitted = str(value or "").strip()
    existing = str(fallback or "").strip()
    if (
        existing
        and connection_url_has_credentials(existing)
        and submitted == public_connection_url(existing)
    ):
        return existing
    try:
        urlsplit(submitted)
    except ValueError as exc:
        raise ValueError("URL non valido") from exc
    if connection_url_has_credentials(submitted):
        raise ValueError("Inserisci le credenziali nel campo dedicato, non nell'URL")
    return submitted


def public_database_parameters(value: Any) -> str:
    """Return libpq/SQLAlchemy parameters with only credential values redacted."""
    raw = str(value or "").strip()
    return _redact_parameter_string(raw)[0]


__all__ = [
    "PUBLIC_REDACTION",
    "connection_url_has_credentials",
    "public_connection_url",
    "public_database_parameters",
    "submitted_connection_url",
]
