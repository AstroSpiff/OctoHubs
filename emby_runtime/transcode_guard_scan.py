"""Polling and session-transition handling for Transcode Guard."""

from __future__ import annotations

from typing import Any, Dict, List

from emby_runtime.transcode_guard_adapters import _get_emby_servers_from_config, _utc_timestamp
from emby_runtime.transcode_guard_constants import TRANSCODE_GUARD_EXIT_SETTLE_SECONDS
from emby_runtime.transcode_guard_events import (
    _is_corrected_playback,
    _matching_other_rule_violation,
    _matching_other_violation,
    _playback_key,
    _resolved_action_for_stream,
    _same_source_resolution,
)
from emby_runtime.transcode_guard_rules import classify_stream
from emby_runtime.transcode_guard_streams import (
    _is_terminal_action,
    _last_action_entry,
)
from emby_runtime.transcode_guard_values import _server_label


class TranscodeGuardScanMixin:
    def check_once(self) -> Dict[str, Any]:
        settings = self.load_settings()
        result = {
            "checked": 0,
            "violations": 0,
            "warned": 0,
            "paused": 0,
            "stopped": 0,
            "errors": [],
        }
        if not settings.get("enabled"):
            with self._lock:
                self._last_result = result
            return result

        config, is_valid = self._load_config()
        if not is_valid or not config:
            result["errors"].append("Config non valida")
            with self._lock:
                self._last_result = result
            return result

        servers = _get_emby_servers_from_config(config)
        seen_keys = set()
        present_session_keys = set()
        present_playback_keys = set()
        direct_playback_streams: Dict[str, Dict[str, Any]] = {}
        violating_playback_streams: Dict[str, List[Dict[str, Any]]] = {}
        scanned_server_ids = set()
        for server in servers:
            server_id = str(server.get("id") or "")
            if not server_id or not server.get("enabled", True):
                continue
            server_generation = self._capture_server_generation(server_id)
            streams, error = self._fetch_sessions(server)
            if error is not None:
                result["errors"].append(f"{_server_label(server)}: {error}")
                continue
            # The lifecycle lock is also the deletion barrier: once forget_server()
            # returns, an in-flight fetch cannot repopulate violations for this ID.
            with self._lock:
                if not self._server_generation_is_current(server_id, server_generation):
                    continue
                scanned_server_ids.add(server_id)
                for stream in streams or []:
                    if not isinstance(stream, dict):
                        continue
                    stream = dict(stream)
                    stream["server_id"] = server_id
                    stream["server_name"] = _server_label(server)
                    result["checked"] += 1
                    session_id = str(stream.get("session_id") or "")
                    if not session_id:
                        continue
                    present_session_keys.add(self._session_key(server_id, session_id))
                    decision = classify_stream(stream, settings)
                    playback_key = _playback_key(server_id, stream)
                    if playback_key:
                        present_playback_keys.add(playback_key)
                    self._record_stream_observation(server, stream, decision)
                    key = self._violation_key(server_id, session_id, decision.get("rule_id") or "default")
                    if not decision.get("should_enforce"):
                        if _is_corrected_playback(decision) and playback_key:
                            direct_stream = dict(stream)
                            direct_stream["server_id"] = server_id
                            direct_stream["server_name"] = _server_label(server)
                            direct_playback_streams.setdefault(playback_key, direct_stream)
                        continue
                    seen_keys.add(key)
                    if playback_key:
                        violating_stream = dict(stream)
                        violating_stream["server_id"] = server_id
                        violating_stream["server_name"] = _server_label(server)
                        violating_playback_streams.setdefault(playback_key, []).append({
                            "key": key,
                            "stream": violating_stream,
                            "decision": decision,
                        })
                    result["violations"] += 1
                    action = self._handle_violation(key, server, stream, decision, decision)
                    if action == "warned":
                        result["warned"] += 1
                    elif action == "paused":
                        result["paused"] += 1
                    elif action == "stopped":
                        result["stopped"] += 1

        with self._lock:
            stale_keys = [
                key
                for key, state in self._violations.items()
                if state.get("server_id") in scanned_server_ids and key not in seen_keys
            ]
            resolved_playback_keys = set()
            for key in stale_keys:
                stale = self._violations.get(key)
                if not stale:
                    continue
                playback_key = str(stale.get("playback_key") or "")
                if not stale.get("stopped") and not stale.get("paused"):
                    direct_stream = direct_playback_streams.get(playback_key) if playback_key else None
                    if direct_stream:
                        stale = self._violations.pop(key)
                        if not _same_source_resolution(stale, direct_stream):
                            self._record_exit_for_violation_state(stale)
                            continue
                        resolved_playback_keys.add(playback_key)
                        action, outcome = _resolved_action_for_stream(stale, direct_stream)
                        self._record_event_action(
                            stale.get("event_id"),
                            action,
                            outcome,
                            {
                                "id": stale.get("server_id"),
                                "name": stale.get("server_name"),
                            },
                            stale,
                            {
                                "category": "direct",
                                "source_height": stale.get("source_height"),
                                "rule_id": stale.get("rule_id"),
                                "rule_name": stale.get("rule_name"),
                                "rule_path": stale.get("rule_path"),
                            },
                            success=True,
                        )
                        continue

                    other_violation = _matching_other_violation(
                        violating_playback_streams.get(playback_key),
                        key,
                    )
                    if other_violation and not _same_source_resolution(stale, other_violation.get("stream") or {}):
                        stale = self._violations.pop(key)
                        self._record_exit_for_violation_state(stale)
                        continue

                    partial_match = _matching_other_rule_violation(other_violation, stale.get("rule_id"))
                    if partial_match:
                        stale = self._violations.pop(key)
                        self._record_event_action(
                            stale.get("event_id"),
                            "partial_resolved",
                            "Risolto parzialmente",
                            {
                                "id": stale.get("server_id"),
                                "name": stale.get("server_name"),
                            },
                            stale,
                            {
                                "category": partial_match.get("decision", {}).get("category") or stale.get("category"),
                                "source_height": stale.get("source_height"),
                                "rule_id": stale.get("rule_id"),
                                "rule_name": stale.get("rule_name"),
                                "rule_path": stale.get("rule_path"),
                            },
                            success=True,
                        )
                        continue

                    if stale.get("session_key") in present_session_keys:
                        continue

                    now = float(self._now())
                    missing_since = stale.get("missing_since")
                    if missing_since is None:
                        stale["missing_since"] = now
                        stale["missing_since_at"] = _utc_timestamp()
                        stale["state"] = "pending_exit"
                        continue
                    if now - float(missing_since) < TRANSCODE_GUARD_EXIT_SETTLE_SECONDS:
                        continue

                    stale = self._violations.pop(key)
                    self._record_exit_for_violation_state(stale)
                else:
                    self._violations.pop(key, None)
            for playback_key, stream in direct_playback_streams.items():
                if playback_key in resolved_playback_keys:
                    continue
                self._record_later_success(playback_key, stream, scanned_server_ids)
            self._close_missing_stream_rows(scanned_server_ids, present_playback_keys)
            self._apply_stream_history_retention(settings)
            self._last_result = result
        return result

    def _record_exit_for_violation_state(self, state: Dict[str, Any], *, source: str = "observed") -> None:
        self._record_event_action(
            state.get("event_id"),
            "exit",
            "Uscita riproduzione",
            {
                "id": state.get("server_id"),
                "name": state.get("server_name"),
            },
            state,
            {
                "category": state.get("category"),
                "source_height": state.get("source_height"),
                "rule_id": state.get("rule_id"),
                "rule_name": state.get("rule_name"),
                "rule_path": state.get("rule_path"),
            },
            success=True,
            source=source,
        )

    def _record_playback_stopped_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        server_id = str(event.get("server_id") or "")
        session_id = str(event.get("session_id") or "")
        session_key = self._session_key(server_id, session_id)
        closed = []
        already_closed_by_guard = 0
        with self._lock:
            for key, state in list(self._violations.items()):
                if str(state.get("session_key") or "") != session_key:
                    continue
                state = self._violations.pop(key)
                if state.get("stopped") or state.get("paused"):
                    already_closed_by_guard += 1
                    continue
                closed.append(state)
        for state in closed:
            self._record_exit_for_violation_state(state, source="player")
        if not already_closed_by_guard:
            self._record_stream_playback_event(event)
            if not closed:
                closed.extend(self._record_exit_for_recent_event_session(event))
        return {"ok": True, "action": "exit", "closed": len(closed), "ignored": already_closed_by_guard}

    def _record_exit_for_recent_event_session(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        server_id = str(event.get("server_id") or "")
        session_id = str(event.get("session_id") or "")
        if not server_id or not session_id:
            return []
        closed = []
        for row in self._load_event_rows():
            if str(row.get("server_id") or "") != server_id:
                continue
            if str(row.get("session_id") or "") != session_id:
                continue
            if _is_terminal_action(_last_action_entry(row)):
                continue
            server = {
                "id": row.get("server_id") or server_id,
                "name": row.get("server_name") or "",
            }
            self._record_event_action(
                row.get("id"),
                "exit",
                "Uscita riproduzione",
                server,
                dict(row),
                {
                    "category": row.get("category"),
                    "source_height": row.get("source_height"),
                    "rule_id": row.get("rule_id") or "",
                    "rule_name": row.get("rule_name") or "",
                    "rule_path": row.get("rule_path") or [],
                },
                success=True,
                source="player",
            )
            closed.append(row)
            break
        return closed

    def _record_playback_change_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        server_id = str(event.get("server_id") or "")
        session_id = str(event.get("session_id") or "")
        session_key = self._session_key(server_id, session_id)
        matched = []
        with self._lock:
            for state in self._violations.values():
                if str(state.get("session_key") or "") == session_key:
                    matched.append(dict(state))
        for state in matched:
            self._record_event_action(
                state.get("event_id"),
                str(event.get("action") or ""),
                str(event.get("outcome") or ""),
                {
                    "id": state.get("server_id"),
                    "name": state.get("server_name"),
                },
                state,
                {
                    "category": state.get("category"),
                    "source_height": state.get("source_height"),
                    "rule_id": state.get("rule_id"),
                    "rule_name": state.get("rule_name"),
                    "rule_path": state.get("rule_path"),
                },
                success=True,
                source="player",
            )
        self._record_stream_playback_event(event)
        return {"ok": True, "action": event.get("action"), "matched": len(matched)}

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            settings = {}
            try:
                settings = self.load_settings()
                self._wake_event.clear()
                if settings.get("enabled"):
                    self.check_once()
            except BaseException:  # pragma: no cover - defensive worker boundary
                with self._lock:
                    self._last_result = {
                        "checked": 0,
                        "violations": 0,
                        "warned": 0,
                        "paused": 0,
                        "stopped": 0,
                        "errors": ["Errore nel ciclo Transcode Guard"],
                    }
            delay = int(settings.get("poll_interval_seconds") or 5)
            self._wait_for_next_cycle(max(2, delay))

    def _wait_for_next_cycle(self, delay: int) -> None:
        while not self._stop_event.is_set():
            if self._wake_event.wait(timeout=min(1.0, max(0.1, float(delay)))):
                self._wake_event.clear()
                return
            delay = int(max(0, delay - 1))
            if delay <= 0:
                return
