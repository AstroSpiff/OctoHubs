"""Operation-center projection for Media Probe background workers."""

from __future__ import annotations

import threading
import time
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from core.thread_lifecycle import log_lifecycle_exception_safely


logger = logging.getLogger(__name__)


def _fail_operation_safely(tracker: Any, operation_id: str, message: str) -> Any:
    try:
        return tracker.fail(operation_id, message)
    except BaseException as exc:
        log_lifecycle_exception_safely(
            logger,
            "Finalizzazione operazione Probe non riuscita: %s",
            exc,
        )
        return None


@dataclass(frozen=True)
class ProbeWorkerOperation:
    """Describes one Probe worker represented in the operation center."""

    key: str
    title: str
    scope: str
    global_key: str | None = None


def start_probe_worker_operation(
    *,
    worker: ProbeWorkerOperation,
    server_ids: Iterable[str],
    summary: str = "",
) -> dict[str, Any]:
    """Track an already-started Probe worker without running it a second time."""

    from app_state import get_operation_tracker
    from emby_probe import get_probe_manager

    normalized_server_ids = [str(server_id) for server_id in server_ids if server_id]
    tracker = get_operation_tracker()
    operation = tracker.start(
        f"probe_{worker.key}",
        worker.title,
        summary=summary,
        details={
            "scope": worker.scope,
            "server_ids": normalized_server_ids,
            "worker": worker.key,
            "current_step_label": "Avvio worker",
        },
    )
    operation_id = operation.get("id")
    if not operation_id:
        raise RuntimeError("Impossibile creare l'operazione Media Probe")

    manager = get_probe_manager()
    try:
        manager.start_operation_monitor(
            lambda stop_event: _monitor_probe_worker(
                tracker,
                operation_id,
                manager,
                worker,
                normalized_server_ids,
                stop_event,
            ),
            owner_token=operation_id,
        )
    except BaseException as exc:
        if manager.owns_operation_monitor(operation_id):
            raise
        failed = _fail_operation_safely(
            tracker, operation_id, "Monitor dell'operazione Media Probe non avviato"
        )
        if not isinstance(exc, Exception):
            raise
        return failed or operation
    return operation


def record_probe_command(
    *,
    title: str,
    summary: str,
    success: bool,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an immediate Probe command such as stop or retry."""

    from app_state import get_operation_tracker

    tracker = get_operation_tracker()
    operation = tracker.start(
        "probe_command",
        title,
        summary=summary,
        details=dict(details or {}),
        total=1,
    )
    operation_id = operation.get("id")
    if not operation_id:
        raise RuntimeError("Impossibile creare l'operazione Media Probe")
    result = {"success": success, "message": message}
    if success:
        tracker.finish(operation_id, message, result=result)
    else:
        tracker.fail(operation_id, message, result=result)
    return operation


def _monitor_probe_worker(
    tracker: Any,
    operation_id: str,
    manager: Any,
    worker: ProbeWorkerOperation,
    server_ids: list[str],
    stop_event: threading.Event,
) -> None:
    """Mirror the live worker until its own thread ends."""

    seen_running = False
    startup_deadline = time.monotonic() + 5
    while not stop_event.is_set():
        try:
            running = manager.is_worker_running(
                worker.key,
                server_ids,
                global_key=worker.global_key,
            )
            states = _worker_states(manager, worker.key, server_ids)
            message = _latest_message(states) or "Worker Media Probe in esecuzione"
            if running:
                seen_running = True
                tracker.update(
                    operation_id,
                    message=message,
                    details={"current_step_label": message, "servers": states},
                )
            elif seen_running or any(states.values()):
                _complete_probe_operation(tracker, operation_id, message, states)
                return
            elif time.monotonic() >= startup_deadline:
                tracker.fail(
                    operation_id,
                    "Il worker Media Probe non si e' avviato",
                    result={"servers": states},
                )
                return
            else:
                tracker.update(operation_id, message="Avvio worker Media Probe")
        except BaseException as exc:
            log_lifecycle_exception_safely(
                logger, "Aggiornamento monitor operazione Probe non riuscito: %s", exc
            )
        if stop_event.wait(1):
            return


def _worker_states(manager: Any, worker_key: str, server_ids: list[str]) -> dict[str, dict[str, Any]]:
    return {
        server_id: dict(manager.get_status(server_id).get(worker_key) or {})
        for server_id in server_ids
    }


def _latest_message(states: Mapping[str, Mapping[str, Any]]) -> str:
    for state in states.values():
        message = str(state.get("last_log") or "").strip()
        if message:
            return message
    return ""


def _complete_probe_operation(
    tracker: Any,
    operation_id: str,
    message: str,
    states: Mapping[str, Mapping[str, Any]],
) -> None:
    final_message = message or "Worker Media Probe completato"
    normalized_message = final_message.lower()
    result = {"servers": dict(states)}
    if "errore" in normalized_message:
        tracker.fail(operation_id, final_message, result=result)
    elif "interrot" in normalized_message or "fermat" in normalized_message:
        tracker.skip(operation_id, final_message, result=result)
    else:
        tracker.finish(operation_id, final_message, result=result)
