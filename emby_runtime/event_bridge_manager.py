"""In-memory registry for Emby Event Bridge transports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Any, Awaitable, cast
from uuid import uuid4

from core.log_sanitization import format_exception_for_log
from core.configuration_redaction import public_connection_url
from core.log_sanitization import sanitize_text_for_log
from emby_runtime.event_bridge_limits import bounded_event_bridge_text
from emby_runtime.event_bridge_payloads import event_bridge_payloads
from emby_runtime.event_bridge_settings import build_plugin_settings_payload, event_bridge_settings_from_plugin_payload

logger = logging.getLogger(__name__)

EVENT_BRIDGE_UPDATED_MESSAGE = "OctoHubsEventBridgeUpdated"
EVENT_BRIDGE_SEND_TIMEOUT_SECONDS = 5.0


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
    generation: int = 0
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
            "last_config_ack_error": sanitize_text_for_log(self.last_config_ack_error),
            "last_config_message_id": self.last_config_message_id,
            "last_config_ack_message_id": self.last_config_ack_message_id,
            "last_plugin_settings_at": self.last_plugin_settings_at,
            "plugin_settings": dict(self.plugin_settings),
            "plugin_target_count": self.plugin_target_count,
            "plugin_targets": [
                {**target, "url": public_connection_url(target.get("url"))}
                for target in self.plugin_targets
            ],
            "last_event_type": self.last_event_type,
            "last_event_name": self.last_event_name,
            "received_count": self.received_count,
            "generation": self.generation,
        }


class EventBridgeConnectionManager:
    def __init__(self):
        self._servers: dict[str, EventBridgeServerState] = {}
        self._websocket_servers: dict[int, tuple[str, int]] = {}
        self._dispatch_locks: dict[str, asyncio.Lock] = {}
        self._accepting = True
        self._shutdown_started = False
        self._shutdown_complete = False

    def _dispatch_lock(self, server_id: str) -> asyncio.Lock:
        return self._dispatch_locks.setdefault(server_id, asyncio.Lock())

    async def register(self, websocket: Any, hello: dict[str, Any] | None = None) -> EventBridgeServerState:
        if not self._accepting:
            raise RuntimeError("Event Bridge manager is shutting down")
        hello = hello or {}
        server_id, server_name = _server_identity(hello)
        async with self._dispatch_lock(server_id):
            if not self._accepting:
                raise RuntimeError("Event Bridge manager is shutting down")
            return await self._register_unlocked(websocket, hello, server_id, server_name)

    async def _register_unlocked(
        self,
        websocket: Any,
        hello: dict[str, Any],
        server_id: str,
        server_name: str,
    ) -> EventBridgeServerState:
        previous = self._websocket_servers.get(id(websocket))
        previous_server_id = previous[0] if previous else None
        if previous_server_id and previous_server_id != server_id:
            disconnected_server_id = self._detach_websocket(websocket)
            if disconnected_server_id:
                self._publish_update([disconnected_server_id], "disconnected")
        now = _utc_now()
        state = self._servers.get(server_id) or EventBridgeServerState(server_id=server_id)
        previous_socket = state.websocket
        state.generation += 1
        state.server_name = server_name or state.server_name
        state.plugin_version = str(hello.get("pluginVersion") or hello.get("version") or state.plugin_version or "")
        state.transport = "websocket"
        state.connected = True
        state.connected_at = now
        state.last_seen_at = now
        state.websocket = websocket
        self._servers[server_id] = state
        self._websocket_servers[id(websocket)] = (server_id, state.generation)
        if previous_socket is not None and previous_socket is not websocket:
            close = getattr(previous_socket, "close", None)
            if callable(close):
                try:
                    await asyncio.wait_for(
                        cast(Awaitable[Any], close(code=1012)),
                        timeout=EVENT_BRIDGE_SEND_TIMEOUT_SECONDS,
                    )
                except Exception:
                    pass
        if not self._accepting:
            self._detach_websocket(websocket)
            raise RuntimeError("Event Bridge manager is shutting down")
        self._publish_update([server_id], "connected")
        return state

    @asynccontextmanager
    async def websocket_dispatch(self, websocket: Any):
        """Fence one frame's side effects against socket replacement."""
        if not self._accepting:
            yield False
            return
        ownership = self._websocket_servers.get(id(websocket))
        if not ownership:
            yield False
            return
        server_id, generation = ownership
        async with self._dispatch_lock(server_id):
            current = self._servers.get(server_id)
            yield bool(
                current
                and current.websocket is websocket
                and current.generation == generation
                and self._websocket_servers.get(id(websocket)) == ownership
            )

    async def disconnect(self, websocket: Any) -> None:
        server_id = self._detach_websocket(websocket)
        if server_id:
            self._publish_update([server_id], "disconnected")

    async def shutdown(self) -> None:
        """Close transports and discard every event-loop-bound primitive."""
        self._shutdown_started = True
        self._accepting = False
        # Every registration/dispatch owns its per-server lock. Crossing each
        # existing lock after fencing admission guarantees that no waiter can
        # publish a socket after the shutdown snapshot.
        for dispatch_lock in list(self._dispatch_locks.values()):
            async with dispatch_lock:
                pass
        websockets = {
            id(state.websocket): state.websocket
            for state in self._servers.values()
            if state.websocket is not None
        }
        self._websocket_servers.clear()
        self._servers.clear()
        self._dispatch_locks.clear()

        async def close(websocket: Any) -> None:
            callback = getattr(websocket, "close", None)
            if not callable(callback):
                return
            try:
                await asyncio.wait_for(
                    cast(Awaitable[Any], callback(code=1001)),
                    timeout=EVENT_BRIDGE_SEND_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.debug("Event Bridge transport close failed during shutdown")

        await asyncio.gather(*(close(websocket) for websocket in websockets.values()))
        self._shutdown_complete = True

    async def close_server_connection(self, server_id: str, code: int = 1008) -> bool:
        """Close the current transport after a credential rotation."""
        if not self._accepting:
            return False
        server_key = str(server_id or "").strip()
        async with self._dispatch_lock(server_key):
            if not self._accepting:
                return False
            state = self._servers.get(server_key)
            websocket = state.websocket if state else None
            if websocket is None:
                return False
            try:
                await asyncio.wait_for(
                    websocket.close(code=code),
                    timeout=EVENT_BRIDGE_SEND_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.debug("Event Bridge close timed out or failed for server %s", server_key)
            finally:
                detached_server_id = self._detach_websocket(websocket)
                if detached_server_id:
                    self._publish_update([detached_server_id], "credential_rotated")
            return True

    def websocket_is_current(self, websocket: Any) -> bool:
        """Return whether this socket still owns its registered generation."""
        ownership = self._websocket_servers.get(id(websocket))
        if not ownership:
            return False
        server_id, generation = ownership
        state = self._servers.get(server_id)
        return bool(
            state
            and state.websocket is websocket
            and state.generation == generation
        )

    def _detach_websocket(self, websocket: Any) -> str | None:
        """Remove only the state still owned by this exact WebSocket instance."""
        ownership = self._websocket_servers.pop(id(websocket), None)
        if not ownership:
            return None
        server_id, generation = ownership
        state = self._servers.get(server_id)
        if state and state.websocket is websocket and state.generation == generation:
            state.connected = False
            state.websocket = None
            state.last_seen_at = _utc_now()
            return server_id
        return None

    async def push_configuration(self, server_id: str | None, settings: dict[str, Any]) -> int:
        async def push_one(state: EventBridgeServerState) -> bool:
            async with self._dispatch_lock(state.server_id):
                current = self._servers.get(state.server_id)
                if not self._accepting or current is not state:
                    return False
                websocket = state.websocket
                if websocket is None:
                    return False
                generation = state.generation
                now = _utc_now()
                message_id = f"cfg-{state.server_id}-{uuid4().hex}"
                previous_delivery = {
                    "last_seen_at": state.last_seen_at,
                    "last_config_sent_at": state.last_config_sent_at,
                    "last_config_transport": state.last_config_transport,
                    "last_config_message_id": state.last_config_message_id,
                    "last_config_ack_status": state.last_config_ack_status,
                    "last_config_ack_error": state.last_config_ack_error,
                }
                payload = {
                    "type": "configure",
                    "id": message_id,
                    "sentAt": now,
                    "settings": build_plugin_settings_payload(settings),
                }
                # Publish ownership before send_json: test transports and some
                # adapters can synchronously deliver an ACK from inside send.
                state.last_seen_at = now
                state.last_config_sent_at = now
                state.last_config_transport = "websocket"
                state.last_config_message_id = message_id
                state.last_config_ack_status = "pending"
                state.last_config_ack_error = ""
                self._publish_update([state.server_id], "configuration_sent")
                try:
                    await asyncio.wait_for(
                        websocket.send_json(payload),
                        timeout=EVENT_BRIDGE_SEND_TIMEOUT_SECONDS,
                    )
                except BaseException as exc:
                    ack_received, rolled_back = self._rollback_configuration_send(
                        state,
                        message_id,
                        previous_delivery,
                    )
                    if isinstance(exc, Exception):
                        if not ack_received:
                            self._detach_websocket(websocket)
                            self._publish_update([state.server_id], "configuration_send_failed")
                            return False
                        return True
                    if rolled_back:
                        self._publish_update([state.server_id], "configuration_send_cancelled")
                    raise
                current = self._servers.get(state.server_id)
                if current is not state or state.websocket is not websocket or state.generation != generation:
                    return False
                return True

        outcomes = await asyncio.gather(
            *(push_one(state) for state in self._target_states(server_id)),
            return_exceptions=False,
        )
        return sum(1 for pushed in outcomes if pushed)

    def _rollback_configuration_send(
        self,
        state: EventBridgeServerState,
        message_id: str,
        previous_delivery: dict[str, Any],
    ) -> tuple[bool, bool]:
        """Restore delivery diagnostics only while this failed send still owns them."""
        ack_received = state.last_config_ack_message_id == message_id
        current = self._servers.get(state.server_id)
        if current is not state or state.last_config_message_id != message_id or ack_received:
            return ack_received, False
        for field_name, value in previous_delivery.items():
            setattr(state, field_name, value)
        return False, True

    def record_config_ack(self, websocket: Any, payload: dict[str, Any]) -> EventBridgeServerState | None:
        if not self._accepting:
            return None
        ownership = self._websocket_servers.get(id(websocket))
        if not ownership:
            return None
        server_id, generation = ownership

        now = _utc_now()
        state = self._servers.get(server_id)
        if not state or state.websocket is not websocket or state.generation != generation:
            return None
        ack_message_id = str(payload.get("id") or payload.get("configureId") or "").strip()
        if not ack_message_id or ack_message_id != state.last_config_message_id:
            return None
        state.last_seen_at = now
        state.last_config_ack_at = now
        state.last_config_transport = "websocket"
        state.last_config_ack_message_id = ack_message_id
        ok = payload.get("ok")
        applied = payload.get("applied")
        state.last_config_ack_status = "applied" if ok is not False and applied is not False else "error"
        state.last_config_ack_error = "" if state.last_config_ack_status == "applied" else str(payload.get("error") or "").strip()
        self._servers[server_id] = state
        self._publish_update([server_id], "configuration_acknowledged")
        return state

    def record_plugin_configuration_response(self, server_id: str | None, response: dict[str, Any] | None) -> None:
        """Record settings returned by the Emby plugin configuration endpoint."""
        if not self._accepting or not server_id or not isinstance(response, dict):
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
        if not self._accepting:
            return
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

    def record_websocket_event(self, websocket: Any, payload: dict[str, Any]) -> bool:
        if not self._accepting:
            return False
        ownership = self._websocket_servers.get(id(websocket))
        if not ownership:
            return False
        server_id, generation = ownership
        current_state = self._servers.get(server_id)
        if not current_state or current_state.websocket is not websocket or current_state.generation != generation:
            return False
        payloads = event_bridge_payloads(payload)
        updated_server_ids: list[str] = []
        for item in payloads:
            event_server_id, event_server_name = _server_identity(item)
            key = server_id or event_server_id
            state = current_state
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
        return True

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
        except Exception as exc:
            logger.debug(
                "Impossibile pubblicare aggiornamento Event Bridge:\n%s",
                format_exception_for_log(exc),
            )

    def retire_if_idle(self) -> bool:
        """Fence an unused manager before installing the next lifespan owner."""
        if self._shutdown_started and not self._shutdown_complete:
            return False
        if (
            self._websocket_servers
            or any(state.websocket is not None for state in self._servers.values())
            or any(lock.locked() for lock in self._dispatch_locks.values())
        ):
            return False
        self._accepting = False
        self._servers.clear()
        self._dispatch_locks.clear()
        self._shutdown_complete = True
        return True


_manager: EventBridgeConnectionManager | None = None


def get_event_bridge_manager() -> EventBridgeConnectionManager:
    global _manager
    if _manager is None:
        _manager = EventBridgeConnectionManager()
    return _manager


def initialize_event_bridge_manager() -> EventBridgeConnectionManager:
    """Install a fresh manager for the current application lifespan."""
    global _manager
    if _manager is not None and not (
        _manager._shutdown_complete or _manager.retire_if_idle()
    ):
        raise RuntimeError("Event Bridge manager ancora attivo durante la riapertura")
    _manager = EventBridgeConnectionManager()
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
    raw_event = payload.get("event")
    event: dict[str, Any] = raw_event if isinstance(raw_event, dict) else {}
    state.last_event_type = bounded_event_bridge_text(event.get("type") or payload.get("eventType"))
    state.last_event_name = bounded_event_bridge_text(event.get("name") or payload.get("eventName"))


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
