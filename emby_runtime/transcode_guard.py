"""Transcode Guard policy and runtime service helpers."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from emby_runtime.playback_events import normalize_emby_playback_events
from emby_runtime.transcode_guard_rules import (
    DEFAULT_TRANSCODE_GUARD_SETTINGS,
    TRANSCODE_GUARD_MODES as TRANSCODE_GUARD_MODES,
    classify_stream,
    normalize_transcode_guard_settings,
)
from emby_runtime.transcode_guard_stats import build_user_stream_stats


TRANSCODE_GUARD_SETTINGS_KEY = "octohubs_transcode_guard:settings:v1"
TRANSCODE_GUARD_STATE_KEY = "octohubs_transcode_guard:state:v1"
TRANSCODE_GUARD_EVENTS_KEY = "octohubs_transcode_guard:events:v1"
TRANSCODE_GUARD_STREAM_LOG_KEY = "octohubs_transcode_guard:stream_log:v1"
TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY = "octohubs_transcode_guard:playback_events:v1"
LEGACY_TRANSCODE_GUARD_KEYS = {
    TRANSCODE_GUARD_SETTINGS_KEY: "octohub_transcode_guard:settings:v1",
    TRANSCODE_GUARD_STATE_KEY: "octohub_transcode_guard:state:v1",
    TRANSCODE_GUARD_EVENTS_KEY: "octohub_transcode_guard:events:v1",
    TRANSCODE_GUARD_STREAM_LOG_KEY: "octohub_transcode_guard:stream_log:v1",
    TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY: "octohub_transcode_guard:playback_events:v1",
}
TRANSCODE_GUARD_EXIT_SETTLE_SECONDS = 4
TRANSCODE_GUARD_STREAM_LOG_LIMIT = 1000
TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT = 1000
TRANSCODE_GUARD_STREAM_STATUS_LIMIT = 160
PLUGIN_PLAYBACK_SOURCE_ALIASES = {
    "plugin",
    "emby_plugin",
    "octohubs_plugin",
    "octohubs_event_bridge",
    "octohubs.eventbridge",
    "octohub_plugin",
    "octohub_event_bridge",
    "octohub.eventbridge",
    "event_bridge",
}
PROXY_PLAYBACK_SOURCE_ALIASES = {
    "proxy",
    "reverse_proxy",
    "octohubs_proxy",
    "octohub_proxy",
}

TRANSCODE_GUARD_ACTION_LABELS = {
    "play": "riproduzione",
    "time_update": "aggiornamento posizione",
    "warn": "avviso",
    "warning_error": "errore avviso",
    "stop": "stop",
    "pause": "pausa",
    "unpause": "ripresa",
    "volume_change": "cambio volume",
    "repeat_mode_change": "cambio ripetizione",
    "resolved": "risolto",
    "partial_resolved": "Risolto Parz.",
    "resolution_change": "Cambio Ris.",
    "quality_change": "cambio qualità",
    "audio_change": "cambio audio",
    "subtitle_change": "cambio sottotitoli",
    "playlist_item_move": "playlist: spostamento",
    "playlist_item_remove": "playlist: rimozione",
    "playlist_item_add": "playlist: aggiunta",
    "state_change": "cambio stato",
    "subtitle_offset_change": "cambio offset sottotitoli",
    "playback_rate_change": "cambio velocità",
    "shuffle_change": "cambio shuffle",
    "sleep_timer_change": "cambio sleep timer",
    "player_event": "evento player",
    "exit": "uscito",
    "resolved_later": "risolto in seguito",
    "relapse": "ricaduta",
}
_LEGACY_POLICY_FIELDS = (
    "mode",
    "video_state",
    "audio_state",
    "remux_state",
    "transformation_state",
    "min_source_height",
    "grace_seconds",
    "correction_window_seconds",
    "message_display_mode",
    "warning_timeout_ms",
    "max_warnings",
    "message_cooldown_seconds",
    "allow_audio_only_transcode",
    "allow_container_remux",
    "ignore_paused",
    "message_header",
    "message_text",
)
_LEGACY_RULE_SCOPE_FIELDS = (
    "server_ids",
    "excluded_users",
    "excluded_clients",
    "excluded_devices",
    "excluded_ips",
)


class TranscodeGuardService:
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

    def load_settings(self) -> Dict[str, Any]:
        try:
            storage = self._storage_provider()
            raw = _get_key_value_with_legacy(storage, TRANSCODE_GUARD_SETTINGS_KEY) if storage else None
        except Exception:
            raw = None
        return normalize_transcode_guard_settings(raw if isinstance(raw, dict) else {})

    def save_settings(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        current = self.load_settings()
        merged = dict(current)
        if isinstance(raw, dict):
            if "rules" not in raw and _has_legacy_policy_fields(raw):
                current_rules = list(current.get("rules") or [])
                primary_rule = dict(current_rules[0]) if current_rules else {}
                for key in (*_LEGACY_POLICY_FIELDS, *_LEGACY_RULE_SCOPE_FIELDS):
                    if key in raw:
                        primary_rule[key] = raw.get(key)
                if current_rules:
                    current_rules[0] = primary_rule
                else:
                    current_rules = [primary_rule]
                merged["rules"] = current_rules
            merged.update(raw)
            if "rules" in raw:
                for key in _LEGACY_RULE_SCOPE_FIELDS:
                    if key not in raw:
                        merged[key] = []
        settings = normalize_transcode_guard_settings(merged)
        _validate_transcode_guard_settings(settings)
        storage = self._storage_provider()
        storage.set_key_value(TRANSCODE_GUARD_SETTINGS_KEY, settings)
        return settings

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._wake_event.set()
                return False
            self._stop_event.clear()
            self._wake_event.set()
            self._thread = threading.Thread(target=self._run_loop, name="octohubs-transcode-guard", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                return False
            self._stop_event.set()
            self._wake_event.set()
            return True

    def wake(self) -> None:
        """Wake the worker so WebSocket session events are checked promptly."""
        self._wake_event.set()

    def record_playback_event(self, server_id: str, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Record a concrete Emby playback event when WebSocket exposes one."""
        events = normalize_emby_playback_events(server_id, event_data)
        if not events:
            return None
        result = None
        for event in events:
            self._record_playback_event_row(event)
            action = event.get("action")
            session_id = str(event.get("session_id") or "")
            if not session_id:
                continue
            if action == "exit":
                result = self._record_playback_stopped_event(event)
            elif action in {"quality_change", "audio_change", "subtitle_change"}:
                result = self._record_playback_change_event(event)
            else:
                recorded = self._record_stream_playback_event(event)
                result = {"ok": True, "action": action, "recorded": recorded}
        return result

    def record_plugin_playback_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Record a real playback event emitted by the OctoHubs Emby plugin."""
        if not isinstance(payload, dict):
            return None
        server_id = str(
            payload.get("serverId")
            or payload.get("server_id")
            or payload.get("server")
            or ""
        ).strip()
        if not server_id:
            return None
        event_data = dict(payload)
        event_data["source"] = "octohubs_event_bridge"
        if not (event_data.get("MessageType") or event_data.get("messageType") or event_data.get("message_type")):
            event_data["messageType"] = str(payload.get("eventType") or payload.get("event_type") or "PluginPlaybackEvent")
        return self.record_playback_event(server_id, event_data)

    def record_event_bridge_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Record an extensible event emitted by the OctoHubs Emby Event Bridge plugin."""
        if not isinstance(payload, dict):
            return None
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        event_type = str(
            event.get("type")
            or payload.get("eventType")
            or payload.get("event_type")
            or ""
        ).strip().lower()
        if not event_type or event_type.startswith("playback.") or event_type.startswith("session."):
            return self.record_plugin_playback_event(_flatten_event_bridge_payload(payload))
        if event_type.startswith("plugin."):
            return self._record_event_bridge_plugin_diagnostic(payload, event_type)
        return {"ok": True, "action": "ignored", "recorded": False, "event_type": event_type}

    def _record_event_bridge_plugin_diagnostic(self, payload: Dict[str, Any], event_type: str) -> Dict[str, Any]:
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
        server_id = str(
            server.get("id")
            or payload.get("serverId")
            or payload.get("server_id")
            or ""
        ).strip()
        if not server_id:
            return {"ok": True, "action": "plugin_event", "recorded": False, "event_type": event_type}
        event_name = str(
            event.get("name")
            or payload.get("eventName")
            or payload.get("event_name")
            or event_type
        ).strip()
        self._record_playback_event_row({
            "server_id": server_id,
            "session_id": f"{server_id}:plugin",
            "event_name": event_name,
            "message_type": event_type,
            "action": "plugin_event",
            "outcome": "evento plugin",
            "source": "plugin",
            "transport": str(payload.get("_eventBridgeTransport") or payload.get("eventBridgeTransport") or ""),
            "raw": payload,
        })
        return {"ok": True, "action": "plugin_event", "recorded": True, "event_type": event_type}

    def get_status(self) -> Dict[str, Any]:
        settings = self.load_settings()
        recent_events = self._load_event_rows()
        stream_history = self._stream_history_payload()
        playback_events = self._playback_events_payload()
        with self._lock:
            active = [dict(item) for item in self._violations.values()]
            last_result = dict(self._last_result)
            running = bool(self._thread and self._thread.is_alive())
        return {
            "ok": True,
            "running": running,
            "settings": settings,
            "active_violations": active,
            "recent_events": recent_events,
            "stream_history": stream_history,
            "playback_events": playback_events,
            "last_result": last_result,
        }

    def clear_events(self, before: Optional[str] = None) -> int:
        rows = self._load_event_rows()
        if not before:
            deleted = len(rows)
            self._save_event_rows([])
            return deleted
        threshold = _parse_datetime(before)
        if threshold is None:
            return 0
        kept: List[Dict[str, Any]] = []
        deleted = 0
        for row in rows:
            row_time = _parse_datetime(row.get("started_at") or row.get("at") or row.get("updated_at"))
            if row_time is not None and row_time < threshold:
                deleted += 1
            else:
                kept.append(row)
        if deleted:
            self._save_event_rows(kept)
        return deleted

    def clear_stream_history(self, before: Optional[str] = None) -> int:
        rows = self._load_stream_rows()
        if not before:
            deleted = len(rows)
            self._save_stream_rows([])
            return deleted
        threshold = _parse_datetime(before)
        if threshold is None:
            return 0
        kept: List[Dict[str, Any]] = []
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

    def get_user_stats(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return build_user_stream_stats(self._load_stream_rows(), filters or {})

    def decorate_streams(self, server_id: str, streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        settings = self.load_settings()
        decorated = []
        with self._lock:
            violations = dict(self._violations)
        for stream in streams or []:
            item = dict(stream)
            item["server_id"] = server_id
            decision = classify_stream(item, settings)
            state = violations.get(self._violation_key(
                server_id,
                item.get("session_id") or "",
                decision.get("rule_id") or "default",
            ))
            if state and decision.get("should_enforce"):
                decision["state"] = state.get("state") or "active"
                decision["first_seen_at"] = state.get("first_seen_at")
                decision["warned_at"] = state.get("warned_at")
                decision["stopped_at"] = state.get("stopped_at")
            item["transcode_guard"] = decision
            decorated.append(item)
        return decorated

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
            streams, error = self._fetch_sessions(server)
            if error is not None:
                result["errors"].append(f"{_server_label(server)}: {error}")
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
                    if _is_corrected_playback(decision):
                        if playback_key:
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
            if _last_action(row) in {"exit", "stop", "pause"}:
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
            settings = self.load_settings()
            self._wake_event.clear()
            if settings.get("enabled"):
                try:
                    self.check_once()
                except Exception as exc:  # pragma: no cover - defensive worker boundary
                    with self._lock:
                        self._last_result = {
                            "checked": 0,
                            "violations": 0,
                            "warned": 0,
                            "paused": 0,
                            "stopped": 0,
                            "errors": [str(exc)],
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
            if _last_action(row) not in {"exit", "stop", "pause"}:
                if stop_at_newer_closed_same_resolution and same_resolution and _last_action(row) in {"resolved", "resolved_later", "resolution_change"}:
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
        if not event_row or _last_action(event_row) in {"exit", "stop", "pause"}:
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
        try:
            storage = self._storage_provider()
            raw = _get_key_value_with_legacy(storage, TRANSCODE_GUARD_STREAM_LOG_KEY) if storage else None
        except Exception:
            raw = None
        return _normalize_stream_rows(raw)

    def _save_stream_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_stream_rows(rows)[:TRANSCODE_GUARD_STREAM_LOG_LIMIT]
        try:
            storage = self._storage_provider()
            if storage:
                storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, normalized)
        except Exception:
            pass

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
        try:
            storage = self._storage_provider()
            raw = _get_key_value_with_legacy(storage, TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY) if storage else None
        except Exception:
            raw = None
        return _normalize_playback_event_rows(raw)

    def _save_playback_event_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_playback_event_rows(rows)[:TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT]
        try:
            storage = self._storage_provider()
            if storage:
                storage.set_key_value(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY, normalized)
        except Exception:
            pass

    def _load_event_rows(self) -> List[Dict[str, Any]]:
        try:
            storage = self._storage_provider()
            raw = _get_key_value_with_legacy(storage, TRANSCODE_GUARD_EVENTS_KEY) if storage else None
        except Exception:
            raw = None
        rows = _normalize_event_rows(raw)
        with self._lock:
            self._recent_events = [dict(row) for row in rows]
        return rows

    def _save_event_rows(self, rows: List[Dict[str, Any]]) -> None:
        normalized = _normalize_event_rows(rows)
        try:
            storage = self._storage_provider()
            if storage:
                storage.set_key_value(TRANSCODE_GUARD_EVENTS_KEY, normalized)
        except Exception:
            pass
        with self._lock:
            self._recent_events = [dict(row) for row in normalized]

    @staticmethod
    def _session_key(server_id: str, session_id: str) -> str:
        return f"{server_id}:{session_id}"

    @staticmethod
    def _violation_key(server_id: str, session_id: str, rule_id: str = "default") -> str:
        return f"{server_id}:{session_id}:{rule_id or 'default'}"


def _decision(
    category: str,
    reason: str,
    severity: str,
    should_enforce: bool,
    stream: Dict[str, Any],
    settings: Dict[str, Any],
    video_height: Optional[int],
) -> Dict[str, Any]:
    return {
        "category": category,
        "label": reason,
        "reason": reason,
        "severity": severity,
        "should_enforce": bool(should_enforce),
        "source_height": video_height,
        "threshold": settings.get("min_source_height"),
        "mode": settings.get("mode"),
        "session_id": stream.get("session_id") or "",
    }


def _make_event_id(server_id: str, session_id: str, now: float) -> str:
    clean_server = _slug_part(server_id or "server")
    clean_session = _slug_part(session_id or "session")
    return f"{clean_server}:{clean_session}:{int(float(now) * 1000)}"


def _get_key_value_with_legacy(storage: Any, key: str) -> Any:
    value = storage.get_key_value(key)
    if value is not None:
        return value
    legacy_key = LEGACY_TRANSCODE_GUARD_KEYS.get(key)
    if legacy_key:
        return storage.get_key_value(legacy_key)
    return None


def _flatten_event_bridge_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    flattened = dict(payload)
    flattened.update({
        "source": "octohubs_event_bridge",
        "eventBridgeTransport": payload.get("_eventBridgeTransport") or payload.get("eventBridgeTransport") or "",
        "serverId": server.get("id") or payload.get("serverId") or payload.get("server_id") or "",
        "messageType": event.get("type") or payload.get("messageType") or payload.get("message_type") or "PluginPlaybackEvent",
        "eventName": event.get("name") or payload.get("eventName") or payload.get("event_name") or "",
        "sessionId": session.get("id") or payload.get("sessionId") or payload.get("session_id") or "",
        "playSessionId": session.get("playSessionId") or payload.get("playSessionId") or payload.get("play_session_id") or "",
        "mediaSourceId": media.get("mediaSourceId") or payload.get("mediaSourceId") or payload.get("media_source_id") or "",
        "audioStreamIndex": media.get("audioStreamIndex") if "audioStreamIndex" in media else payload.get("audioStreamIndex"),
        "subtitleStreamIndex": media.get("subtitleStreamIndex") if "subtitleStreamIndex" in media else payload.get("subtitleStreamIndex"),
        "itemId": item.get("id") or payload.get("itemId") or payload.get("item_id") or "",
    })
    return flattened


def _playback_key(server_id: str, stream: Dict[str, Any]) -> str:
    user = _slug_part(stream.get("user") or "user")
    device = _slug_part(stream.get("device_id") or stream.get("device") or stream.get("client") or "device")
    content = _content_key(stream)
    if not content:
        return ""
    return "|".join([str(server_id or ""), user, device, content])


def _content_key(stream: Dict[str, Any]) -> str:
    media_type = str(stream.get("media_type") or "").strip().lower()
    series = str(stream.get("series_name") or "").strip()
    season = stream.get("season_number")
    episode = stream.get("episode_number")
    if (media_type == "episode" or series) and season is not None and episode is not None:
        return "episode:" + "|".join([
            _slug_part(series or stream.get("title") or "series"),
            _slug_part(season if season is not None else ""),
            _slug_part(episode if episode is not None else ""),
        ])
    item_id = str(stream.get("item_id") or "").strip()
    if item_id:
        return f"item:{item_id}"
    title = str(stream.get("title") or "").strip()
    year = str(stream.get("year") or "").strip()
    if not title:
        return ""
    return "title:" + "|".join([_slug_part(title), _slug_part(year)])


def _matching_other_violation(
    matches: Optional[List[Dict[str, Any]]],
    current_key: str,
) -> Optional[Dict[str, Any]]:
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("key") or "") != str(current_key or ""):
            return match
    return None


def _matching_other_rule_violation(
    match: Optional[Dict[str, Any]],
    current_rule_id: Any,
) -> Optional[Dict[str, Any]]:
    if not isinstance(match, dict):
        return None
    decision = match.get("decision") if isinstance(match.get("decision"), dict) else {}
    if str(decision.get("rule_id") or "") == str(current_rule_id or ""):
        return None
    return match


def _resolved_action_for_stream(previous: Dict[str, Any], stream: Dict[str, Any]) -> Tuple[str, str]:
    if _same_source_resolution(previous, stream):
        return "resolved", "Risolta"
    return "resolution_change", "Cambio risoluzione"


def _later_success_action_for_stream(previous: Dict[str, Any], stream: Dict[str, Any]) -> Tuple[str, str]:
    if _same_source_resolution(previous, stream):
        return "resolved_later", "Risolto in seguito"
    return "resolution_change", "Cambio risoluzione"


def _same_source_resolution(previous: Dict[str, Any], stream: Dict[str, Any]) -> bool:
    previous_height = _extract_video_height(previous)
    current_height = _extract_video_height(stream)
    if previous_height is None or current_height is None:
        return True
    return abs(previous_height - current_height) <= 80


def _observed_stream_change_actions(
    previous: Dict[str, Any],
    stream: Dict[str, Any],
    decision: Dict[str, Any],
) -> List[Tuple[str, str]]:
    actions: List[Tuple[str, str]] = []
    previous_source = str(previous.get("media_source_id") or "").strip()
    current_source = str(stream.get("media_source_id") or "").strip()
    previous_height = _extract_video_height(previous)
    current_height = decision.get("source_height") or _extract_video_height(stream)
    source_changed = bool(
        previous.get("media_source_id_known")
        and previous_source
        and current_source
        and previous_source != current_source
    )
    height_changed = bool(
        previous.get("video_height_known")
        and
        previous_height is not None
        and current_height is not None
        and not _same_source_resolution(previous, {"video_height": current_height})
    )
    if source_changed or height_changed:
        actions.append(("quality_change", "Cambio qualità"))

    if (
        previous.get("audio_stream_index_known")
        and "audio_stream_index" in stream
        and _stream_value_changed(previous.get("audio_stream_index"), stream.get("audio_stream_index"))
    ):
        actions.append(("audio_change", "Cambio audio"))
    if (
        previous.get("subtitle_stream_index_known")
        and "subtitle_stream_index" in stream
        and _stream_value_changed(previous.get("subtitle_stream_index"), stream.get("subtitle_stream_index"))
    ):
        actions.append(("subtitle_change", "Cambio sottotitoli"))
    return actions


def _stream_value_changed(previous: Any, current: Any) -> bool:
    previous_value = "" if previous is None else str(previous)
    current_value = "" if current is None else str(current)
    return previous_value != current_value


def _is_duplicate_playback_event(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
    keys = (
        "server_id",
        "session_id",
        "play_session_id",
        "media_source_id",
        "event_name",
        "message_type",
        "action",
        "audio_stream_index",
        "subtitle_stream_index",
    )
    if any(str(previous.get(key) or "") != str(current.get(key) or "") for key in keys):
        return False
    previous_at = _parse_datetime(previous.get("at"))
    current_at = _parse_datetime(current.get("at"))
    if previous_at is None or current_at is None:
        return True
    return abs((current_at - previous_at).total_seconds()) <= 2


def _append_stream_action(row: Dict[str, Any], action_entry: Dict[str, Any]) -> None:
    actions = row.setdefault("actions", [])
    action = str(action_entry.get("action") or "")
    if actions and isinstance(actions[-1], dict) and actions[-1].get("action") == action:
        actions[-1].update(action_entry)
    else:
        actions.append(action_entry)


def _camel_action(action: str) -> str:
    return "".join(part.capitalize() for part in str(action or "").split("_") if part)


def _slug_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", " ").replace(":", " ")


def _is_corrected_playback(decision: Dict[str, Any]) -> bool:
    if decision.get("should_enforce"):
        return False
    return str(decision.get("category") or "") in {"direct", "container_remux", "remux", "audio_transcode"}


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
        row = dict(item)
        row["id"] = str(row.get("id") or _make_event_id(row.get("server_id") or "", row.get("session_id") or "", 0))
        row["server_id"] = str(row.get("server_id") or "")
        row["session_id"] = str(row.get("session_id") or "")
        row["play_session_id"] = str(row.get("play_session_id") or "")
        row["media_source_id"] = str(row.get("media_source_id") or "")
        row["event_name"] = str(row.get("event_name") or "")
        row["message_type"] = str(row.get("message_type") or "")
        row["action"] = str(row.get("action") or "")
        row["outcome"] = str(row.get("outcome") or "")
        row["source"] = _normalize_playback_event_source(row.get("source"))
        row["transport"] = _normalize_playback_event_transport(row.get("transport"))
        if row["source"] not in {"player", "plugin", "proxy"}:
            continue
        if row["event_name"].lower().startswith("inferred") or row["message_type"].lower().startswith("inferred"):
            continue
        row["at"] = str(row.get("at") or _utc_timestamp())
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


def _stream_identity_fields(server: Dict[str, Any], stream: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    server_id = str(server.get("id") or stream.get("server_id") or "")
    session_id = str(stream.get("session_id") or "")
    position_seconds = _ticks_to_seconds(stream.get("position_ticks") or stream.get("playback_position_ticks"))
    duration_seconds = _ticks_to_seconds(stream.get("runtime_ticks") or stream.get("duration_ticks"))
    playback_percent = None
    if position_seconds is not None and duration_seconds:
        playback_percent = round(min(100.0, max(0.0, position_seconds / duration_seconds * 100.0)), 2)
    source_height = decision.get("source_height") or _extract_video_height(stream)
    return {
        "server_id": server_id,
        "server_name": _server_label(server),
        "session_id": session_id,
        "session_key": str(stream.get("session_key") or f"{server_id}:{session_id}" if session_id else ""),
        "play_session_id": stream.get("play_session_id") or "",
        "media_source_id": stream.get("media_source_id") or "",
        "audio_stream_index": stream.get("audio_stream_index"),
        "subtitle_stream_index": stream.get("subtitle_stream_index"),
        "media_source_id_known": bool(str(stream.get("media_source_id") or "").strip()),
        "audio_stream_index_known": "audio_stream_index" in stream,
        "subtitle_stream_index_known": "subtitle_stream_index" in stream,
        "video_height_known": _extract_video_height(stream) is not None,
        "playback_event_name": stream.get("playback_event_name") or "",
        "item_id": stream.get("item_id") or "",
        "title": stream.get("title") or "Stream",
        "user": stream.get("user") or "",
        "client": stream.get("client") or "",
        "device": stream.get("device") or "",
        "device_id": stream.get("device_id") or "",
        "ip": stream.get("ip") or stream.get("remote_address") or "",
        "media_type": stream.get("media_type") or "",
        "series_name": stream.get("series_name") or "",
        "season_number": stream.get("season_number"),
        "episode_number": stream.get("episode_number"),
        "year": stream.get("year") or "",
        "source_height": source_height,
        "video_height": _extract_video_height(stream),
        "video_width": _to_int_or_none(stream.get("video_width") or stream.get("width")),
        "source_quality_tier": decision.get("source_quality_tier") or "",
        "quality": f"{source_height}p" if source_height else "",
        "video_mode": stream.get("video_mode") or "",
        "audio_mode": stream.get("audio_mode") or "",
        "play_method": stream.get("play_method") or "",
        "container": stream.get("container") or "",
        "stream_container": stream.get("stream_container") or "",
        "transcode_container": stream.get("transcode_container") or "",
        "video_codec": stream.get("video_codec") or "",
        "audio_codec": stream.get("audio_codec") or "",
        "video_label": stream.get("video_label") or "",
        "audio_label": stream.get("audio_label") or "",
        "bitrate": stream.get("bitrate") or stream.get("media_bitrate") or "",
        "transcode_bitrate": stream.get("transcode_bitrate") or "",
        "position_seconds": position_seconds,
        "duration_seconds": duration_seconds,
        "playback_percent": playback_percent,
        "paused": bool(stream.get("paused") or stream.get("is_paused")),
        "transcode_reasons": _normalize_reason_list(stream.get("transcode_reasons") or stream.get("reasons")),
    }


def _stream_observation_tags(stream: Dict[str, Any], decision: Dict[str, Any]) -> List[str]:
    category = str(decision.get("category") or "")
    tags: List[str] = []
    technical = _stream_technical_violations(stream, decision)
    direct_container_remux = category in {"container_remux", "remux"} and not technical
    if direct_container_remux:
        tags.extend(["container remux", "direct stream"])
        if not decision.get("should_enforce"):
            tags.append("corretta")
    elif category == "direct" and not technical and not decision.get("should_enforce"):
        tags.extend(["corretta", "direct play"])
    if "video_transcode" in technical:
        tags.append("transcode video")
    if "audio_transcode" in technical:
        tags.append("transcode audio")
    if "subtitle_burnin" in technical:
        tags.append("sottotitoli burn-in")
    if "remux" in technical:
        tags.append("remux")
    if "browser_playback" in technical:
        tags.append("browser")
    if category == "unknown":
        tags.append("metadati incompleti")
    if bool(stream.get("paused") or stream.get("is_paused")):
        tags.append("pausa")
    if decision.get("should_enforce"):
        tags.append("violazione")
    elif technical:
        tags.append("non monitorata")
    return _unique_ordered(tags)


def _stream_action_tags(action: Optional[Dict[str, Any]]) -> List[str]:
    if not action:
        return []
    label = TRANSCODE_GUARD_ACTION_LABELS.get(str(action.get("action") or ""), str(action.get("action") or ""))
    return [label] if label else []


def _stream_technical_violations(stream: Dict[str, Any], decision: Dict[str, Any]) -> List[str]:
    category = str(decision.get("category") or "")
    violations: List[str] = []
    video_mode = str(stream.get("video_mode") or "").strip().lower()
    audio_mode = str(stream.get("audio_mode") or "").strip().lower()
    reasons = _normalize_reason_list(stream.get("transcode_reasons") or stream.get("reasons"))
    if category in {"video_transcode", "video_audio_transcode", "subtitle_burnin"} or video_mode in {"transcodifica", "transcode"}:
        violations.append("video_transcode")
    if category in {"audio_transcode", "video_audio_transcode"} or audio_mode in {"transcodifica", "transcode"}:
        violations.append("audio_transcode")
    if category == "subtitle_burnin" or _has_subtitle_burn_reason(reasons):
        violations.append("subtitle_burnin")
    if category == "remux":
        violations.append("remux")
    if category == "browser_playback" or _looks_like_browser_playback(stream):
        violations.append("browser_playback")
    if category == "unknown":
        violations.append("unknown_height")
    return _unique_ordered(violations)


def _stream_row_is_correct(row: Dict[str, Any]) -> bool:
    return "corretta" in (row.get("tags") or []) and not row.get("violations_committed")


def _looks_like_browser_playback(stream: Dict[str, Any]) -> bool:
    client = str(stream.get("client") or "").lower()
    return any(token in client for token in ("web", "browser", "chrome", "safari", "firefox", "edge"))


def _normalize_reason_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [value] if "," not in value else value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = [value]
    return _unique_ordered(str(part or "").strip() for part in parts)


def _unique_ordered(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ticks_to_seconds(value: Any) -> Optional[float]:
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return round(ticks / 10_000_000, 3)


def _action_label(actions: List[Dict[str, Any]]) -> str:
    labels = []
    for action in actions:
        key = str(action.get("action") or "")
        label = TRANSCODE_GUARD_ACTION_LABELS.get(key, key or "evento")
        if label and (not labels or labels[-1] != label):
            labels.append(label)
    return " - ".join(labels)


def _last_action(row: Dict[str, Any]) -> str:
    actions = row.get("actions")
    if isinstance(actions, list) and actions:
        last = actions[-1]
        if isinstance(last, dict):
            return str(last.get("action") or "")
    return str(row.get("action") or "")


def _terminal_row_has_open_problem(row: Dict[str, Any]) -> bool:
    actions = row.get("actions")
    if not isinstance(actions, list) or not actions:
        return False
    last_action = _last_action(row)
    if last_action == "stop":
        return True
    if last_action not in {"exit", "pause"}:
        return False
    for action in reversed(actions[:-1]):
        if not isinstance(action, dict):
            continue
        key = str(action.get("action") or "")
        if key in {"exit", "stop", "pause"}:
            continue
        return key in {"warn", "warning_error", "relapse", "partial_resolved"}
    return False


def _has_legacy_policy_fields(raw: Dict[str, Any]) -> bool:
    return any(key in raw for key in (*_LEGACY_POLICY_FIELDS, *_LEGACY_RULE_SCOPE_FIELDS))


def _validate_transcode_guard_settings(settings: Dict[str, Any]) -> None:
    for rule in settings.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        if rule.get("server_ids"):
            continue
        name = str(rule.get("name") or "Regola").strip() or "Regola"
        raise ValueError(f'Seleziona almeno un server per "{name}" o disattiva la regola.')


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if len(text) == 10 and text.count("-") == 2:
            text = f"{text}T00:00:00"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_video_height(stream: Dict[str, Any]) -> Optional[int]:
    for key in ("video_height", "height", "source_height"):
        value = stream.get(key)
        try:
            height = int(value)
        except (TypeError, ValueError):
            continue
        return height if height > 0 else None
    label = str(stream.get("video_label") or "")
    marker = "p"
    for part in label.replace("x", " ").replace("/", " ").split():
        cleaned = part.lower().strip()
        if cleaned.endswith(marker):
            cleaned = cleaned[:-1]
        try:
            height = int(cleaned)
        except ValueError:
            continue
        if 240 <= height <= 4320:
            return height
    return None


def _is_direct_mode(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"diretta", "direct", "directplay", "directstream", "direct play", "direct stream"}


def _looks_like_remux(stream: Dict[str, Any]) -> bool:
    source_container = _normalize_container_name(stream.get("container") or stream.get("stream_container"))
    output_container = _normalize_container_name(stream.get("transcode_container"))
    if output_container and source_container:
        return output_container != source_container
    stream_container = _normalize_container_name(stream.get("stream_container"))
    if stream_container and source_container:
        return stream_container != source_container
    return False


def _normalize_container_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "matroska": "mkv",
        "mpegts": "ts",
        "mpeg-ts": "ts",
        "m3u8": "hls",
    }
    return aliases.get(text, text)


def _has_subtitle_burn_reason(reasons: Iterable[str]) -> bool:
    return any("subtitle" in reason.lower() or "burn" in reason.lower() for reason in reasons)


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    value_norm = str(value or "").strip().lower()
    if not value_norm:
        return False
    return any(value_norm == str(pattern or "").strip().lower() for pattern in patterns or [])


def _ip_matches_any(value: str, patterns: Iterable[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    host = text
    if host.count(":") == 1 and "." in host:
        host = host.rsplit(":", 1)[0]
    try:
        address = ip_address(host)
    except ValueError:
        return _matches_any(text, patterns)
    for pattern in patterns or []:
        item = str(pattern or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                if address in ip_network(item, strict=False):
                    return True
            elif address == ip_address(item):
                return True
        except ValueError:
            if _matches_any(text, [item]):
                return True
    return False


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = [value]
    result = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sì"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(minimum, min(maximum, resolved))


def _format_message_value(
    template: Any,
    settings: Dict[str, Any],
    server: Dict[str, Any],
    stream: Dict[str, Any],
    *,
    fallback: str,
) -> str:
    text = str(template or fallback or "")
    replacements = _message_replacements(settings, server, stream)
    try:
        return text.format(**replacements)
    except Exception:
        return str(fallback or "").format(**replacements)


def _format_message(settings: Dict[str, Any], server: Dict[str, Any], stream: Dict[str, Any]) -> str:
    return _format_message_value(
        settings.get("message_text"),
        settings,
        server,
        stream,
        fallback=DEFAULT_TRANSCODE_GUARD_SETTINGS["message_text"],
    )


def _message_replacements(settings: Dict[str, Any], server: Dict[str, Any], stream: Dict[str, Any]) -> Dict[str, Any]:
    reasons = _normalize_string_list(stream.get("transcode_reasons"))
    stop_delay_seconds = settings.get("correction_window_seconds") if settings.get("mode") == "warn_then_stop" else 0
    replacements = {
        "title": stream.get("title") or "Stream",
        "server": _server_label(server),
        "user": stream.get("user") or "Utente",
        "client": stream.get("client") or "Client",
        "device": stream.get("device") or "Device",
        "reasons": ", ".join(reasons) if reasons else "Transcode video",
        "quality": f"{_extract_video_height(stream) or '?'}p",
        "seconds": stop_delay_seconds or 0,
    }
    return replacements


def _server_label(server: Dict[str, Any]) -> str:
    return (
        str(server.get("alias") or "").strip()
        or str(server.get("original_name") or "").strip()
        or str(server.get("name") or "").strip()
        or str(server.get("id") or "").strip()
        or "Server Emby"
    )


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


_TRANSCODE_GUARD_SERVICE: Optional[TranscodeGuardService] = None


def get_transcode_guard_service() -> TranscodeGuardService:
    global _TRANSCODE_GUARD_SERVICE
    if _TRANSCODE_GUARD_SERVICE is None:
        _TRANSCODE_GUARD_SERVICE = TranscodeGuardService()
    return _TRANSCODE_GUARD_SERVICE
