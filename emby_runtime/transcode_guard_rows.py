"""Persistence-row normalization for Transcode Guard."""

from __future__ import annotations

from typing import Any, Dict, List

from emby_runtime.event_bridge_limits import bounded_event_bridge_text
from emby_runtime.transcode_guard_adapters import _utc_timestamp
from emby_runtime.transcode_guard_constants import (
    PLUGIN_PLAYBACK_SOURCE_ALIASES,
    PROXY_PLAYBACK_SOURCE_ALIASES,
)
from emby_runtime.transcode_guard_events import _make_event_id
from emby_runtime.transcode_guard_streams import (
    _action_label,
    _normalize_reason_list,
    _to_int,
    _unique_ordered,
)

def _normalize_event_rows(raw: Any) -> List[Dict[str, Any]]:
    source = raw.get("rows") if isinstance(raw, dict) else raw
    if not isinstance(source, list):
        return []
    rows = []
    for item in source:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        actions = row.get("actions")
        if not isinstance(actions, list) or not actions:
            action = str(row.get("action") or "event")
            actions = [{
                "action": action,
                "outcome": row.get("outcome") or "",
                "success": bool(row.get("success", True)),
                "at": row.get("at") or row.get("started_at") or _utc_timestamp(),
            }]
        normalized_actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            normalized_actions.append({
                "action": str(action.get("action") or "event"),
                "outcome": str(action.get("outcome") or ""),
                "success": bool(action.get("success", True)),
                "at": str(action.get("at") or row.get("updated_at") or row.get("at") or _utc_timestamp()),
                "source": str(action.get("source") or "guard"),
            })
        if not normalized_actions:
            continue
        row["actions"] = normalized_actions
        last = normalized_actions[-1]
        row["action"] = last["action"]
        row["outcome"] = last["outcome"]
        row["success"] = last["success"]
        row["started_at"] = str(row.get("started_at") or normalized_actions[0]["at"])
        row["at"] = row["started_at"]
        row["updated_at"] = str(row.get("updated_at") or last["at"])
        row["action_label"] = _action_label(normalized_actions)
        row["id"] = str(row.get("id") or _make_event_id(row.get("server_id") or "", row.get("session_id") or "", 0))
        rows.append(row)
    return _sort_event_rows(rows)


def _normalize_stream_rows(raw: Any) -> List[Dict[str, Any]]:
    source = raw.get("rows") if isinstance(raw, dict) else raw
    if not isinstance(source, list):
        return []
    rows = []
    for item in source:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["id"] = str(row.get("id") or _make_event_id(row.get("server_id") or "", row.get("session_id") or "", 0))
        row["event_id"] = str(row.get("event_id") or "")
        row["playback_key"] = str(row.get("playback_key") or "")
        row["content_key"] = str(row.get("content_key") or "")
        row["session_id"] = str(row.get("session_id") or "")
        row["session_key"] = str(row.get("session_key") or "")
        row["started_at"] = str(row.get("started_at") or row.get("updated_at") or _utc_timestamp())
        row["updated_at"] = str(row.get("updated_at") or row.get("last_seen_at") or row["started_at"])
        row["last_seen_at"] = str(row.get("last_seen_at") or row["updated_at"])
        if row.get("ended_at"):
            row["ended_at"] = str(row.get("ended_at"))
        row["tags"] = _unique_ordered(row.get("tags") or [])
        row["violations_committed"] = _unique_ordered(row.get("violations_committed") or [])
        row["transcode_reasons"] = _normalize_reason_list(row.get("transcode_reasons"))
        actions = row.get("actions")
        if not isinstance(actions, list):
            actions = []
        normalized_actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            normalized_actions.append({
                "action": str(action.get("action") or "event"),
                "outcome": str(action.get("outcome") or ""),
                "success": bool(action.get("success", True)),
                "at": str(action.get("at") or row["updated_at"]),
                "source": str(action.get("source") or "guard"),
            })
        row["actions"] = normalized_actions
        row["action_label"] = _action_label(normalized_actions) if normalized_actions else str(row.get("action_label") or "")
        row["observations"] = max(0, _to_int(row.get("observations"), 0))
        row["violation_count"] = max(0, _to_int(row.get("violation_count"), 0))
        rows.append(row)
    return _sort_stream_rows(rows)


def _normalize_playback_event_rows(raw: Any) -> List[Dict[str, Any]]:
    source = raw.get("rows") if isinstance(raw, dict) else raw
    if not isinstance(source, list):
        return []
    rows = []
    for item in source:
        if not isinstance(item, dict):
            continue
        source = _normalize_playback_event_source(item.get("source"))
        if source not in {"player", "plugin", "proxy"}:
            continue
        server_id = bounded_event_bridge_text(item.get("server_id"), 512)
        session_id = bounded_event_bridge_text(item.get("session_id"), 512)
        row = {
            "id": bounded_event_bridge_text(
                item.get("id") or _make_event_id(server_id, session_id, 0),
                256,
            ),
            "server_id": server_id,
            "session_id": session_id,
            "play_session_id": bounded_event_bridge_text(item.get("play_session_id"), 512),
            "media_source_id": bounded_event_bridge_text(item.get("media_source_id"), 512),
            "event_name": bounded_event_bridge_text(item.get("event_name")),
            "message_type": bounded_event_bridge_text(item.get("message_type")),
            "action": bounded_event_bridge_text(item.get("action")),
            "outcome": bounded_event_bridge_text(item.get("outcome"), 512),
            "audio_stream_index": item.get("audio_stream_index"),
            "subtitle_stream_index": item.get("subtitle_stream_index"),
            "source": source,
            "transport": _normalize_playback_event_transport(item.get("transport")),
            "at": bounded_event_bridge_text(item.get("at") or _utc_timestamp(), 64),
        }
        rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("at") or ""), reverse=True)


def _normalize_playback_event_source(source: Any) -> str:
    value = str(source or "player").strip().lower()
    if value in PLUGIN_PLAYBACK_SOURCE_ALIASES:
        return "plugin"
    if value in PROXY_PLAYBACK_SOURCE_ALIASES:
        return "proxy"
    if value in {"player", "websocket", "emby_websocket"}:
        return "player"
    return value


def _normalize_playback_event_transport(transport: Any) -> str:
    value = str(transport or "").strip().lower()
    if value in {"websocket", "ws"}:
        return "websocket"
    if value in {"http", "http_fallback", "fallback_http"}:
        return "http_fallback"
    return ""


def _sort_event_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: str(row.get("updated_at") or row.get("at") or ""),
        reverse=True,
    )


def _sort_stream_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: str(row.get("updated_at") or row.get("last_seen_at") or row.get("started_at") or ""),
        reverse=True,
    )
