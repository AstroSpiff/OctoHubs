"""ScanManager and AutoScheduler wiring."""

from __future__ import annotations

from core import config_manager
from core.config_manager import set_sync_auto_scheduler
from core.tasks import ScanManager, AutoScheduler
from services.requests_cache import _save_cached_requests_overview
from services.requests_summary import _summarize_requests_for_dashboard
from services.requests_processor import process_requests
from services.workflows import _wf_trigger_sync

scan_manager = ScanManager()
_AUTO_SCHEDULER: AutoScheduler | None = None


def _ensure_auto_scheduler() -> AutoScheduler:
    global _AUTO_SCHEDULER
    if _AUTO_SCHEDULER is None:
        _AUTO_SCHEDULER = AutoScheduler(scan_manager_instance=scan_manager)
        _AUTO_SCHEDULER.set_callbacks(
            summarize_func=_summarize_requests_for_dashboard,
            save_overview_func=_save_cached_requests_overview,
            process_requests_func=process_requests,
            sync_users_func=_wf_trigger_sync,
        )
    return _AUTO_SCHEDULER


def sync_auto_scheduler(config_ready: bool) -> None:
    scheduler = _ensure_auto_scheduler()
    if config_ready and config_manager._ACTIVE_CONFIG:
        scheduler.update_config(config_manager._ACTIVE_CONFIG)
    else:
        scheduler.update_config(None)


def init_scheduler() -> None:
    set_sync_auto_scheduler(sync_auto_scheduler)
