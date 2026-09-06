"""Violation enforcement and action logging for Transcode Guard."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from emby_runtime.transcode_guard_adapters import _utc_timestamp
from emby_runtime.transcode_guard_events import (
    _content_key,
    _later_success_action_for_stream,
    _make_event_id,
    _playback_key,
    _same_source_resolution,
)
from emby_runtime.transcode_guard_rules import DEFAULT_TRANSCODE_GUARD_SETTINGS
from emby_runtime.transcode_guard_rows import _sort_event_rows
from emby_runtime.transcode_guard_locking import synchronized_history
from emby_runtime.transcode_guard_streams import (
    _action_label,
    _is_terminal_action,
    _last_action,
    _last_action_entry,
    _terminal_row_has_open_problem,
)
from emby_runtime.transcode_guard_values import (
    _extract_video_height,
    _format_message,
    _format_message_value,
    _server_label,
)


class TranscodeGuardEnforcementMixin:
    def _handle_violation(
        self,
        key: str,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> str:
        now = float(self._now())
        server_id = str(server.get("id") or "")
        session_id = str(stream.get("session_id") or "")
        playback_key = _playback_key(server_id, stream)
        is_relapse = False
        resolution_change_prefix = False
        with self._lock:
            state = self._violations.get(key)
            if state is None:
                pending_resolution_change = self._close_pending_different_resolution_event(playback_key, stream)
                event_id = self._take_pending_exit_event_id(playback_key, stream)
                if not event_id:
                    event_id = self._find_reopenable_event_id(playback_key, session_id, stream)
                is_relapse = bool(event_id)
                resolution_change_prefix = bool(
                    not event_id
                    and (
                        pending_resolution_change
                        or self._find_previous_open_problem_event(playback_key, stream, require_different_resolution=True)
                        or self._find_pending_open_problem_event(playback_key, stream, require_different_resolution=True)
                    )
                )
                state = {
                    "key": key,
                    "event_id": event_id or _make_event_id(server_id, session_id, now),
                    "session_key": self._session_key(server_id, session_id),
                    "playback_key": playback_key,
                    "content_key": _content_key(stream),
                    "server_id": server_id,
                    "server_name": _server_label(server),
                    "session_id": session_id,
                    "item_id": stream.get("item_id") or "",
                    "title": stream.get("title") or "Stream",
                    "user": stream.get("user") or "",
                    "client": stream.get("client") or "",
                    "device": stream.get("device") or "",
                    "device_id": stream.get("device_id") or "",
                    "category": decision.get("category"),
                    "source_height": decision.get("source_height"),
                    "rule_id": decision.get("rule_id") or "",
                    "rule_name": decision.get("rule_name") or "",
                    "rule_path": decision.get("rule_path") or [],
                    "first_seen": now,
                    "first_seen_at": _utc_timestamp(),
                    "warned_at": None,
                    "first_warned": None,
                    "first_warned_at": None,
                    "warning_count": 0,
                    "stopped_at": None,
                    "paused_at": None,
                    "state": "detected",
                }
                if resolution_change_prefix:
                    state["resolution_change_prefix_pending"] = True
                self._violations[key] = state
            state["playback_key"] = playback_key or state.get("playback_key") or ""
            state["content_key"] = _content_key(stream) or state.get("content_key") or ""
            state["device_id"] = stream.get("device_id") or state.get("device_id") or ""
            state["last_seen"] = now
            state["last_seen_at"] = _utc_timestamp()
            state.pop("missing_since", None)
            state.pop("missing_since_at", None)
            state["category"] = decision.get("category")
            state["source_height"] = decision.get("source_height")
            state["rule_id"] = decision.get("rule_id") or state.get("rule_id") or ""
            state["rule_name"] = decision.get("rule_name") or state.get("rule_name") or ""
            state["rule_path"] = decision.get("rule_path") or state.get("rule_path") or []
            warned_at = state.get("warned")
            first_warned_at = state.get("first_warned") or warned_at
            stopped_at = state.get("stopped")
            paused_at = state.get("paused")

        if resolution_change_prefix:
            self._record_event_action(
                state.get("event_id"),
                "resolution_change",
                "Cambio risoluzione",
                server,
                stream,
                decision,
                success=True,
            )
            with self._lock:
                state["resolution_change_prefix_pending"] = False
                state["resolution_change_recorded"] = True

        if is_relapse:
            self._record_event_action(
                state.get("event_id"),
                "relapse",
                "Ricaduta",
                server,
                stream,
                decision,
                success=True,
            )

        if stopped_at or paused_at:
            return "waiting"

        mode = str(settings.get("mode") or "monitor")
        if mode == "monitor":
            with self._lock:
                state["state"] = "monitor"
            return "monitored"
        if mode == "warn":
            if self._can_send_warning(state, settings, now):
                warning_sent = self._send_warning(server, stream, decision, settings, state)
                with self._lock:
                    if warning_sent:
                        state["warned"] = now
                        state["warned_at"] = _utc_timestamp()
                        state["warning_count"] = int(state.get("warning_count") or 0) + 1
                        state["state"] = "warned"
                    else:
                        state["state"] = "error"
                return "warned" if warning_sent else "error"
            return "waiting"
        if mode == "stop":
            return self._stop_stream(server, stream, decision, state)
        if mode == "warn_then_stop":
            correction_window = int(settings.get("correction_window_seconds") or 0)
            if first_warned_at and now - float(first_warned_at) >= correction_window:
                return self._stop_stream(server, stream, decision, state)
            if self._can_send_warning(state, settings, now):
                warning_sent = self._send_warning(server, stream, decision, settings, state)
                with self._lock:
                    if warning_sent:
                        if not state.get("first_warned"):
                            state["first_warned"] = now
                            state["first_warned_at"] = _utc_timestamp()
                        state["warned"] = now
                        state["warned_at"] = _utc_timestamp()
                        state["warning_count"] = int(state.get("warning_count") or 0) + 1
                        state["state"] = "warned"
                    else:
                        state["state"] = "error"
                return "warned" if warning_sent else "error"
        return "waiting"

    def _can_send_warning(self, state: Dict[str, Any], settings: Dict[str, Any], now: float) -> bool:
        warned_at = state.get("warned")
        count = int(state.get("warning_count") or 0)
        max_warnings = int(settings.get("max_warnings") or 1)
        if count >= max_warnings:
            return False
        if not warned_at:
            return True
        cooldown = int(settings.get("message_cooldown_seconds") or 0)
        return cooldown <= 0 or now - float(warned_at) >= cooldown

    def _send_warning(
        self,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        settings: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        session_id = str(stream.get("session_id") or "")
        header = _format_message_value(settings.get("message_header"), settings, server, stream, fallback=DEFAULT_TRANSCODE_GUARD_SETTINGS["message_header"])
        text = _format_message(settings, server, stream)
        timeout_ms = None if settings.get("message_display_mode") == "confirmation" else int(settings.get("warning_timeout_ms") or DEFAULT_TRANSCODE_GUARD_SETTINGS["warning_timeout_ms"])
        success, payload = self._send_message(server, session_id, header, text, timeout_ms)
        action = "warn" if success else "warning_error"
        self._record_event_action(state.get("event_id"), action, "Avviso inviato" if success else "Errore avviso", server, stream, decision, success=bool(success))
        self._record_operation_event(
            "Avviso Transcode Guard",
            "Messaggio inviato da Transcode Guard" if success else f"Errore messaggio Transcode Guard: {payload}",
            server,
            stream,
            {"action": action, "success": bool(success), "decision": decision, "response": payload},
            success=bool(success),
        )
        return bool(success)

    def _pause_stream(
        self,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        state: Dict[str, Any],
    ) -> str:
        session_id = str(stream.get("session_id") or "")
        success, payload = self._pause_session(server, session_id)
        with self._lock:
            state["paused"] = float(self._now()) if success else None
            state["paused_at"] = _utc_timestamp() if success else None
            state["state"] = "paused" if success else "error"
        self._record_event_action(state.get("event_id"), "pause", "Sessione in pausa" if success else "Errore pausa", server, stream, decision, success=bool(success))
        self._record_operation_event(
            "Pausa Transcode Guard",
            "Sessione messa in pausa da Transcode Guard" if success else f"Errore pausa Transcode Guard: {payload}",
            server,
            stream,
            {"action": "pause", "success": bool(success), "decision": decision, "response": payload},
            success=bool(success),
        )
        return "paused" if success else "error"

    def _stop_stream(
        self,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        state: Dict[str, Any],
    ) -> str:
        session_id = str(stream.get("session_id") or "")
        success, payload = self._stop_session(server, session_id)
        with self._lock:
            state["stopped"] = float(self._now()) if success else None
            state["stopped_at"] = _utc_timestamp() if success else None
            state["state"] = "stopped" if success else "error"
        self._record_event_action(state.get("event_id"), "stop", "Sessione fermata" if success else "Errore stop", server, stream, decision, success=bool(success))
        self._record_operation_event(
            "Blocco Transcode Guard",
            "Sessione fermata da Transcode Guard" if success else f"Errore stop Transcode Guard: {payload}",
            server,
            stream,
            {"action": "stop", "success": bool(success), "decision": decision, "response": payload},
            success=bool(success),
        )
        return "stopped" if success else "error"

    def _record_operation_event(
        self,
        title: str,
        message: str,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        result: Dict[str, Any],
        *,
        success: bool,
    ) -> None:
        try:
            tracker = self._operation_tracker_provider()
        except Exception:
            tracker = None
        if not tracker:
            return
        details = {
            "server": _server_label(server),
            "server_id": server.get("id") or "",
            "user": stream.get("user") or "",
            "client": stream.get("client") or "",
            "title": stream.get("title") or "Stream",
            "source_height": _extract_video_height(stream),
            "action": result.get("action"),
            "rule_id": result.get("decision", {}).get("rule_id") if isinstance(result.get("decision"), dict) else "",
            "rule_name": result.get("decision", {}).get("rule_name") if isinstance(result.get("decision"), dict) else "",
        }
        try:
            operation = tracker.start(
                "transcode_guard",
                title,
                summary=details["title"],
                details=details,
                total=1,
            )
            operation_id = operation.get("id") if isinstance(operation, dict) else None
            if not operation_id:
                return
            if success:
                tracker.finish(operation_id, message, result=result)
            else:
                tracker.fail(operation_id, message, result=result)
        except Exception:
            return

    def _record_later_success(
        self,
        playback_key: str,
        stream: Dict[str, Any],
        scanned_server_ids: Iterable[str],
    ) -> None:
        server_id = str(stream.get("server_id") or "").strip()
        if not server_id and isinstance(playback_key, str):
            server_id = playback_key.split("|", 1)[0]
        if server_id and server_id not in set(scanned_server_ids):
            return
        session_id = str(stream.get("session_id") or "")
        if not playback_key or not session_id:
            return
        rows = self._load_event_rows()
        previous = self._find_previous_open_problem_event(
            playback_key,
            stream,
            stop_at_newer_closed_same_resolution=True,
        )
        if not previous:
            return
        action, outcome = _later_success_action_for_stream(previous, stream)
        if any(
            row.get("playback_key") == playback_key
            and row.get("session_id") == session_id
            and any(item.get("action") == action for item in row.get("actions") or [])
            for row in rows
        ):
            return
        server = {
            "id": previous.get("server_id") or server_id,
            "name": previous.get("server_name") or "",
        }
        self._record_event_action(
            None,
            action,
            outcome,
            server,
            stream,
            {
                "category": "direct",
                "source_height": _extract_video_height(stream),
                "rule_id": previous.get("rule_id") or "",
                "rule_name": previous.get("rule_name") or "",
                "rule_path": previous.get("rule_path") or [],
            },
            success=True,
        )

    def _find_previous_open_problem_event(
        self,
        playback_key: str,
        stream: Dict[str, Any],
        *,
        require_different_resolution: bool = False,
        stop_at_newer_closed_same_resolution: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not playback_key:
            return None
        for row in self._load_event_rows():
            if row.get("playback_key") != playback_key:
                continue
            same_resolution = _same_source_resolution(row, stream)
            last_action = _last_action(row)
            if not _is_terminal_action(_last_action_entry(row)):
                if stop_at_newer_closed_same_resolution and same_resolution and last_action in {"resolved", "resolved_later", "resolution_change"}:
                    return None
                continue
            if not _terminal_row_has_open_problem(row):
                if stop_at_newer_closed_same_resolution and same_resolution:
                    return None
                continue
            if require_different_resolution and same_resolution:
                continue
            return row
        return None

    @synchronized_history
    def _record_event_action(
        self,
        event_id: Optional[str],
        action: str,
        outcome: str,
        server: Dict[str, Any],
        stream: Dict[str, Any],
        decision: Dict[str, Any],
        *,
        success: bool,
        source: str = "guard",
    ) -> None:
        now = _utc_timestamp()
        server_id = str(server.get("id") or stream.get("server_id") or "")
        session_id = str(stream.get("session_id") or "")
        playback_key = str(stream.get("playback_key") or _playback_key(server_id, stream) or "")
        event_id = str(event_id or _make_event_id(server_id, session_id or playback_key, self._now()))
        action_entry = {
            "action": action,
            "outcome": outcome,
            "success": bool(success),
            "at": now,
            "source": source,
        }
        rows = self._load_event_rows()
        row = next((item for item in rows if item.get("id") == event_id), None)
        if row is None:
            row = {
                "id": event_id,
                "playback_key": playback_key,
                "content_key": stream.get("content_key") or _content_key(stream),
                "session_id": session_id,
                "item_id": stream.get("item_id") or "",
                "title": stream.get("title") or "Stream",
                "user": stream.get("user") or "",
                "client": stream.get("client") or "",
                "device": stream.get("device") or "",
                "device_id": stream.get("device_id") or "",
                "server_id": server_id,
                "server_name": _server_label(server),
                "source_height": decision.get("source_height") or _extract_video_height(stream),
                "category": decision.get("category"),
                "rule_id": decision.get("rule_id") or "",
                "rule_name": decision.get("rule_name") or "",
                "rule_path": decision.get("rule_path") or [],
                "started_at": now,
                "actions": [],
            }
            rows.insert(0, row)
        actions = row.setdefault("actions", [])
        if actions and actions[-1].get("action") == action:
            actions[-1].update(action_entry)
        else:
            actions.append(action_entry)
        row.update({
            "action": action,
            "outcome": outcome,
            "success": bool(success),
            "at": row.get("started_at") or now,
            "updated_at": now,
            "action_label": _action_label(actions),
            "playback_key": row.get("playback_key") or playback_key,
            "content_key": row.get("content_key") or stream.get("content_key") or _content_key(stream),
            "session_id": row.get("session_id") or session_id,
            "item_id": row.get("item_id") or stream.get("item_id") or "",
            "device_id": row.get("device_id") or stream.get("device_id") or "",
            "source_height": row.get("source_height") or decision.get("source_height") or _extract_video_height(stream),
            "category": row.get("category") or decision.get("category"),
            "rule_id": row.get("rule_id") or decision.get("rule_id") or "",
            "rule_name": row.get("rule_name") or decision.get("rule_name") or "",
            "rule_path": row.get("rule_path") or decision.get("rule_path") or [],
        })
        rows = _sort_event_rows(rows)
        self._save_event_rows(rows)
        self._record_stream_observation(server, stream, decision, event_id=event_id, action=action, outcome=outcome, success=success, source=source)

    def _find_reopenable_event_id(
        self,
        playback_key: str,
        session_id: str,
        stream: Dict[str, Any],
    ) -> Optional[str]:
        if not playback_key or not session_id:
            return None
        for row in self._load_event_rows():
            if row.get("playback_key") != playback_key:
                continue
            if str(row.get("session_id") or "") != session_id:
                continue
            if not _same_source_resolution(row, stream):
                continue
            if _last_action(row) in {"resolved", "resolution_change", "partial_resolved"}:
                return str(row.get("id") or "") or None
        return None

    def _take_pending_exit_event_id(self, playback_key: str, stream: Dict[str, Any]) -> Optional[str]:
        if not playback_key:
            return None
        for old_key, state in list(self._violations.items()):
            if str(state.get("playback_key") or "") != playback_key:
                continue
            if str(state.get("state") or "") != "pending_exit":
                continue
            if state.get("stopped") or state.get("paused"):
                continue
            if not _same_source_resolution(state, stream):
                continue
            self._violations.pop(old_key, None)
            return str(state.get("event_id") or "") or None
        return None

    def _close_pending_different_resolution_event(self, playback_key: str, stream: Dict[str, Any]) -> bool:
        if not playback_key:
            return False
        for old_key, state in list(self._violations.items()):
            if str(state.get("playback_key") or "") != playback_key:
                continue
            if str(state.get("state") or "") != "pending_exit":
                continue
            if state.get("stopped") or state.get("paused"):
                continue
            if _same_source_resolution(state, stream):
                continue
            state = self._violations.pop(old_key)
            self._record_exit_for_violation_state(state)
            return True
        return False

    def _find_pending_open_problem_event(
        self,
        playback_key: str,
        stream: Dict[str, Any],
        *,
        require_different_resolution: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not playback_key:
            return None
        for state in self._violations.values():
            if str(state.get("playback_key") or "") != playback_key:
                continue
            if str(state.get("state") or "") != "pending_exit":
                continue
            if state.get("stopped") or state.get("paused"):
                continue
            if require_different_resolution and _same_source_resolution(state, stream):
                continue
            return state
        return None
