"""Failure-safe SQLAlchemy session cleanup shared by storage mixins."""

from __future__ import annotations

import logging
from typing import Any

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def _try_cleanup(session: Any, operation: str) -> bool:
    cleanup = getattr(session, operation, None)
    if not callable(cleanup):
        return False
    try:
        cleanup()
        return True
    except Exception as exc:
        logger.error(
            "Cleanup sessione storage %s non riuscito:\n%s",
            operation,
            format_exception_for_log(exc),
        )
        return False


def rollback_session_safely(session: Any) -> bool:
    """Best-effort rollback that cannot replace the primary storage error."""
    if _try_cleanup(session, "rollback"):
        return True
    for operation in ("invalidate", "close", "remove"):
        if _try_cleanup(session, operation):
            break
    return False


def close_session_safely(session: Any) -> bool:
    """Return a connection to the pool without leaking a cleanup exception."""
    if _try_cleanup(session, "close"):
        return True
    _try_cleanup(session, "invalidate")
    return False
