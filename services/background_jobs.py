"""Small helpers for operation-center backed background jobs."""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Dict, Optional


class BackgroundJobContext:
    """Tiny adapter around OperationTracker for worker functions."""

    def __init__(self, tracker: Any, operation_id: str):
        self.tracker = tracker
        self.operation_id = operation_id

    def update(self, **kwargs) -> None:
        if not self.tracker or not self.operation_id:
            return
        self.tracker.update(self.operation_id, **kwargs)


def start_tracked_background_job(
    *,
    kind: str,
    title: str,
    summary: str = "",
    details: Optional[Dict[str, Any]] = None,
    total: Optional[int] = None,
    work: Callable[[BackgroundJobContext], Dict[str, Any]],
    success_message: str = "Operazione completata",
) -> Dict[str, Any]:
    """Start a daemon thread and mirror its lifecycle into the global operation center."""

    from app_state import get_operation_tracker

    tracker = get_operation_tracker()
    operation = tracker.start(kind, title, summary=summary, details=details or {}, total=total)
    operation_id = operation.get("id")
    if not operation_id:
        raise RuntimeError("Impossibile creare operazione")

    def _run() -> None:
        context = BackgroundJobContext(tracker, operation_id)
        try:
            context.update(message="Operazione avviata", progress=5)
            result = work(context) or {}
            tracker.finish(operation_id, success_message, result=result)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            traceback.print_exc()
            tracker.fail(operation_id, str(exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return operation
