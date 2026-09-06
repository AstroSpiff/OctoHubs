"""
Emby WebSocket Manager - Persistent connections to Emby servers
Handles real-time events from Emby servers without polling.
"""
import json
import threading
import time
import websocket
from typing import Dict, Callable, Optional, Any, List
import logging

from core.log_sanitization import format_exception_for_log, sanitize_diagnostic_text, sanitize_url_for_log
from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread_confirmed,
)

logger = logging.getLogger(__name__)


_NON_STREAM_EVENT_TYPES = {
    "ConnectionEstablished",
    "ConnectionClosed",
    "RefreshProgress",
    "ScheduledTasksInfo",
    "ScheduledTasksInfoStart",
    "ScheduledTasksInfoStop",
}


def _is_stream_session_event(event_data: Dict[str, Any]) -> bool:
    """Return True when an Emby WebSocket event can affect active streams."""
    message_type = str((event_data or {}).get("MessageType") or "")
    if not message_type or message_type in _NON_STREAM_EVENT_TYPES:
        return False
    if message_type == "Sessions":
        return True
    lowered = message_type.lower()
    return "playback" in lowered or "session" in lowered or _has_session_identity(event_data)


def _connection_worker_is_active(connection: Any) -> bool:
    thread = getattr(connection, "ws_thread", None)
    if thread is not None:
        return bool(thread.is_alive())
    return bool(
        getattr(connection, "started", False)
        and not getattr(connection, "stopped", False)
    )


def _has_session_identity(value: Any) -> bool:
    if isinstance(value, dict):
        for key in ("SessionId", "SessionID", "Session", "SessionInfo"):
            candidate = value.get(key)
            if isinstance(candidate, dict):
                if _has_session_identity(candidate):
                    return True
            elif str(candidate or "").strip():
                return True
        data = value.get("Data")
        if _has_session_identity(data):
            return True
        play_state = value.get("PlayState")
        if _has_session_identity(play_state):
            return True
        return False
    if isinstance(value, list):
        return any(_has_session_identity(item) for item in value)
    return False


