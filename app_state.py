"""
Shared application state and singletons.
Extracted from the legacy monolith to reduce module size.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import threading
from typing import Optional

from core.storage import StorageError
from core.config_manager import _ensure_db_backend, load_config
from core import config_manager
from core.utils import json_error, json_success
from emby_libraries.client import EmbyApiClient
from emby_libraries.manager import EmbyLibrariesManager
from emby_libraries.scan_manager import EmbyLibraryScanManager
from emby_libraries.tracker import LibraryScanTracker
from emby_runtime.api_clients import _trigger_library_scan as _api_trigger_library_scan
from emby_users.registry import get_emby_user_manager as _get_emby_user_manager


_APP_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


def register_app_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _APP_EVENT_LOOP
    _APP_EVENT_LOOP = loop


def get_app_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _APP_EVENT_LOOP


def _default_get_loop():
    return get_app_event_loop()


def _default_log_flush(msg: str) -> None:
    print(msg, flush=True)


_APP_EVENT_LOOP_GETTER = _default_get_loop
_LOG_FLUSH = _default_log_flush


def _get_app_event_loop():
    return _APP_EVENT_LOOP_GETTER()


def _log_flush(msg: str) -> None:
    _LOG_FLUSH(msg)


def init_state(get_app_event_loop, log_flush) -> None:
    """Initialize state with app loop/log handlers."""
    global _APP_EVENT_LOOP_GETTER, _LOG_FLUSH
    _APP_EVENT_LOOP_GETTER = get_app_event_loop
    _LOG_FLUSH = log_flush


_LIBRARY_SCAN_TRACKER: LibraryScanTracker = LibraryScanTracker(_get_app_event_loop, _log_flush)

# Jellyseerr refresh state (for displaying warnings in UI and status polling)
_JELLYSEERR_REFRESH_STATE: dict = {
    "running": False,
    "last_status": None,       # "success" | "error" | "skipped"
    "last_warning": None,
    "last_warning_at": None,
    "last_error": None,
    "completed_at": None,
    "counts": None,
}


def get_jellyseerr_refresh_state() -> dict:
    """Return the current request-refresh state for operational views."""
    return {
        "running": bool(_JELLYSEERR_REFRESH_STATE.get("running")),
        "last_status": _JELLYSEERR_REFRESH_STATE.get("last_status"),
        "last_warning": _JELLYSEERR_REFRESH_STATE.get("last_warning"),
        "last_warning_at": _JELLYSEERR_REFRESH_STATE.get("last_warning_at"),
        "last_error": _JELLYSEERR_REFRESH_STATE.get("last_error"),
        "completed_at": _JELLYSEERR_REFRESH_STATE.get("completed_at"),
    }


# Latest result of the shared integrations check. It is intentionally ephemeral:
# credentials and health details stay in the running application only.
_CONNECTION_CHECK_STATE: dict = {
    "checked_at": None,
    "statuses": {},
}


def set_connection_check_state(statuses: dict | None, checked_at: str | None) -> None:
    """Store the most recent integrations check for the configuration views."""
    _CONNECTION_CHECK_STATE["checked_at"] = checked_at
    _CONNECTION_CHECK_STATE["statuses"] = deepcopy(statuses or {})


def get_connection_check_state() -> dict:
    """Return a copy so callers cannot mutate shared health state."""
    return {
        "checked_at": _CONNECTION_CHECK_STATE.get("checked_at"),
        "statuses": deepcopy(_CONNECTION_CHECK_STATE.get("statuses") or {}),
    }

_EMBY_LIBRARIES_MANAGER = None
_EMBY_LIBRARY_SCAN_MANAGER = None
_OPERATION_TRACKER = None
_OPERATION_TRACKER_RECOVERED = False
_OPERATION_TRACKER_LOCK = threading.Lock()


def get_emby_user_manager():
    return _get_emby_user_manager(
        _ensure_db_backend,
        lambda: config_manager._DB_BACKEND,
        lambda: config_manager._ACTIVE_CONFIG or {},
        get_operation_tracker,
    )


def get_operation_tracker():
    """Return the global persistent operation tracker."""
    global _OPERATION_TRACKER, _OPERATION_TRACKER_RECOVERED
    with _OPERATION_TRACKER_LOCK:
        if _OPERATION_TRACKER is None:
            from core.operations import OperationTracker

            _OPERATION_TRACKER = OperationTracker(_ensure_db_backend())
        if not _OPERATION_TRACKER_RECOVERED:
            _OPERATION_TRACKER_RECOVERED = True
            try:
                interrupted = _OPERATION_TRACKER.interrupt_active("Interrotta da riavvio OctoHubs")
                if interrupted:
                    print(f"[OPERATIONS] {interrupted} operazioni attive marcate come interrotte dopo riavvio.")
            except Exception as exc:
                print(f"[OPERATIONS] Recovery operazioni non riuscita: {exc}")
    return _OPERATION_TRACKER


def get_emby_libraries_manager():
    global _EMBY_LIBRARIES_MANAGER
    if _EMBY_LIBRARIES_MANAGER is None:
        _EMBY_LIBRARIES_MANAGER = EmbyLibrariesManager(
            load_config,
            _ensure_db_backend,
            json_error,
            StorageError,
        )
    return _EMBY_LIBRARIES_MANAGER


def get_emby_library_scan_manager():
    global _EMBY_LIBRARY_SCAN_MANAGER
    if _EMBY_LIBRARY_SCAN_MANAGER is None:
        _EMBY_LIBRARY_SCAN_MANAGER = EmbyLibraryScanManager(
            load_config=load_config,
            json_error=json_error,
            json_success=json_success,
            scan_tracker=_LIBRARY_SCAN_TRACKER,
            trigger_library_scan=_api_trigger_library_scan,
            get_app_event_loop=_get_app_event_loop,
            emby_api_client_cls=EmbyApiClient,
            log_flush=_log_flush,
        )
    return _EMBY_LIBRARY_SCAN_MANAGER
