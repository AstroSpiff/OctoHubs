"""Bounded, safe change journal for external OctoHubs API clients.

The browser keeps its own SSE/WebSocket transport. External clients instead
poll this tiny journal and then reread the canonical v1 endpoint for the topic
that changed. That keeps one source of truth for data and avoids exporting raw
Emby/Event Bridge messages to third parties.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any


EXTERNAL_CHANGE_RETENTION = 250

_changes: deque[dict[str, Any]] = deque(maxlen=EXTERNAL_CHANGE_RETENTION)
_changes_lock = Lock()
_latest_cursor = 0

_TOPICS_BY_MESSAGE_TYPE = {
    "ConnectionClosed": "emby.connection",
    "ConnectionEstablished": "emby.connection",
    "LibraryChanged": "libraries",
    "OctoHubsCollectionsUpdated": "collections",
    "OctoHubsConfigurationUpdated": "configuration",
    "OctoHubsEventBridgeUpdated": "event_bridge",
    "OctoHubsLatestUpdated": "publications",
    "OctoHubsUsersUpdated": "users",
    "RefreshProgress": "libraries.scan",
    "ScheduledTasksInfoStart": "libraries.scan",
    "ScheduledTasksInfoStop": "libraries.scan",
    "Sessions": "emby.streams",
    "SessionsUpdate": "emby.streams",
    "UserPolicyUpdated": "users",
}


def _topic_for_message(message_type: str) -> str:
    return _TOPICS_BY_MESSAGE_TYPE.get(message_type, "application")


def _safe_details(message_type: str, data: Any) -> dict[str, str]:
    """Keep only routing metadata that lets a client choose a v1 refresh."""
    if not isinstance(data, dict):
        return {}

    details: dict[str, str] = {}
    if message_type == "OctoHubsConfigurationUpdated":
        scope = str(data.get("scope") or "").strip()
        if scope:
            details["scope"] = scope
    return details


def publish_external_change(event_data: dict[str, Any]) -> None:
    """Record one safe invalidation event from the shared realtime emitter."""
    global _latest_cursor

    message_type = str(event_data.get("MessageType") or "ApplicationUpdated").strip()
    if not message_type:
        message_type = "ApplicationUpdated"
    server_id = str(event_data.get("server_id") or "").strip() or None
    data = event_data.get("Data")

    with _changes_lock:
        _latest_cursor += 1
        _changes.append(
            {
                "cursor": _latest_cursor,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "topic": _topic_for_message(message_type),
                "message_type": message_type,
                "server_id": server_id,
                "details": _safe_details(message_type, data),
            }
        )


def read_external_changes(*, after: int, limit: int) -> dict[str, Any]:
    """Return a bounded page of safe changes after a client cursor."""
    requested_after = max(0, int(after))
    requested_limit = max(1, min(int(limit), EXTERNAL_CHANGE_RETENTION))

    with _changes_lock:
        latest_cursor = _latest_cursor
        oldest_cursor = _changes[0]["cursor"] if _changes else latest_cursor + 1
        reset_required = requested_after > latest_cursor or (
            bool(_changes) and requested_after < oldest_cursor - 1
        )
        effective_after = oldest_cursor - 1 if reset_required else requested_after
        matching = [event.copy() for event in _changes if event["cursor"] > effective_after]
        events = matching[:requested_limit]
        next_cursor = events[-1]["cursor"] if events else effective_after

    return {
        "events": events,
        "next_cursor": next_cursor,
        "latest_cursor": latest_cursor,
        "oldest_cursor": oldest_cursor,
        "has_more": len(matching) > len(events),
        "reset_required": reset_required,
        "retention": EXTERNAL_CHANGE_RETENTION,
    }


def reset_external_change_feed_for_tests() -> None:
    """Reset process-local state for deterministic unit tests."""
    global _latest_cursor
    with _changes_lock:
        _changes.clear()
        _latest_cursor = 0
