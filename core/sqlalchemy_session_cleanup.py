"""Failure-safe cleanup primitives for application-owned SQLAlchemy sessions."""

from __future__ import annotations

import logging
import sys
from typing import Any

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def _try_cleanup(
    session: Any,
    operation: str,
    *,
    context: str,
    primary_error: BaseException | None = None,
) -> bool:
    cleanup = getattr(session, operation, None)
    if not callable(cleanup):
        return False
    active_primary = primary_error if primary_error is not None else sys.exception()
    try:
        cleanup()
        return True
    except BaseException as exc:
        # Process-control exceptions must retain their normal semantics when
        # cleanup is the operation being performed.  When cleanup runs while
        # another exception is already propagating, however, even a
        # BaseException raised by the driver is secondary and must not replace
        # the original failure.
        if active_primary is None and not isinstance(exc, Exception):
            raise
        logger.error(
            "Cleanup sessione SQLAlchemy %s (%s) non riuscito:\n%s",
            operation,
            context,
            format_exception_for_log(exc),
        )
        return False


def rollback_session_safely(
    session: Any,
    *,
    context: str = "storage",
    primary_error: BaseException | None = None,
) -> bool:
    """Best-effort rollback that cannot replace an operation's primary error."""
    if _try_cleanup(
        session,
        "rollback",
        context=context,
        primary_error=primary_error,
    ):
        return True
    for operation in ("invalidate", "close", "remove"):
        if _try_cleanup(
            session,
            operation,
            context=context,
            primary_error=primary_error,
        ):
            break
    return False


def close_session_safely(
    session: Any,
    *,
    context: str = "storage",
    primary_error: BaseException | None = None,
) -> bool:
    """Release a session without propagating a secondary cleanup failure."""
    if _try_cleanup(
        session,
        "close",
        context=context,
        primary_error=primary_error,
    ):
        return True
    _try_cleanup(
        session,
        "invalidate",
        context=context,
        primary_error=primary_error,
    )
    return False


def invalidate_session_safely(
    session: Any,
    *,
    context: str = "storage",
    primary_error: BaseException | None = None,
) -> bool:
    """Discard a broken session without replacing an active primary error."""
    return _try_cleanup(
        session,
        "invalidate",
        context=context,
        primary_error=primary_error,
    )


def remove_session_registry_safely(
    registry: Any,
    *,
    context: str,
    primary_error: BaseException | None = None,
) -> bool:
    """Remove a scoped session without aborting a wider cleanup sequence."""
    return _try_cleanup(
        registry,
        "remove",
        context=context,
        primary_error=primary_error,
    )


__all__ = [
    "close_session_safely",
    "invalidate_session_safely",
    "remove_session_registry_safely",
    "rollback_session_safely",
]