class EmbyWebSocketConnection:
    """Manages a single persistent WebSocket connection to an Emby server."""

    # Connection states
    STATE_DISCONNECTED = "disconnected"
    STATE_CONNECTING = "connecting"
    STATE_CONNECTED = "connected"
    STATE_RECONNECTING = "reconnecting"

    def __init__(self, server_id: str, server_url: str, api_key: str, event_callback: Callable):
        """
        Initialize WebSocket connection for an Emby server.

        Args:
            server_id: Unique identifier for the server
            server_url: Base URL of Emby server (e.g., "http://192.168.1.100:8096")
            api_key: Emby API key for authentication
            event_callback: Function to call when events are received
        """
        self.server_id = server_id
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.event_callback = event_callback

        # WebSocket connection
        self.ws = None
        self.ws_thread = None
        self.state = self.STATE_DISCONNECTED

        # Reconnection logic
        self.should_reconnect = True
        self.reconnect_delay = 1  # Start with 1 second
        self.max_reconnect_delay = 60  # Max 60 seconds
        self.last_connection_time = 0
        self._reconnect_wake = threading.Event()

        # Statistics
        self.connection_attempts = 0
        self.successful_connections = 0
        self.last_event_time = 0

        # Device ID for Emby
        self.device_id = f"OctoHubs_{server_id[:8]}"

    def get_websocket_url(self) -> str:
        """Build WebSocket URL for Emby server."""
        # Convert http:// to ws:// and https:// to wss://
        ws_url = self.server_url.replace('http://', 'ws://').replace('https://', 'wss://')
        return f"{ws_url}/embywebsocket?api_key={self.api_key}&deviceId={self.device_id}"

    def start(self):
        """Start WebSocket connection in a separate thread."""
        if self.ws_thread and self.ws_thread.is_alive():
            logger.warning("[WS:%s] Connection already running", sanitize_diagnostic_text(self.server_id))
            return

        self.should_reconnect = True
        self._reconnect_wake.clear()
        thread = threading.Thread(target=self._run, daemon=True)
        self.ws_thread = thread

        def rollback_unstarted() -> None:
            if self.ws_thread is thread:
                self.ws_thread = None
            self.should_reconnect = False
            self._reconnect_wake.set()

        start_owned_thread_confirmed(
            thread,
            rollback_unstarted=rollback_unstarted,
            context=f"Emby WebSocket {self.server_id}",
        )
        logger.info("[WS:%s] WebSocket thread started", sanitize_diagnostic_text(self.server_id))

    def stop(self):
        """Stop WebSocket connection gracefully."""
        logger.info("[WS:%s] Stopping WebSocket connection", sanitize_diagnostic_text(self.server_id))
        self.should_reconnect = False
        self._reconnect_wake.set()

        if self.ws:
            try:
                self._send_sessions_stop()
                self.ws.close()
            except Exception as e:
                logger.error("[WS:%s] Error closing WebSocket: %s", sanitize_diagnostic_text(self.server_id), sanitize_diagnostic_text(e))

        self.state = self.STATE_DISCONNECTED

    def wait_stopped(self, timeout_seconds: float | None = None) -> bool:
        """Wait for the connection thread without blocking indefinitely."""
        thread = self.ws_thread
        return join_owned_thread(thread, timeout_seconds)

    def _run(self):
        """Main WebSocket connection loop with auto-reconnect."""
        while self.should_reconnect:
            try:
                self._connect()
            except BaseException as exc:
                log_lifecycle_exception_safely(
                    logger,
                    f"[WS:{sanitize_diagnostic_text(self.server_id)}] Connection error: %s",
                    exc,
                )
                self.state = self.STATE_RECONNECTING
            finally:
                if self.should_reconnect and self.state != self.STATE_CONNECTED:
                    try:
                        self._handle_reconnect()
                    except BaseException as exc:
                        log_lifecycle_exception_safely(
                            logger,
                            f"[WS:{sanitize_diagnostic_text(self.server_id)}] Reconnect error: %s",
                            exc,
                        )

    def _connect(self):
        """Establish WebSocket connection and listen for events."""
        self.state = self.STATE_CONNECTING
        self.connection_attempts += 1

        logger.info("[WS:%s] Connecting to %s", sanitize_diagnostic_text(self.server_id), sanitize_url_for_log(self.get_websocket_url()))

        # Create WebSocket with callbacks
        self.ws = websocket.WebSocketApp(
            self.get_websocket_url(),
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )

        # Run forever (blocking call)
        self.ws.run_forever()

    def _on_open(self, ws):
        """Called when WebSocket connection is established."""
        self.state = self.STATE_CONNECTED
        self.successful_connections += 1
        self.last_connection_time = time.time()
        self.reconnect_delay = 1  # Reset reconnect delay on successful connection

        logger.info("[WS:%s] Connected successfully (attempt #%s)", sanitize_diagnostic_text(self.server_id), self.connection_attempts)
        self._send_sessions_start()

        # Notify callback about connection
        self._notify_event({
            "MessageType": "ConnectionEstablished",
            "Data": {
                "server_id": self.server_id,
                "connection_time": self.last_connection_time
            }
        })

    def _on_message(self, ws, message):
        """Called when a message is received from Emby."""
        try:
            self.last_event_time = time.time()
            data = json.loads(message)

            message_type = data.get("MessageType")
            logger.debug("[WS:%s] Received event: %s", sanitize_diagnostic_text(self.server_id), sanitize_diagnostic_text(message_type))

            # Add server_id to data for routing
            data["server_id"] = self.server_id

            # Call event callback
            self._notify_event(data)

        except json.JSONDecodeError as exc:
            logger.error("[WS:%s] Invalid JSON:\n%s", sanitize_diagnostic_text(self.server_id), format_exception_for_log(exc))
        except Exception as exc:
            logger.error("[WS:%s] Error processing message:\n%s", sanitize_diagnostic_text(self.server_id), format_exception_for_log(exc))

    def _on_error(self, ws, error):
        """Called when WebSocket encounters an error."""
        logger.error("[WS:%s] Error: %s", sanitize_diagnostic_text(self.server_id), sanitize_diagnostic_text(error))
        self.state = self.STATE_RECONNECTING

    def _on_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection is closed."""
        logger.warning(
            "[WS:%s] Connection closed (code: %s, msg: %s)",
            sanitize_diagnostic_text(self.server_id),
            close_status_code,
            sanitize_diagnostic_text(close_msg),
        )
        self.state = self.STATE_RECONNECTING

        # Notify callback about disconnection
        self._notify_event({
            "MessageType": "ConnectionClosed",
            "Data": {
                "server_id": self.server_id,
                "close_code": close_status_code,
                "close_message": close_msg
            }
        })

    def _handle_reconnect(self):
        """Handle reconnection with exponential backoff."""
        if not self.should_reconnect:
            return

        logger.info("[WS:%s] Reconnecting in %ss...", sanitize_diagnostic_text(self.server_id), self.reconnect_delay)
        if self._reconnect_wake.wait(self.reconnect_delay):
            self._reconnect_wake.clear()
            return

        # Exponential backoff
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

    def _notify_event(self, event_data: Dict):
        """Notify event callback with received data."""
        try:
            self.event_callback(self.server_id, event_data)
        except Exception as exc:
            logger.error("[WS:%s] Error in event callback:\n%s", sanitize_diagnostic_text(self.server_id), format_exception_for_log(exc))

    def _send_sessions_start(self):
        """Subscribe to Emby session updates after connecting."""
        self._send_command({"MessageType": "SessionsStart", "Data": "0,1500"})

    def _send_sessions_stop(self):
        """Unsubscribe from Emby session updates before disconnecting."""
        self._send_command({"MessageType": "SessionsStop"})

    def _send_command(self, payload: Dict[str, Any]) -> bool:
        if not self.ws:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception as exc:
            logger.warning(
                "[WS:%s] Failed sending command %s:\n%s",
                self.server_id,
                payload.get("MessageType"),
                format_exception_for_log(exc),
            )
            return False

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected."""
        return self.state == self.STATE_CONNECTED

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "server_id": self.server_id,
            "state": self.state,
            "connection_attempts": self.connection_attempts,
            "successful_connections": self.successful_connections,
            "last_connection_time": self.last_connection_time,
            "last_event_time": self.last_event_time,
            "uptime": time.time() - self.last_connection_time if self.is_connected() else 0
        }


