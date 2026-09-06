"""Settings, lifecycle and public API methods for Transcode Guard."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from emby_runtime.playback_events import normalize_emby_playback_events
from emby_runtime.transcode_guard_constants import TRANSCODE_GUARD_SETTINGS_KEY
from emby_runtime.transcode_guard_events import _flatten_event_bridge_payload
from emby_runtime.transcode_guard_locking import synchronized_history
from emby_runtime.transcode_guard_rules import classify_stream, normalize_transcode_guard_settings
from emby_runtime.transcode_guard_stats import build_user_stream_stats, get_stream_history_detail
from emby_runtime.transcode_guard_streams import _validate_transcode_guard_settings
from emby_runtime.transcode_guard_values import _parse_datetime
from emby_runtime.transcode_guard_validation import validate_transcode_guard_persisted_size


class TranscodeGuardControlMixin:
    def allow_server(self, server_id: str) -> None:
        """Admit a newly saved server and invalidate work from its older identity."""
        server_key = str(server_id or "").strip()
        if not server_key:
            return
        with self._lock:
            self._server_generations[server_key] = self._server_generations.get(server_key, 0) + 1
            self._forgotten_servers.discard(server_key)

    def forget_server(self, server_id: str) -> None:
        """Fence deleted-server work and remove its in-memory violation state."""
        server_key = str(server_id or "").strip()
        if not server_key:
            return
        with self._lock:
            self._server_generations[server_key] = self._server_generations.get(server_key, 0) + 1
            self._forgotten_servers.add(server_key)
            self._violations = {
                key: state
                for key, state in self._violations.items()
                if str(state.get("server_id") or "") != server_key
            }

    def _capture_server_generation(self, server_id: str) -> int:
        with self._lock:
            if server_id in self._forgotten_servers:
                return -1
            return self._server_generations.setdefault(server_id, 0)

    def _server_generation_is_current(self, server_id: str, generation: int) -> bool:
        return (
            server_id not in self._forgotten_servers
            and self._server_generations.get(server_id, 0) == generation
        )

    def load_settings(self) -> Dict[str, Any]:
        try:
            storage = self._storage_provider()
            raw = storage.get_key_value(TRANSCODE_GUARD_SETTINGS_KEY) if storage else None
        except Exception:
            raw = None
        return normalize_transcode_guard_settings(raw if isinstance(raw, dict) else {})

    def save_settings(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        storage = self._storage_provider()
        if not storage:
            raise RuntimeError("Storage Transcode Guard non disponibile")

        settings_base = self.load_settings()

        def merge_settings(current_raw):
            current = normalize_transcode_guard_settings(
                current_raw if isinstance(current_raw, dict) else settings_base
            )
            merged = dict(current)
            if isinstance(raw, dict):
                allowed_fields = {
                    "enabled",
                    "poll_interval_seconds",
                    "stream_history_retention_days",
                    "rules",
                }
                unsupported = sorted(set(raw) - allowed_fields)
                if unsupported:
                    raise ValueError(
                        "Campi Transcode Guard non supportati: " + ", ".join(unsupported)
                    )
                merged.update({key: raw[key] for key in allowed_fields if key in raw})
            settings = normalize_transcode_guard_settings(merged)
            _validate_transcode_guard_settings(settings)
            validate_transcode_guard_persisted_size(settings)
            return settings

        atomic_update = getattr(storage, "update_key_value", None)
        if callable(atomic_update):
            return atomic_update(TRANSCODE_GUARD_SETTINGS_KEY, merge_settings)

        settings = merge_settings(storage.get_key_value(TRANSCODE_GUARD_SETTINGS_KEY))
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

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        """Stop the monitor and wait for its worker within a bounded timeout."""
        self.stop()
        with self._lock:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout=max(0.0, timeout_seconds))
        return not thread.is_alive()

    def wake(self) -> None:
        """Wake the worker so WebSocket session events are checked promptly."""
        self._wake_event.set()

    def record_playback_event(self, server_id: str, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Record a concrete Emby playback event when WebSocket exposes one."""
        with self._lock:
            if str(server_id or "").strip() in self._forgotten_servers:
                return None
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

    @synchronized_history
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

    @synchronized_history
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

    def get_stream_history_detail(self, stream_id: str) -> Optional[Dict[str, Any]]:
        return get_stream_history_detail(self._load_stream_rows(), stream_id)

    def decorate_streams(self, server_id: str, streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        settings = self.load_settings()
        decorated = []
        with self._lock:
            violations = dict(self._violations)
        for stream in streams or []:
            item = dict(stream)
            item["server_id"] = server_id
            decision = classify_stream(item, settings)
            decision["enabled"] = bool(settings.get("enabled"))
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
