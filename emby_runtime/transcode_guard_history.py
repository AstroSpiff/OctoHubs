"""Persistent stream and playback history for Transcode Guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Iterable, List, Optional

from emby_runtime.transcode_guard_adapters import _utc_timestamp
from emby_runtime.transcode_guard_constants import (
    TRANSCODE_GUARD_EVENTS_KEY,
    TRANSCODE_GUARD_EXIT_SETTLE_SECONDS,
    TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY,
    TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT,
    TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_MAX_BYTES,
    TRANSCODE_GUARD_STREAM_LOG_KEY,
    TRANSCODE_GUARD_STREAM_LOG_LIMIT,
    TRANSCODE_GUARD_STREAM_STATUS_LIMIT,
)
from emby_runtime.transcode_guard_events import (
    _append_stream_action,
    _content_key,
    _is_duplicate_playback_event,
    _make_event_id,
    _observed_stream_change_actions,
    _playback_key,
)
from emby_runtime.transcode_guard_rows import (
    _normalize_event_rows,
    _normalize_playback_event_rows,
    _normalize_stream_rows,
)
from emby_runtime.transcode_guard_locking import synchronized_history
from emby_runtime.transcode_guard_streams import (
    _action_label,
    _is_terminal_action,
    _last_action_entry,
    _stream_action_tags,
    _stream_identity_fields,
    _stream_observation_tags,
    _stream_row_is_correct,
    _stream_technical_violations,
    _unique_ordered,
)
from emby_runtime.transcode_guard_values import _parse_datetime


def _rows_within_json_budget(rows: List[Dict[str, Any]], max_bytes: int) -> List[Dict[str, Any]]:
    """Keep newest rows while bounding the serialized persistence footprint."""
    kept: List[Dict[str, Any]] = []
    used = 2  # JSON list delimiters.
    for row in rows:
        row_bytes = len(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        required = row_bytes + (1 if kept else 0)
        if used + required > max_bytes:
            break
        kept.append(row)
        used += required
    return kept


class TranscodeGuardHistoryMixin:
    def _stream_history_payload(self) -> Dict[str, Any]:
        rows = self._load_stream_rows()
        limited = rows[:TRANSCODE_GUARD_STREAM_STATUS_LIMIT]
        return {
            "rows": limited,
            "total": len(rows),
            "correct": sum(1 for row in rows if _stream_row_is_correct(row)),
            "violations": sum(1 for row in rows if row.get("violations_committed")),
            "active": sum(1 for row in rows if not row.get("ended_at")),
        }

    def _playback_events_payload(self) -> Dict[str, Any]:
        rows = self._load_playback_event_rows()
        return {
            "rows": rows[:TRANSCODE_GUARD_STREAM_STATUS_LIMIT],
            "total": len(rows),
        }

    @synchronized_history
    def _record_stream_observation(
        self,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        *,
        event_id: Optional[str] = None,
        action: Optional[str] = None,
        outcome: str = "",
        success: bool = True,
        source: str = "guard",
    ) -> None:
        server_id = str(server.get("id") or stream.get("server_id") or "")
        session_id = str(stream.get("session_id") or "")
        playback_key = str(stream.get("playback_key") or _playback_key(server_id, stream) or "")
        if not playback_key:
            return
        now = _utc_timestamp()
        rows = self._load_stream_rows()
        row = None
        if event_id:
            row = next(
                (
                    item
                    for item in rows
                    if str(item.get("event_id") or item.get("id") or "") == str(event_id)
                ),
                None,
            )
        if row is None:
            row = next(
                (
                    item
                    for item in rows
                    if item.get("playback_key") == playback_key and not item.get("ended_at")
                ),
                None,
            )
        if row is None:
            row = {
                "id": _make_event_id(server_id, session_id or playback_key, self._now()),
                "event_id": str(event_id or ""),
                "playback_key": playback_key,
                "content_key": _content_key(stream),
                "session_key": self._session_key(server_id, session_id) if session_id else "",
                "session_id": session_id,
                "started_at": now,
                "updated_at": now,
                "last_seen_at": now,
                "observations": 0,
                "violation_count": 0,
                "actions": [],
                "tags": [],
                "violations_committed": [],
            }
            rows.insert(0, row)

        previous_enforced = bool(row.get("last_should_enforce"))
        should_enforce = bool(decision.get("should_enforce"))
        if should_enforce and not previous_enforced:
            row["violation_count"] = int(row.get("violation_count") or 0) + 1
        self._record_observed_stream_changes(row, server, stream, decision, now)

        if event_id:
            row["event_id"] = str(event_id)
        action_entry = None
        if action:
            action_entry = {
                "action": str(action),
                "outcome": str(outcome or ""),
                "success": bool(success),
                "at": now,
                "source": source,
            }
            _append_stream_action(row, action_entry)
            if action in {"exit", "stop", "pause"}:
                row["ended_at"] = now
            elif action in {"relapse", "resolved", "partial_resolved", "resolution_change", "resolved_later"}:
                row.pop("ended_at", None)

        row.update(_stream_identity_fields(server, stream, decision))
        row["last_should_enforce"] = should_enforce
        row["last_decision_category"] = decision.get("category") or ""
        row["last_decision_reason"] = decision.get("reason") or decision.get("label") or ""
        row["last_rule_id"] = decision.get("rule_id") or ""
        row["last_rule_name"] = decision.get("rule_name") or ""
        row["last_rule_path"] = decision.get("rule_path") or []
        row["observations"] = int(row.get("observations") or 0) + 1
        row["last_seen_at"] = now
        row["updated_at"] = now
        row["tags"] = _unique_ordered([
            *(row.get("tags") or []),
            *_stream_observation_tags(stream, decision),
            *(_stream_action_tags(action_entry) if action_entry else []),
        ])
        row["violations_committed"] = _unique_ordered([
            *(row.get("violations_committed") or []),
            *_stream_technical_violations(stream, decision),
        ])
        row["action_label"] = _action_label(row.get("actions") or []) if row.get("actions") else ""
        self._save_stream_rows(rows)

    def _record_observed_stream_changes(
        self,
        row: Dict[str, Any],
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        now: str,
    ) -> None:
        if int(row.get("observations") or 0) <= 0:
            return
        server_id = str(server.get("id") or stream.get("server_id") or "")
        session_id = str(stream.get("session_id") or "")
        if not server_id or not session_id:
            return
        observed = _observed_stream_change_actions(row, stream, decision)
        for action, outcome in observed:
            action_entry = {
                "action": action,
                "outcome": outcome,
                "success": True,
                "at": now,
                "source": "observed",
            }
            _append_stream_action(row, action_entry)

    @synchronized_history
    def _close_missing_stream_rows(self, scanned_server_ids: Iterable[str], present_playback_keys: Iterable[str]) -> None:
        scanned = {str(item or "") for item in scanned_server_ids}
        present = {str(item or "") for item in present_playback_keys}
        if not scanned:
            return
        now = _utc_timestamp()
        rows = self._load_stream_rows()
        changed = False
        for row in rows:
            if row.get("ended_at"):
                continue
            if str(row.get("server_id") or "") not in scanned:
                continue
            if str(row.get("playback_key") or "") in present:
                if "missing_since" in row or "missing_since_at" in row:
                    row.pop("missing_since", None)
                    row.pop("missing_since_at", None)
                    changed = True
                continue
            missing_since = row.get("missing_since")
            if missing_since is None:
                row["missing_since"] = float(self._now())
                row["missing_since_at"] = now
                row["updated_at"] = now
                changed = True
                continue
            try:
                missing_elapsed = float(self._now()) - float(missing_since)
            except (TypeError, ValueError):
                missing_elapsed = TRANSCODE_GUARD_EXIT_SETTLE_SECONDS
            if missing_elapsed < TRANSCODE_GUARD_EXIT_SETTLE_SECONDS:
                continue
            self._record_exit_for_stream_row(row)
            row["ended_at"] = now
            row["updated_at"] = now
            changed = True
        if changed:
            self._save_stream_rows(rows)

    def _record_exit_for_stream_row(self, row: Dict[str, Any]) -> None:
        event_id = str(row.get("event_id") or "")
        if not event_id:
            return
        event_row = next((item for item in self._load_event_rows() if item.get("id") == event_id), None)
        if not event_row or _is_terminal_action(_last_action_entry(event_row)):
            return
        server = {
            "id": row.get("server_id") or "",
            "name": row.get("server_name") or "",
        }
        stream = dict(row)
        self._record_event_action(
            event_id,
            "exit",
            "Uscita riproduzione",
            server,
            stream,
            {
                "category": row.get("last_decision_category") or row.get("category"),
                "source_height": row.get("source_height"),
                "rule_id": row.get("last_rule_id") or row.get("rule_id") or "",
                "rule_name": row.get("last_rule_name") or row.get("rule_name") or "",
                "rule_path": row.get("last_rule_path") or row.get("rule_path") or [],
            },
            success=True,
        )

    @synchronized_history
    def _record_stream_playback_event(self, event: Dict[str, Any]) -> bool:
        server_id = str(event.get("server_id") or "")
        session_id = str(event.get("session_id") or "")
        action = str(event.get("action") or "")
        if not server_id or not session_id or not action:
            return False
        rows = self._load_stream_rows()
        row = next(
            (
                item
                for item in rows
                if str(item.get("server_id") or "") == server_id
                and str(item.get("session_id") or "") == session_id
                and not item.get("ended_at")
            ),
            None,
        )
        if row is None:
            return False
        now = _utc_timestamp()
        action_entry = {
            "action": action,
            "outcome": str(event.get("outcome") or ""),
            "success": True,
            "at": now,
            "source": str(event.get("source") or "player"),
        }
        _append_stream_action(row, action_entry)
        if action == "exit":
            row["ended_at"] = now
        row["last_playback_event"] = str(event.get("event_name") or "")
        row["last_playback_event_at"] = now
        row["play_session_id"] = row.get("play_session_id") or event.get("play_session_id") or ""
        row["media_source_id"] = row.get("media_source_id") or event.get("media_source_id") or ""
        if event.get("audio_stream_index") is not None:
            row["audio_stream_index"] = event.get("audio_stream_index")
        if event.get("subtitle_stream_index") is not None:
            row["subtitle_stream_index"] = event.get("subtitle_stream_index")
        row["updated_at"] = now
        row["tags"] = _unique_ordered([
            *(row.get("tags") or []),
            *_stream_action_tags(action_entry),
        ])
        row["action_label"] = _action_label(row.get("actions") or [])
        self._save_stream_rows(rows)
        return True

    @synchronized_history
    def _apply_stream_history_retention(self, settings: Dict[str, Any]) -> int:
        try:
            days = int(settings.get("stream_history_retention_days") or 0)
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            return 0
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        rows = self._load_stream_rows()
        kept = []
        deleted = 0
        for row in rows:
            row_time = _parse_datetime(row.get("started_at") or row.get("updated_at"))
            if row_time is not None and row_time < threshold:
                deleted += 1
            else:
                kept.append(row)
        if deleted:
            self._save_stream_rows(kept)
        return deleted

    def _load_stream_rows(self) -> List[Dict[str, Any]]:
        storage = self._storage_provider()
        raw = storage.get_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY) if storage else None
        return _normalize_stream_rows(raw)

    def _save_stream_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_stream_rows(rows)[:TRANSCODE_GUARD_STREAM_LOG_LIMIT]
        storage = self._storage_provider()
        if storage:
            storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, normalized)

    @synchronized_history
    def _record_playback_event_row(self, event: Dict[str, Any]) -> None:
        now = _utc_timestamp()
        row = {
            "id": _make_event_id(
                str(event.get("server_id") or ""),
                f"{event.get('session_id') or ''}:{event.get('action') or ''}",
                self._now(),
            ),
            "server_id": str(event.get("server_id") or ""),
            "session_id": str(event.get("session_id") or ""),
            "play_session_id": str(event.get("play_session_id") or ""),
            "media_source_id": str(event.get("media_source_id") or ""),
            "event_name": str(event.get("event_name") or ""),
            "message_type": str(event.get("message_type") or ""),
            "action": str(event.get("action") or ""),
            "outcome": str(event.get("outcome") or ""),
            "audio_stream_index": event.get("audio_stream_index"),
            "subtitle_stream_index": event.get("subtitle_stream_index"),
            "at": now,
            "source": str(event.get("source") or "player"),
            "transport": str(event.get("transport") or ""),
        }
        rows = self._load_playback_event_rows()
        if rows and _is_duplicate_playback_event(rows[0], row):
            rows[0]["at"] = row["at"]
            self._save_playback_event_rows(rows)
            return
        rows.insert(0, row)
        self._save_playback_event_rows(rows)

    def _load_playback_event_rows(self) -> List[Dict[str, Any]]:
        storage = self._storage_provider()
        raw = storage.get_key_value(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY) if storage else None
        return _normalize_playback_event_rows(raw)

    def _save_playback_event_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_playback_event_rows(rows)[:TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT]
        normalized = _rows_within_json_budget(
            normalized,
            TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_MAX_BYTES,
        )
        storage = self._storage_provider()
        if storage:
            storage.set_key_value(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY, normalized)

    def _load_event_rows(self) -> List[Dict[str, Any]]:
        storage = self._storage_provider()
        raw = storage.get_key_value(TRANSCODE_GUARD_EVENTS_KEY) if storage else None
        rows = _normalize_event_rows(raw)
        with self._lock:
            self._recent_events = [dict(row) for row in rows]
        return rows

    def _save_event_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_event_rows(rows)
        storage = self._storage_provider()
        if storage:
            storage.set_key_value(TRANSCODE_GUARD_EVENTS_KEY, normalized)
        with self._lock:
            self._recent_events = [dict(row) for row in normalized]

    @staticmethod
    def _session_key(server_id: str, session_id: str) -> str:
        return f"{server_id}:{session_id}"

    @staticmethod
    def _violation_key(server_id: str, session_id: str, rule_id: str = "default") -> str:
        return f"{server_id}:{session_id}:{rule_id or 'default'}"
