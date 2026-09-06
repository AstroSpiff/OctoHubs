"""Small helpers for operation-center backed background jobs."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from services.background_job_registry import background_job_registry
from core.thread_lifecycle import log_lifecycle_exception_safely


logger = logging.getLogger(__name__)
_GENERIC_FAILURE_MESSAGE = "Operazione non completata. Verifica i log dell'applicazione."


def _fail_operation_safely(tracker: Any, operation_id: str, *, context: str) -> None:
    try:
        tracker.fail(operation_id, _GENERIC_FAILURE_MESSAGE)
    except BaseException as cleanup_error:
        log_lifecycle_exception_safely(logger, f"{context}:\n%s", cleanup_error)


def _require_complete_result(result: Dict[str, Any]) -> None:
    """Reject application-level failures before marking a background job green."""
    status = str(result.get("status") or "").strip().lower()
    if result.get("success") is False or status in {"error", "partial", "failed"}:
        raise RuntimeError(str(result.get("message") or _GENERIC_FAILURE_MESSAGE))


class BackgroundJobContext:
    """Tiny adapter around OperationTracker for worker functions."""

    def __init__(self, tracker: Any, operation_id: str, stop_event) -> None:
        self.tracker = tracker
        self.operation_id = operation_id
        self.stop_event = stop_event

    def update(self, **kwargs) -> None:
        if not self.tracker or not self.operation_id:
            return
        self.tracker.update(self.operation_id, **kwargs)

    def raise_if_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise RuntimeError("Operazione interrotta durante lo shutdown")


def start_tracked_background_job(
    *,
    kind: str,
    title: str,
    summary: str = "",
    details: Optional[Dict[str, Any]] = None,
    total: Optional[int] = None,
    work: Callable[[BackgroundJobContext], Dict[str, Any]],
    success_message: str = "Operazione completata",
    singleflight_key: str | None = None,
) -> Dict[str, Any]:
    """Start a lifecycle-owned thread and mirror it into the operation center."""

    from app_state import get_operation_tracker

    tracker = get_operation_tracker()
    operation: Dict[str, Any] = {}

    def _run(stop_event) -> None:
        operation_id = str(operation.get("id") or "")
        context = BackgroundJobContext(tracker, operation_id, stop_event)
        try:
            context.raise_if_cancelled()
            context.update(message="Operazione avviata", progress=5)
            result = work(context) or {}
            context.raise_if_cancelled()
            _require_complete_result(result)
            tracker.finish(operation_id, success_message, result=result)
        except BaseException as exc:  # pragma: no cover - defensive worker boundary
            log_lifecycle_exception_safely(
                logger,
                "Job background non completato:\n%s",
                exc,
            )
            _fail_operation_safely(
                tracker,
                operation_id,
                context="Terminalizzazione job fallita",
            )
            if not isinstance(exc, Exception):
                raise

    def _create_operation() -> Dict[str, Any]:
        created = tracker.start(kind, title, summary=summary, details=details or {}, total=total)
        if not created.get("id"):
            raise RuntimeError("Impossibile creare operazione")
        operation.update(created)
        return operation

    try:
        registered, _started = background_job_registry.start(
            singleflight_key,
            _create_operation,
            _run,
        )
    except BaseException:
        operation_id = str(operation.get("id") or "")
        if operation_id and not background_job_registry.owns_operation(operation):
            _fail_operation_safely(
                tracker,
                operation_id,
                context="Terminalizzazione job non avviato fallita",
            )
        raise
    return registered


def shutdown_background_jobs(timeout_seconds: float = 5.0) -> bool:
    return background_job_registry.shutdown(timeout_seconds)


def initialize_background_jobs() -> None:
    """Prepare the shared registry for a new application lifespan."""
    background_job_registry.initialize()
