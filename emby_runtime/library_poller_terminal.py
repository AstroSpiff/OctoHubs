"""Terminal state transitions for Emby library polling."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any


TERMINAL_LIBRARY_STATES = {"idle", "completed", "error", "timeout", "interrupted"}
RESTART_INTERRUPTION_MESSAGE = "Scan interrotto dal riavvio di OctoHubs"


@dataclass(frozen=True)
class TerminalLibraryUpdate:
    state_key: str
    server_id: str
    library_id: str
    tracker_status: str
    progress: float
    message: str
    metadata: dict[str, Any]


def polling_failure_update(
    state_key: str,
    state: dict[str, Any],
    message: str,
    now: datetime,
) -> TerminalLibraryUpdate | None:
    """Mark a non-terminal library as failed because its server poller stopped."""
    if state.get("state") in TERMINAL_LIBRARY_STATES:
        return None
    return _apply_terminal_update(
        state_key,
        state,
        internal_state="error",
        tracker_status="error",
        progress=_progress(state),
        message=message,
        now=now,
    )


def missing_target_update(
    state_key: str,
    state: dict[str, Any],
    *,
    now: datetime,
    progress_detection_timeout: float,
    max_scan_duration: float,
) -> TerminalLibraryUpdate | None:
    """Return a terminal update when an expected folder remains absent too long."""
    if state.get("state") in TERMINAL_LIBRARY_STATES:
        return None

    requested_at = state.get("scan_requested_at")
    if not isinstance(requested_at, datetime):
        return None

    if not state.get("ever_seen_progress"):
        elapsed = (now - requested_at).total_seconds()
        if elapsed <= progress_detection_timeout:
            return None
        return _apply_terminal_update(
            state_key,
            state,
            internal_state="timeout",
            tracker_status="completed",
            progress=1.0,
            message=f"RefreshProgress never appeared after {elapsed:.1f}s",
            now=now,
        )

    started_at = state.get("started_at") or state.get("first_progress_seen_at") or requested_at
    if not isinstance(started_at, datetime):
        return None
    elapsed = (now - started_at).total_seconds()
    if elapsed <= max_scan_duration:
        return None
    return _apply_terminal_update(
        state_key,
        state,
        internal_state="error",
        tracker_status="error",
        progress=_progress(state),
        message=f"Scan error after {elapsed:.1f}s",
        now=now,
    )


def _apply_terminal_update(
    state_key: str,
    state: dict[str, Any],
    *,
    internal_state: str,
    tracker_status: str,
    progress: float,
    message: str,
    now: datetime,
) -> TerminalLibraryUpdate:
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    metadata["state"] = internal_state
    metadata["scan_stage"] = state.get("scan_stage", "file")
    state.update(
        {
            "state": internal_state,
            "progress": progress,
            "last_seen_at": now,
            "completed_at": now,
            "next_poll_time": None,
            "progress_source": "poller",
            "metadata": metadata,
        }
    )
    return TerminalLibraryUpdate(
        state_key=state_key,
        server_id=str(state.get("server_id") or ""),
        library_id=str(state.get("library_id") or ""),
        tracker_status=tracker_status,
        progress=progress,
        message=message,
        metadata=copy.deepcopy(metadata),
    )


def _progress(state: dict[str, Any]) -> float:
    try:
        return min(max(float(state.get("progress") or 0.0), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def interrupt_persisted_state(
    persisted: Any,
    now: datetime,
) -> tuple[Any, bool]:
    """Terminalize one orphaned persisted scan without rebuilding runtime tasks."""
    if not isinstance(persisted, dict) or persisted.get("state") not in {"running", "waiting"}:
        return copy.deepcopy(persisted), False

    updated = copy.deepcopy(persisted)
    metadata = updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {}
    metadata.update(
        {
            "state": "interrupted",
            "scan_stage": updated.get("scan_stage", "file"),
            "interruption_reason": "application_restart",
            "interruption_message": RESTART_INTERRUPTION_MESSAGE,
        }
    )
    timestamp = now.isoformat()
    updated.update(
        {
            "state": "interrupted",
            "last_seen_at": timestamp,
            "completed_at": timestamp,
            "next_poll_time": None,
            "progress_source": "application_restart",
            "status_message": RESTART_INTERRUPTION_MESSAGE,
            "metadata": metadata,
        }
    )
    return updated, True
