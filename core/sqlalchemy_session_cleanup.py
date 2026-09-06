"""Failure-safe cleanup primitives for application-owned SQLAlchemy sessions."""

from __future__ import annotations

import logging
from typing import Any

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def _try_cleanup(session: Any, operation: str, *, context: str) -> bool:
    cleanup = getattr(session, operation, None)
    if not callable(cleanup):
        return False
    try:
        cleanup()
        return True
    except Exception as exc:
        logger.error(
            "Cleanup sessione SQLAlchemy %s (%s) non riuscito:\n%s",
            operation,
            context,
            format_exception_for_log(exc),
        )
        return False


def rollback_session_safely(session: Any, *, context: str = "storage") -> bool:
    """Best-effort rollback that cannot replace an operation's primary error."""
    if _try_cleanup(session, "rollback", context=context):
        return True
    for operation in ("invalidate", "close", "remove"):
        if _try_cleanup(session, operation, context=context):
            break
    return False


def close_session_safely(session: Any, *, context: str = "storage") -> bool:
    """Release a session without propagating a secondary cleanup failure."""
    if _try_cleanup(session, "close", context=context):
        return True
    _try_cleanup(session, "invalidate", context=context)
    return False


def remove_session_registry_safely(registry: Any, *, context: str) -> bool:
    """Remove a scoped session without aborting a wider cleanup sequence."""
    return _try_cleanup(registry, "remove", context=context)


__all__ = [
    "close_session_safely",
    "remove_session_registry_safely",
    "rollback_session_safely",
]
