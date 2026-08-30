"""In-memory registry for Emby Event Bridge transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from emby_runtime.event_bridge_payloads import event_bridge_payloads
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, event_bridge_settings_from_plugin_payload

logger = logging.getLogger(__name__)

EVENT_BRIDGE_UPDATED_MESSAGE = "OctoHubsEventBridgeUpdated"


@dataclass
class EventBridgeServerState:
    server_id: str
    server_name: str = ""
    plugin_version: str = ""
    transport: str = "http"
    connected: bool = False
    connected_at: str = ""
    last_seen_at: str = ""
    last_event_at: str = ""
    last_config_sent_at: str = ""
    last_config_ack_at: str = ""
    last_config_transport: str = ""
    last_config_ack_status: str = ""
    last_config_ack_error: str = ""
    last_config_message_id: str = ""
    last_config_ack_message_id: str = ""
    last_plugin_settings_at: str = ""
    plugin_settings: dict[str, Any] = field(default_factory=dict)
    plugin_target_count: int | None = None
    plugin_targets: list[dict[str, str]] = field(default_factory=list)
    last_event_type: str = ""
    last_event_name: str = ""
    received_count: int = 0
    websocket: Any = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "server_name": self.server_name,
            "plugin_version": self.plugin_version,
            "transport": self.transport,
            "connected": self.connected,
            "connected_at": self.connected_at,
            "last_seen_at": self.last_seen_at,
            "last_event_at": self.last_event_at,
            "last_config_sent_at": self.last_config_sent_at,
            "last_config_ack_at": self.last_config_ack_at,
            "last_config_transport": self.last_config_transport,
            "last_config_ack_status": self.last_config_ack_status,
            "last_config_ack_error": self.last_config_ack_error,
            "last_config_message_id": self.last_config_message_id,
            "last_config_ack_message_id": self.last_config_ack_message_id,
            "last_plugin_settings_at": self.last_plugin_settings_at,
            "plugin_settings": dict(self.plugin_settings),
            "plugin_target_count": self.plugin_target_count,
            "plugin_targets": list(self.plugin_targets),
            "last_event_type": self.last_event_type,
            "last_event_name": self.last_event_name,
            "received_count": self.received_count,
        }


class EventBridgeConnectionManager:
    def __init__(self):
        self._servers: dict[str, EventBridgeServerState] = {}
        self._websocket_servers: dict[int, str] = {}

    async def register(self, websocket: Any, hello: dict[str, Any] | None = None) -> EventBridgeServerState:
        hello = hello or {}
        server_id, server_name = _server_identity(hello)
        previous_server_id = self._websocket_servers.get(id(websocket))
        if previous_server_id and previous_server_id != server_id:
            disconnected_server_id = self._detach_websocket(websocket)
            if disconnected_server_id:
                self._publish_update([disconnected_server_id], "disconnected")
        now = _utc_now()
        state = self._servers.get(server_id) or EventBridgeServerState(server_id=server_id)
        state.server_name = server_name or state.server_name
        state.plugin_version = str(hello.get("pluginVersion") or hello.get("version") or state.plugin_version or "")
        state.transport = "websocket"
        state.connected = True
        state.connected_at = now
        state.last_seen_at = now
        state.websocket = websocket
        self._servers[server_id] = state
        self._websocket_servers[id(websocket)] = server_id
        self._publish_update([server_id], "connected")
        return state

    async def disconnect(self, websocket: Any) -> None:
        server_id = self._detach_websocket(websocket)
        if server_id:
            self._publish_update([server_id], "disconnected")

    async def close_server_connection(self, server_id: str, code: int = 1008) -> bool:
        """Close the current transport after a credential rotation."""
        state = self._servers.get(str(server_id or "").strip())
        websocket = state.websocket if state else None
        if websocket is None:
            return False
        try:
            await websocket.close(code=code)
        finally:
            detached_server_id = self._detach_websocket(websocket)
            if detached_server_id:
                self._publish_update([detached_server_id], "credential_rotated")
        return True

    def _detach_websocket(self, websocket: Any) -> str | None:
        """Remove only the state still owned by this exact WebSocket instance."""
        server_id = self._websocket_servers.pop(id(websocket), None)
        if not server_id:
            return None
        state = self._servers.get(server_id)
        if state and state.websocket is websocket:
            state.connected = False
            state.websocket = None
            state.last_seen_at = _utc_now()
            return server_id
        return None

    async def push_configuration(self, server_id: str | None, settings: dict[str, Any]) -> int:
        pushed = 0
        for state in self._target_states(server_id):
            websocket = state.websocket
            if websocket is None:
                continue
            now = _utc_now()
            message_id = f"cfg-{state.server_id}-{uuid4().hex}"
            payload = {
                "type": "configure",
                "id": message_id,
                "sentAt": now,
                "settings": build_plugin_settings_payload(settings),
            }
            await websocket.send_json(payload)
            state.last_seen_at = now
            state.last_config_sent_at = now
            state.last_config_transport = "websocket"
            state.last_config_message_id = message_id
            state.last_config_ack_status = "pending"
            state.last_config_ack_error = ""
            pushed += 1
            self._publish_update([state.server_id], "configuration_sent")
        return pushed

    def record_config_ack(self, websocket: Any, payload: dict[str, Any]) -> EventBridgeServerState | None:
        server_id = self._websocket_servers.get(id(websocket)) or str(payload.get("serverId") or "").strip()
        if not server_id:
            return None

        now = _utc_now()
        state = self._servers.get(server_id) or EventBridgeServerState(server_id=server_id)
        state.transport = "websocket"
        state.connected = True
        state.websocket = websocket
        state.last_seen_at = now
        state.last_config_ack_at = now
        state.last_config_transport = "websocket"
        state.last_config_ack_message_id = str(payload.get("id") or payload.get("configureId") or "").strip()
        ok = payload.get("ok")
        applied = payload.get("applied")
        state.last_config_ack_status = "applied" if ok is not False and applied is not False else "error"
        state.last_config_ack_error = "" if state.last_config_ack_status == "applied" else str(payload.get("error") or "").strip()
        self._servers[server_id] = state
        self._websocket_servers[id(websocket)] = server_id
        self._publish_update([server_id], "configuration_acknowledged")
        return state

    def record_plugin_configuration_response(self, server_id: str | None, response: dict[str, Any] | None) -> None:
        """Record settings returned by the Emby plugin configuration endpoint."""
        if not server_id or not isinstance(response, dict):
            return

        now = _utc_now()
        state = self._servers.get(server_id) or EventBridgeServerState(server_id=server_id)
        state.server_name = str(response.get("ServerName") or response.get("serverName") or state.server_name or "")
        state.plugin_version = str(
            response.get("PluginVersion")
            or response.get("pluginVersion")
            or state.plugin_version
            or ""
        )
        if not state.connected:
            state.transport = "http"
        state.last_seen_at = now
        state.last_config_sent_at = now
        state.last_config_ack_at = now
        state.last_config_transport = "http"
        ok = response.get("Ok") if "Ok" in response else response.get("ok")
        applied = response.get("Applied") if "Applied" in response else response.get("applied")
        state.last_config_ack_status = "applied" if ok is not False and applied is not False else "error"
        state.last_config_ack_error = (
            ""
            if state.last_config_ack_status == "applied"
            else str(response.get("Error") or response.get("error") or "").strip()
        )
        settings = response.get("Settings") if "Settings" in response else response.get("settings")
        if isinstance(settings, dict):
            self._record_plugin_payload_state(state, settings)
        self._servers[server_id] = state
        self._publish_update([server_id], "configuration_applied")

    def record_http_event(self, payload: dict[str, Any]) -> None:
        payloads = event_bridge_payloads(payload)
        for item in payloads:
            server_id, server_name = _server_identity(item)
            state = self._servers.get(server_id) or EventBridgeServerState(server_id=server_id)
            state.server_name = server_name or state.server_name
            if not state.connected:
                state.transport = "http"
            state.last_seen_at = _utc_now()
            state.last_event_at = state.last_seen_at
            state.received_count += 1
            _record_event_identity(state, item)
            plugin = item.get("plugin") if isinstance(item.get("plugin"), dict) else {}
            if plugin:
                self._record_plugin_payload_state(state, plugin)
            self._servers[server_id] = state
        self._publish_update(_event_server_ids(payloads), "event_received")

    def record_websocket_event(self, websocket: Any, payload: dict[str, Any]) -> None:
        server_id = self._websocket_servers.get(id(websocket))
        payloads = event_bridge_payloads(payload)
        updated_server_ids: list[str] = []
        for item in payloads:
            event_server_id, event_server_name = _server_identity(item)
            key = server_id or event_server_id
            state = self._servers.get(key) or EventBridgeServerState(server_id=key)
            state.server_name = event_server_name or state.server_name
            state.transport = "websocket"
            state.connected = True
            state.websocket = websocket
            state.last_seen_at = _utc_now()
            state.last_event_at = state.last_seen_at
            state.received_count += 1
            _record_event_identity(state, item)
            plugin = item.get("plugin") if isinstance(item.get("plugin"), dict) else {}
            if plugin:
                self._record_plugin_payload_state(state, plugin)
            self._servers[key] = state
            if key and key != "unknown" and key not in updated_server_ids:
                updated_server_ids.append(key)
        self._publish_update(updated_server_ids, "event_received")

    def status(self) -> dict[str, Any]:
        servers = sorted(self._servers.values(), key=lambda item: (item.server_name or item.server_id).lower())
        return {
            "ok": True,
            "connected": sum(1 for item in servers if item.connected),
            "servers": [item.snapshot() for item in servers],
        }

    def _target_states(self, server_id: str | None) -> list[EventBridgeServerState]:
        if server_id:
            state = self._servers.get(server_id)
            return [state] if state else []
        return list(self._servers.values())

    def _record_plugin_payload_state(self, state: EventBridgeServerState, plugin: dict[str, Any]) -> None:
        state.plugin_settings = event_bridge_settings_from_plugin_payload(plugin)
        state.last_plugin_settings_at = _utc_now()
        state.plugin_version = str(plugin.get("version") or state.plugin_version or "")
        state.plugin_target_count = _int_or_none(plugin.get("octoHubsTargetCount"))
        state.plugin_targets = _plugin_targets(plugin.get("octoHubsTargets"))

    def _publish_update(self, server_ids: list[str], reason: str) -> None:
        try:
            from realtime.manager import publish_application_event

            publish_application_event(
                EVENT_BRIDGE_UPDATED_MESSAGE,
                {
                    "server_ids": [server_id for server_id in server_ids if server_id],
                    "reason": reason,
                },
            )
        except Exception:
            logger.debug("Impossibile pubblicare aggiornamento Event Bridge", exc_info=True)


_manager = EventBridgeConnectionManager()


def get_event_bridge_manager() -> EventBridgeConnectionManager:
    return _manager


def _server_identity(payload: dict[str, Any]) -> tuple[str, str]:
    server = payload.get("server")
    if isinstance(server, dict):
        server_id = str(server.get("id") or "").strip()
        server_name = str(server.get("name") or "").strip()
        if server_id or server_name:
            return server_id or server_name or "unknown", server_name
    server_id = str(payload.get("serverId") or "").strip()
    server_name = str(payload.get("serverName") or "").strip()
    return server_id or server_name or "unknown", server_name


def _record_event_identity(state: EventBridgeServerState, payload: dict[str, Any]) -> None:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    state.last_event_type = str(event.get("type") or payload.get("eventType") or "").strip()
    state.last_event_name = str(event.get("name") or payload.get("eventName") or "").strip()


def _event_server_ids(payloads: list[dict[str, Any]]) -> list[str]:
    ids = []
    for item in payloads:
        server_id, _server_name = _server_identity(item)
        if server_id and server_id != "unknown" and server_id not in ids:
            ids.append(server_id)
    return ids


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _plugin_targets(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    targets: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("baseUrl") or "").strip()
        if not url:
            continue
        name = str(item.get("name") or f"OctoHubs {index}").strip()
        targets.append({"name": name, "url": url})
    return targets


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
