"""Failure-safe lifecycle primitives for application-owned threads."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)


def log_lifecycle_exception_safely(
    target_logger: Any,
    message: str,
    error: BaseException,
) -> None:
    """Emit a diagnostic without replacing or blocking lifecycle cleanup."""
    try:
        target_logger.error(message, format_exception_for_log(error))
    except BaseException:
        pass


def thread_has_started(thread: threading.Thread) -> bool:
    """Return whether ``thread`` reached native start, including after exit."""
    if getattr(thread, "ident", None) is not None:
        return True
    try:
        return bool(thread.is_alive())
    except BaseException:
        # If the runtime cannot prove pre-native failure, retain ownership.
        return True


def _cleanup_preserving_primary(
    cleanup: Callable[[], object],
    primary_error: BaseException,
    *,
    context: str,
) -> None:
    try:
        cleanup()
    except BaseException as cleanup_error:
        try:
            logger.error(
                "Cleanup lifecycle thread %s non riuscito mentre propaga l'errore primario:\n%s",
                context,
                format_exception_for_log(cleanup_error),
            )
        except BaseException:
            pass
    _ = primary_error


def start_owned_thread(
    thread: threading.Thread,
    *,
    rollback_unstarted: Callable[[], object] | None = None,
    context: str = "worker",
) -> None:
    """Start a published thread and roll it back only before native start.

    ``Thread.start`` may raise after the native worker exists. In that ambiguous
    case ownership must remain published so normal completion or shutdown can
    still reach it. Cleanup failures never replace the start failure.
    """
    try:
        thread.start()
    except BaseException as primary_error:
        if not thread_has_started(thread) and rollback_unstarted is not None:
            _cleanup_preserving_primary(
                rollback_unstarted,
                primary_error,
                context=context,
            )
        raise


def start_owned_thread_confirmed(
    thread: threading.Thread,
    *,
    rollback_unstarted: Callable[[], object] | None = None,
    context: str = "worker",
) -> None:
    """Treat an ordinary post-native start error as a successful hand-off."""
    try:
        start_owned_thread(
            thread,
            rollback_unstarted=rollback_unstarted,
            context=context,
        )
    except Exception as start_error:
        if thread_has_started(thread):
            log_lifecycle_exception_safely(
                logger,
                f"Thread {context} avviato nonostante un errore restituito da start(): %s",
                start_error,
            )
            return
        raise


def join_owned_thread(
    thread: threading.Thread | None,
    timeout_seconds: float | None = None,
) -> bool:
    """Join a thread only when native start made it joinable."""
    if thread is None or thread is threading.current_thread():
        return True
    if not thread_has_started(thread):
        return True
    thread.join(timeout=timeout_seconds)
    return not thread.is_alive()


def stop_and_join_after_start_failure(
    thread: threading.Thread,
    stop: Callable[[], object],
    primary_error: BaseException,
    *,
    timeout_seconds: float | None = None,
    context: str = "worker",
) -> None:
    """Reclaim a possibly native-started thread without masking its failure."""
    _cleanup_preserving_primary(stop, primary_error, context=f"{context} stop")
    if not thread_has_started(thread):
        return
    _cleanup_preserving_primary(
        lambda: join_owned_thread(thread, timeout_seconds),
        primary_error,
        context=f"{context} join",
    )


__all__ = [
    "join_owned_thread",
    "log_lifecycle_exception_safely",
    "start_owned_thread",
    "start_owned_thread_confirmed",
    "stop_and_join_after_start_failure",
    "thread_has_started",
]
