"""In-memory registry for Emby Event Bridge transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from emby_runtime.event_bridge_payloads import event_bridge_payloads
from emby_runtime.event_bridge_settings import build_plugin_settings_payload


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
            "received_count": self.received_count,
        }


class EventBridgeConnectionManager:
    def __init__(self):
        self._servers: dict[str, EventBridgeServerState] = {}
        self._websocket_servers: dict[int, str] = {}

    async def register(self, websocket: Any, hello: dict[str, Any] | None = None) -> EventBridgeServerState:
        hello = hello or {}
        server_id, server_name = _server_identity(hello)
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
        return state

    async def disconnect(self, websocket: Any) -> None:
        server_id = self._websocket_servers.pop(id(websocket), None)
        if not server_id:
            return
        state = self._servers.get(server_id)
        if state and state.websocket is websocket:
            state.connected = False
            state.websocket = None
            state.last_seen_at = _utc_now()

    async def push_configuration(self, server_id: str | None, settings: dict[str, Any]) -> int:
        payload = {
            "type": "configure",
            "sentAt": _utc_now(),
            "settings": build_plugin_settings_payload(settings),
        }
        pushed = 0
        for state in self._target_states(server_id):
            websocket = state.websocket
            if websocket is None:
                continue
            await websocket.send_json(payload)
            state.last_seen_at = _utc_now()
            pushed += 1
        return pushed

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
            self._servers[server_id] = state

    def record_websocket_event(self, websocket: Any, payload: dict[str, Any]) -> None:
        server_id = self._websocket_servers.get(id(websocket))
        for item in event_bridge_payloads(payload):
            event_server_id, event_server_name = _server_identity(item)
            key = event_server_id if event_server_id != "unknown" else server_id or event_server_id
            state = self._servers.get(key) or EventBridgeServerState(server_id=key)
            state.server_name = event_server_name or state.server_name
            state.transport = "websocket"
            state.connected = True
            state.websocket = websocket
            state.last_seen_at = _utc_now()
            state.last_event_at = state.last_seen_at
            state.received_count += 1
            self._servers[key] = state

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
