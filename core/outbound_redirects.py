"""Shared policy for credential-bearing outbound HTTP requests."""

from __future__ import annotations

from typing import Any


REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


def response_is_redirect(response: Any) -> bool:
    """Check redirect status without inspecting an untrusted Location value."""
    return int(getattr(response, "status_code", 0) or 0) in REDIRECT_STATUS_CODES
