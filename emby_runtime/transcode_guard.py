"""Transcode Guard policy and runtime service helpers."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_runtime.transcode_guard_adapters import (
    _default_fetch_sessions,
    _default_load_config,
    _default_operation_tracker_provider,
    _default_pause_session,
    _default_send_message,
    _default_stop_session,
    _default_storage_provider,
)
from emby_runtime.transcode_guard_constants import (  # noqa: F401 - public facade
    PLUGIN_PLAYBACK_SOURCE_ALIASES,
    PROXY_PLAYBACK_SOURCE_ALIASES,
    TRANSCODE_GUARD_ACTION_LABELS,
    TRANSCODE_GUARD_EVENTS_KEY,
    TRANSCODE_GUARD_EXIT_SETTLE_SECONDS,
    TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY,
    TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT,
    TRANSCODE_GUARD_SETTINGS_KEY,
    TRANSCODE_GUARD_STATE_KEY,
    TRANSCODE_GUARD_STREAM_LOG_KEY,
    TRANSCODE_GUARD_STREAM_LOG_LIMIT,
    TRANSCODE_GUARD_STREAM_STATUS_LIMIT,
)
from emby_runtime.transcode_guard_control import (
    TranscodeGuardControlMixin,
    TranscodeGuardLifecycleError as TranscodeGuardLifecycleError,
)
from emby_runtime.transcode_guard_enforcement import TranscodeGuardEnforcementMixin
from emby_runtime.transcode_guard_history import TranscodeGuardHistoryMixin
from emby_runtime.transcode_guard_rules import (  # noqa: F401 - public facade
    DEFAULT_TRANSCODE_GUARD_SETTINGS,
    TRANSCODE_GUARD_MODES as TRANSCODE_GUARD_MODES,
    classify_stream,
    normalize_transcode_guard_settings,
)
from emby_runtime.transcode_guard_scan import TranscodeGuardScanMixin
from emby_runtime.transcode_guard_streams import _terminal_row_has_open_problem as _terminal_row_has_open_problem

class TranscodeGuardService(
    TranscodeGuardControlMixin,
    TranscodeGuardScanMixin,
    TranscodeGuardEnforcementMixin,
    TranscodeGuardHistoryMixin,
):
    """Monitor Emby sessions and enforce configurable Transcode Guard policy."""

    def __init__(
        self,
        *,
        storage_provider: Optional[Callable[[], Any]] = None,
        load_config: Optional[Callable[[], Tuple[Dict[str, Any], bool]]] = None,
        fetch_sessions: Optional[Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[Any]]]] = None,
        send_message: Optional[Callable[[Dict[str, Any], str, str, str, int], Tuple[bool, Any]]] = None,
        pause_session: Optional[Callable[[Dict[str, Any], str], Tuple[bool, Any]]] = None,
        stop_session: Optional[Callable[[Dict[str, Any], str], Tuple[bool, Any]]] = None,
        operation_tracker_provider: Optional[Callable[[], Any]] = None,
        now: Optional[Callable[[], float]] = None,
    ):
        self._storage_provider = storage_provider or _default_storage_provider
        self._load_config = load_config or _default_load_config
        self._fetch_sessions = fetch_sessions or _default_fetch_sessions
        self._send_message = send_message or _default_send_message
        self._pause_session = pause_session or _default_pause_session
        self._stop_session = stop_session or _default_stop_session
        self._operation_tracker_provider = operation_tracker_provider or _default_operation_tracker_provider
        self._now = now or time.time
        self._lock = threading.RLock()
        self._violations: Dict[str, Dict[str, Any]] = {}
        self._server_generations: Dict[str, int] = {}
        self._forgotten_servers: set[str] = set()
        self._recent_events: List[Dict[str, Any]] = []
        self._last_result: Dict[str, Any] = {
            "checked": 0,
            "violations": 0,
            "warned": 0,
            "paused": 0,
            "stopped": 0,
            "errors": [],
        }
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._accepting_starts = True

_TRANSCODE_GUARD_SERVICE: Optional[TranscodeGuardService] = None

def get_transcode_guard_service() -> TranscodeGuardService:
    global _TRANSCODE_GUARD_SERVICE
    if _TRANSCODE_GUARD_SERVICE is None:
        _TRANSCODE_GUARD_SERVICE = TranscodeGuardService()
    return _TRANSCODE_GUARD_SERVICE
