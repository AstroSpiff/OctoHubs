"""ScanManager and AutoScheduler wiring."""

from __future__ import annotations

import time

from core import config_manager
from core.config_manager import set_sync_auto_scheduler
from core.tasks import ScanManager, AutoScheduler
from services.requests_processor import process_requests
from services.request_refresh_snapshot import refresh_request_snapshot
from services.scheduler_occurrences import SchedulerOccurrenceCoordinator
from services.workflows import _wf_trigger_sync

scan_manager = ScanManager()
_AUTO_SCHEDULER: AutoScheduler | None = None


def _ensure_auto_scheduler() -> AutoScheduler:
    global _AUTO_SCHEDULER
    if _AUTO_SCHEDULER is None:
        _AUTO_SCHEDULER = AutoScheduler(
            scan_manager_instance=scan_manager,
            occurrence_coordinator=SchedulerOccurrenceCoordinator(
                config_manager._ensure_db_backend,
            ),
        )
        _AUTO_SCHEDULER.set_callbacks(
            process_requests_func=process_requests,
            sync_users_func=_wf_trigger_sync,
            refresh_snapshot_func=refresh_request_snapshot,
        )
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