class EmbyWebSocketManager:
    """Manages multiple WebSocket connections to Emby servers."""

    def __init__(self):
        """Initialize WebSocket manager."""
        self.connections: Dict[str, EmbyWebSocketConnection] = {}
        self.event_handlers: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._event_fence = threading.RLock()
        self._accepting_connections = True

        # Global event callback
        self.global_event_callback: Optional[Callable] = None
        self._global_event_callbacks: List[Callable] = []
        self._stream_session_forwarding_ready = False

        logger.info("[WSManager] Initialized")

    def add_server(self, server_id: str, server_url: str, api_key: str):
        """Add an Emby server and establish WebSocket connection."""
        with self._event_fence:
            with self._lock:
                if not self._accepting_connections:
                    logger.info("[WSManager] Ignoring server %s while stopping", sanitize_diagnostic_text(server_id))
                    return
                existing = self.connections.get(server_id)
                if existing is not None and _connection_worker_is_active(existing):
                    logger.warning("[WSManager] Server %s already connected", sanitize_diagnostic_text(server_id))
                    return
                if existing is not None:
                    existing.stop()
                    self.connections.pop(server_id, None)

                conn = self._build_connection(server_id, server_url, api_key)
                self.connections[server_id] = conn
                try:
                    conn.start()
                except BaseException:
                    if (
                        getattr(conn, "ws_thread", None) is None
                        and self.connections.get(server_id) is conn
                    ):
                        self.connections.pop(server_id, None)
                    raise

            logger.info("[WSManager] Added server %s", sanitize_diagnostic_text(server_id))

    def upsert_server(self, server_id: str, server_url: str, api_key: str) -> bool:
        """Create or replace a server connection when its endpoint changes."""
        normalized_url = str(server_url or "").rstrip("/")
        normalized_key = str(api_key or "")
        if not server_id or not normalized_url or not normalized_key:
            raise ValueError("Server ID, URL e API key sono necessari per il WebSocket Emby.")

        with self._event_fence:
            with self._lock:
                if not self._accepting_connections:
                    logger.info("[WSManager] Ignoring server %s while stopping", sanitize_diagnostic_text(server_id))
                    return False
                existing = self.connections.get(server_id)
                if (
                    existing is not None
                    and existing.server_url == normalized_url
                    and existing.api_key == normalized_key
                    and _connection_worker_is_active(existing)
                ):
                    return False

                if existing is not None:
                    existing.stop()

                connection = self._build_connection(server_id, normalized_url, normalized_key)
                self.connections[server_id] = connection
                try:
                    connection.start()
                except BaseException:
                    if (
                        getattr(connection, "ws_thread", None) is None
                        and self.connections.get(server_id) is connection
                    ):
                        self.connections.pop(server_id, None)
                    raise
        logger.info("[WSManager] Synchronized server %s", sanitize_diagnostic_text(server_id))
        return True

    def start_accepting(self) -> None:
        """Open connection registration for a newly initialized app lifespan."""
        with self._lock:
            self._accepting_connections = True

    def remove_server(self, server_id: str):
        """Remove an Emby server and close WebSocket connection."""
        with self._event_fence:
            with self._lock:
                if server_id not in self.connections:
                    logger.warning("[WSManager] Server %s not found", sanitize_diagnostic_text(server_id))
                    return

                conn = self.connections.pop(server_id)
                conn.stop()

                logger.info("[WSManager] Removed server %s", sanitize_diagnostic_text(server_id))

    def _build_connection(self, server_id: str, server_url: str, api_key: str):
        connection = None

        def owned_callback(callback_server_id: str, event_data: Dict):
            if connection is not None:
                self._handle_owned_event(connection, callback_server_id, event_data)

        connection = EmbyWebSocketConnection(
            server_id=server_id,
            server_url=server_url,
            api_key=api_key,
            event_callback=owned_callback,
        )
        return connection

    def _handle_owned_event(
        self,
        source: EmbyWebSocketConnection,
        server_id: str,
        event_data: Dict,
    ) -> None:
        """Dispatch only while the source still owns this server connection."""
        with self._event_fence:
            with self._lock:
                if self.connections.get(server_id) is not source:
                    logger.debug("[WSManager] Ignored stale event for server %s", sanitize_diagnostic_text(server_id))
                    return
            self._handle_event(server_id, event_data)

    def register_event_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific Emby event type."""
        self.event_handlers[message_type] = handler
        logger.info("[WSManager] Registered handler for %s", sanitize_diagnostic_text(message_type))

    def set_global_callback(self, callback: Callable):
        """Set a global callback for all events."""
        self.global_event_callback = callback

    def add_global_callback(self, callback: Callable):
        """Add a global callback without replacing the primary event router."""
        with self._lock:
            if callback not in self._global_event_callbacks:
                self._global_event_callbacks.append(callback)

    def _handle_event(self, server_id: str, event_data: Dict):
        """Handle events received from any Emby server."""
        message_type = event_data.get("MessageType")

        # Call specific handler if registered
        if message_type in self.event_handlers:
            try:
                self.event_handlers[message_type](server_id, event_data)
            except Exception as exc:
                logger.error("[WSManager] Error in handler for %s:\n%s", sanitize_diagnostic_text(message_type), format_exception_for_log(exc))

        # Call global callback
        if self.global_event_callback:
            try:
                self.global_event_callback(server_id, event_data)
            except Exception as exc:
                logger.error("[WSManager] Error in global callback:\n%s", format_exception_for_log(exc))

        for callback in list(self._global_event_callbacks):
            try:
                callback(server_id, event_data)
            except Exception as exc:
                logger.error("[WSManager] Error in extra global callback:\n%s", format_exception_for_log(exc))

    def get_connection(self, server_id: str) -> Optional[EmbyWebSocketConnection]:
        """Get connection for a specific server."""
        return self.connections.get(server_id)

    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all connections."""
        with self._lock:
            return {
                server_id: conn.get_stats()
                for server_id, conn in self.connections.items()
            }

    def is_server_connected(self, server_id: str) -> bool:
        """Check if a specific server is connected."""
        conn = self.connections.get(server_id)
        return conn.is_connected() if conn else False

    def stop_all(self, timeout_seconds: float = 5.0) -> bool:
        """Stop all WebSocket connections within one shared deadline."""
        logger.info("[WSManager] Stopping all connections")
        with self._event_fence:
            with self._lock:
                self._accepting_connections = False
                connections = list(self.connections.values())
                self.connections.clear()

        for connection in connections:
            connection.stop()

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        stopped = True
        for connection in connections:
            wait_stopped = getattr(connection, "wait_stopped", None)
            if wait_stopped is None:
                continue
            stopped = bool(wait_stopped(max(0.0, deadline - time.monotonic()))) and stopped
        return stopped

    def setup_scan_progress_forwarding(self):
        """
        Setup forwarding di eventi RefreshProgress ai client browser.

        Quando Emby invia RefreshProgress, questo viene inoltrato
        al ScanConnectionManager per broadcast ai client WebSocket.
        """
        # Import lazy per evitare circular dependency
        from emby_runtime.scan_websocket_manager import get_scan_connection_manager
        from app_state import _LIBRARY_SCAN_TRACKER

        def sync_handler(server_id: str, event_data: Dict):
            """Coalesce RefreshProgress from the socket thread by scan job."""
            try:
                data = event_data.get("Data", {})
                library_id = data.get("ItemId")
                progress = data.get("Progress", 0)  # 0-100

                if not library_id:
                    return

                logger.debug("[WSManager] RefreshProgress from %s, library %s: %s%%", sanitize_diagnostic_text(server_id), sanitize_diagnostic_text(library_id), progress)

                # Trova job associati a questo server/library
                matching_jobs = _LIBRARY_SCAN_TRACKER.find_jobs_by_library(server_id, str(library_id))

                if not matching_jobs:
                    logger.debug("[WSManager] No active jobs for server %s, library %s", sanitize_diagnostic_text(server_id), sanitize_diagnostic_text(library_id))
                    return

                # Broadcast a tutti job corrispondenti
                manager = get_scan_connection_manager()
                from app_state import get_app_event_loop

                loop = get_app_event_loop()
                if not loop or not loop.is_running():
                    logger.warning("[WSManager] App event loop not running, cannot forward progress")
                    return

                for job_id in matching_jobs:
                    manager.schedule_broadcast(loop, job_id, {
                        "type": "progress",
                        "job_id": job_id,
                        "library_id": str(library_id),
                        "progress": progress / 100.0,  # Normalizza a 0.0-1.0
                        "message": f"Scanning library {library_id}..."
                    })

                    logger.debug(f"[WSManager] Forwarded progress to job {job_id}: {progress}%")

            except Exception as exc:
                logger.error("[WSManager] Error forwarding RefreshProgress:\n%s", format_exception_for_log(exc))

        # Registra handler per RefreshProgress
        self.register_event_handler("RefreshProgress", sync_handler)
        logger.info("[WSManager] Setup RefreshProgress forwarding to client WebSockets")

    def setup_stream_session_forwarding(self):
        """Mark the shared stream cache stale when playback WebSocket events arrive."""
        with self._lock:
            if self._stream_session_forwarding_ready:
                return
            self._stream_session_forwarding_ready = True

        def sync_handler(server_id: str, event_data: Dict):
            if not _is_stream_session_event(event_data):
                return

            message_type = str(event_data.get("MessageType") or "event")
            try:
                if message_type != "Sessions":
                    from emby_runtime.streams import get_streams_manager

                    get_streams_manager().mark_stale(server_id, f"websocket:{message_type}")
            except Exception as exc:
                logger.error("[WSManager] Error marking stream cache stale for %s:\n%s", sanitize_diagnostic_text(server_id), format_exception_for_log(exc))

            try:
                from emby_runtime.transcode_guard import get_transcode_guard_service

                service = get_transcode_guard_service()
                service.record_playback_event(server_id, event_data)
                service.wake()
            except Exception as exc:
                logger.error("[WSManager] Error waking Transcode Guard for %s:\n%s", sanitize_diagnostic_text(server_id), format_exception_for_log(exc))

        self.add_global_callback(sync_handler)
        logger.info("[WSManager] Setup stream session forwarding to shared stream manager")


# Global singleton instance
_manager_instance = None


def get_websocket_manager() -> EmbyWebSocketManager:
    """Get global WebSocket manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = EmbyWebSocketManager()
    return _manager_instance
