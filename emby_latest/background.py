"""
Background tasks for Latest Publications system.

This module handles background refresh operations with proper DB persistence.
Migrated from app.py lines 4690-4919.

CRITICAL BUG FIXES:
- Bug #1: refresh_full now saves BOTH batch and feed caches to DB
- Bug #2: refresh_incremental now saves state to DB
"""

from typing import Any, Dict, Optional, Tuple
import threading

# Background refresh state
_refresh_lock = threading.Lock()
_refresh_state = {
    "running": False,
    "last_run": None,
    "last_error": None
}


def refresh_full(
    manager,
    limit: int,
    per_server_limit: int,
    fast_mode: bool = False,
    enrich: bool = True,
    force_omdb: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Perform full background refresh (batch + feed modes).

    CRITICAL BUG FIX #1: Saves BOTH batch and feed caches to DB.
    The fix is implemented in collectors.collect_entries().

    Args:
        manager: EmbyLatestManager instance
        limit: Maximum number of results
        per_server_limit: Limit per server
        fast_mode: Faster initial load
        enrich: Enable enrichment
        force_omdb: Force OMDb cache refresh

    Returns:
        Tuple of (payload, error_message)
    """
    with _refresh_lock:
        if _refresh_state["running"]:
            return None, "Refresh already running"
        _refresh_state["running"] = True
        _refresh_state["last_error"] = None

    try:
        # Delegate to manager which handles the logic
        payload, error = manager.refresh_full(
            limit=limit,
            per_server_limit=per_server_limit,
            fast_mode=fast_mode,
            enrich=enrich,
            force_omdb=force_omdb
        )

        if error:
            _refresh_state["last_error"] = error
        else:
            from datetime import datetime, timezone
            _refresh_state["last_run"] = datetime.now(timezone.utc).isoformat()

        return payload, error

    finally:
        with _refresh_lock:
            _refresh_state["running"] = False


def refresh_incremental(
    manager,
    limit: int,
    per_server_limit: int,
    enrich: bool = True,
    force_omdb: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Perform incremental background refresh (enrich missing data only).

    CRITICAL BUG FIX #2: Saves state to DB.
    The fix is implemented in collectors.collect_entries().

    Args:
        manager: EmbyLatestManager instance
        limit: Maximum number of results
        per_server_limit: Limit per server
        enrich: Enable enrichment
        force_omdb: Force OMDb cache refresh

    Returns:
        Tuple of (payload, error_message)
    """
    with _refresh_lock:
        if _refresh_state["running"]:
            return None, "Refresh already running"
        _refresh_state["running"] = True
        _refresh_state["last_error"] = None

    try:
        # Delegate to manager
        payload, error = manager.refresh_incremental(
            limit=limit,
            per_server_limit=per_server_limit,
            enrich=enrich,
            force_omdb=force_omdb
        )

        if error:
            _refresh_state["last_error"] = error
        else:
            from datetime import datetime, timezone
            _refresh_state["last_run"] = datetime.now(timezone.utc).isoformat()

        return payload, error

    finally:
        with _refresh_lock:
            _refresh_state["running"] = False


def get_refresh_state() -> Dict[str, Any]:
    """
    Get current background refresh state.

    Returns:
        Dict with keys: running, last_run, last_error
    """
    with _refresh_lock:
        return dict(_refresh_state)
