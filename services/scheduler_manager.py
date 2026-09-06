"""ScanManager and AutoScheduler wiring."""

from __future__ import annotations

import logging
import time

from core import config_manager
from core.config_manager import set_sync_auto_scheduler
from core.log_sanitization import format_exception_for_log
from core.tasks import ScanManager, AutoScheduler
from services.requests_processor import process_requests
from services.request_refresh_snapshot import refresh_request_snapshot
from services.scheduler_occurrences import SchedulerOccurrenceCoordinator
from services.workflows import _wf_trigger_sync

scan_manager = ScanManager()
_AUTO_SCHEDULER: AutoScheduler | None = None
logger = logging.getLogger(__name__)


def _cleanup_unpublished_scheduler(
    candidate: AutoScheduler,
    primary_error: BaseException,
) -> None:
    """Try every candidate cleanup while retaining the wiring failure."""
    cleanup_actions = (
        ("stop", candidate.stop),
        ("wait", lambda: candidate.wait(1.0)),
    )
    for label, cleanup in cleanup_actions:
        try:
            cleanup()
        except BaseException as cleanup_error:
            try:
                logger.error(
                    "Cleanup AutoScheduler non pubblicato (%s) non riuscito:\n%s",
                    label,
                    format_exception_for_log(cleanup_error),
                )
            except BaseException:
                pass
    _ = primary_error


def _ensure_auto_scheduler() -> AutoScheduler:
    global _AUTO_SCHEDULER
    if _AUTO_SCHEDULER is None:
        candidate = AutoScheduler(
            scan_manager_instance=scan_manager,
            occurrence_coordinator=SchedulerOccurrenceCoordinator(
                config_manager._ensure_db_backend,
            ),
        )
        try:
            candidate.set_callbacks(
                process_requests_func=process_requests,
                sync_users_func=_wf_trigger_sync,
                refresh_snapshot_func=refresh_request_snapshot,
            )
        except BaseException as primary_error:
            _cleanup_unpublished_scheduler(candidate, primary_error)
            raise
        _AUTO_SCHEDULER = candidate
    return _AUTO_SCHEDULER


def sync_auto_scheduler(config_ready: bool) -> None:
    scheduler = _ensure_auto_scheduler()
    if config_ready and config_manager._ACTIVE_CONFIG:
        scheduler.update_config(config_manager._ACTIVE_CONFIG)
    else:
        scheduler.update_config(None)


def init_scheduler() -> None:
    scan_manager.start_accepting()
    set_sync_auto_scheduler(sync_auto_scheduler)


def begin_scheduler_shutdown() -> None:
    """Fence scans synchronously before parallel runtime drains begin."""
    scan_manager.begin_shutdown()


def shutdown_scheduler(timeout_seconds: float = 5.0) -> bool:
    """Stop scheduled and active scan workers within one shared deadline."""
    global _AUTO_SCHEDULER

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    scheduler = _AUTO_SCHEDULER
    begin_scheduler_shutdown()
    if scheduler is not None:
        scheduler.stop()

    scheduler_stopped = True
    if scheduler is not None:
        scheduler_stopped = scheduler.wait(max(0.0, deadline - time.monotonic()))
    scan_stopped = scan_manager.wait(max(0.0, deadline - time.monotonic()))

    if scheduler_stopped:
        _AUTO_SCHEDULER = None
    return scheduler_stopped and scan_stopped
