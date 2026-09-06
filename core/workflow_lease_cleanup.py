"""Failure-isolated cleanup for workflow leases."""

from __future__ import annotations

import logging
import sys
from typing import Any

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def release_workflow_lease_safely(
    storage: Any,
    lease: Any,
    *,
    context: str,
    primary_error: BaseException | None = None,
    preserve_outcome: bool = False,
) -> bool:
    """Release a lease without replacing an error or established outcome."""
    release = getattr(storage, "release_workflow_lease", None) if storage else None
    if not callable(release):
        return True
    active_primary = primary_error if primary_error is not None else sys.exception()
    try:
        release(lease)
        return True
    except BaseException as exc:
        # Keep process-control signals observable when release itself is the
        # operation. During unwinding, or after the caller has established a
        # boolean/final lifecycle outcome, every release failure is secondary.
        if active_primary is None and not preserve_outcome and not isinstance(exc, Exception):
            raise
        logger.error(
            "Rilascio lease workflow non riuscito (%s):\n%s",
            context,
            format_exception_for_log(exc),
        )
        return False


__all__ = ["release_workflow_lease_safely"]
