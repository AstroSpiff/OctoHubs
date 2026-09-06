"""Default adapters used by the Transcode Guard service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_emby_servers_from_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from core.utils import get_emby_servers

        return list(get_emby_servers(config) or [])
    except Exception:
        servers = ((config or {}).get("EMBY") or {}).get("SERVERS") or []
        return list(servers) if isinstance(servers, list) else []


def _default_storage_provider():
    from core.config_manager import _ensure_db_backend

    return _ensure_db_backend()


def _default_load_config():
    from core.config_manager import load_config

    return load_config()


def _default_fetch_sessions(server: Dict[str, Any]):
    from emby_runtime.api_clients import _fetch_emby_active_sessions
    from emby_runtime.streams import get_streams_manager

    return get_streams_manager().refresh_server(
        server,
        _fetch_emby_active_sessions,
        max_age_seconds=1,
    )


def _default_send_message(server: Dict[str, Any], session_id: str, header: str, text: str, timeout_ms: Optional[int]):
    from emby_runtime.api_clients import _send_emby_session_message

    return _send_emby_session_message(server, session_id, header, text, timeout_ms)


def _default_stop_session(server: Dict[str, Any], session_id: str):
    from emby_runtime.api_clients import _stop_emby_playback_session

    return _stop_emby_playback_session(server, session_id)


def _default_pause_session(server: Dict[str, Any], session_id: str):
    from emby_runtime.api_clients import _pause_emby_playback_session

    return _pause_emby_playback_session(server, session_id)


def _default_operation_tracker_provider():
    from app_state import get_operation_tracker

    return get_operation_tracker()
