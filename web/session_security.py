"""Session-secret and cookie-security helpers shared by application startup."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping

from core.secret_strength import MIN_SECRET_BYTES, is_strong_secret


_INSECURE_SESSION_SECRETS = frozenset(
    {
        "",
        "change-this-secret-key",
        "your-secret-key-here",
        "cambia_questo",
    }
)
MIN_SESSION_SECRET_BYTES = MIN_SECRET_BYTES


def is_insecure_session_secret(value: object) -> bool:
    """Recognize missing, documented placeholders, and trivially weak secrets."""
    normalized = str(value or "").strip()
    return (
        normalized.lower() in _INSECURE_SESSION_SECRETS
        or not is_strong_secret(normalized)
    )


def resolved_session_secret(
    environment: Mapping[str, str],
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> tuple[str, bool]:
    """Return the configured secret or a safe ephemeral replacement and its origin."""
    configured = str(environment.get("SECRET_KEY") or "").strip()
    if not configured or configured.lower() in _INSECURE_SESSION_SECRETS:
        return token_factory(48), True
    if is_insecure_session_secret(configured):
        raise ValueError(
            f"SECRET_KEY deve contenere almeno {MIN_SESSION_SECRET_BYTES} byte non banali"
        )
    return configured, False


def environment_flag(environment: Mapping[str, str], key: str, default: bool = False) -> bool:
    """Parse an explicit boolean environment variable without surprising truthiness."""
    value = environment.get(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def session_timeout_seconds(environment: Mapping[str, str]) -> int | None:
    """Convert SESSION_TIMEOUT_MINUTES to Starlette's max-age value."""
    raw_value = str(environment.get("SESSION_TIMEOUT_MINUTES", "60")).strip()
    try:
        minutes = int(raw_value)
    except ValueError:
        minutes = 60
    if minutes <= 0:
        return None
    return max(minutes, 1) * 60
