"""
Emby WebSocket Manager - Persistent connections to Emby servers
Handles real-time events from Emby servers without polling.
"""
import asyncio
import json
import threading
import time
import websocket
from typing import Dict, Callable, Optional, Any
import logging

logger = logging.getLogger(__name__)


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

        # Statistics
        self.connection_attempts = 0
        self.successful_connections = 0
        self.last_event_time = 0

        # Device ID for Emby
        self.device_id = f"OctoHub_{server_id[:8]}"

    def get_websocket_url(self) -> str:
        """Build WebSocket URL for Emby server."""
        # Convert http:// to ws:// and https:// to wss://
        ws_url = self.server_url.replace('http://', 'ws://').replace('https://', 'wss://')
        return f"{ws_url}/embywebsocket?api_key={self.api_key}&deviceId={self.device_id}"

    def start(self):
        """Start WebSocket connection in a separate thread."""
        if self.ws_thread and self.ws_thread.is_alive():
            logger.warning(f"[WS:{self.server_id}] Connection already running")
            return

        self.should_reconnect = True
        self.ws_thread = threading.Thread(target=self._run, daemon=True)
        self.ws_thread.start()
        logger.info(f"[WS:{self.server_id}] WebSocket thread started")

    def stop(self):
        """Stop WebSocket connection gracefully."""
        logger.info(f"[WS:{self.server_id}] Stopping WebSocket connection")
        self.should_reconnect = False

        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                logger.error(f"[WS:{self.server_id}] Error closing WebSocket: {e}")

        self.state = self.STATE_DISCONNECTED

    def _run(self):
        """Main WebSocket connection loop with auto-reconnect."""
        while self.should_reconnect:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"[WS:{self.server_id}] Connection error: {e}")
                self.state = self.STATE_RECONNECTING
                self._handle_reconnect()

    def _connect(self):
        """Establish WebSocket connection and listen for events."""
        self.state = self.STATE_CONNECTING
        self.connection_attempts += 1

        logger.info(f"[WS:{self.server_id}] Connecting to {self.get_websocket_url()}")

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

        logger.info(f"[WS:{self.server_id}] ✓ Connected successfully (attempt #{self.connection_attempts})")

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
            logger.debug(f"[WS:{self.server_id}] Received: {message_type}")

            # Add server_id to data for routing
            data["server_id"] = self.server_id

            # Call event callback
            self._notify_event(data)

        except json.JSONDecodeError as e:
            logger.error(f"[WS:{self.server_id}] Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"[WS:{self.server_id}] Error processing message: {e}")

    def _on_error(self, ws, error):
        """Called when WebSocket encounters an error."""
        logger.error(f"[WS:{self.server_id}] Error: {error}")
        self.state = self.STATE_RECONNECTING

    def _on_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection is closed."""
        logger.warning(f"[WS:{self.server_id}] Connection closed (code: {close_status_code}, msg: {close_msg})")
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

        logger.info(f"[WS:{self.server_id}] Reconnecting in {self.reconnect_delay}s...")
        time.sleep(self.reconnect_delay)

        # Exponential backoff
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

    def _notify_event(self, event_data: Dict):
        """Notify event callback with received data."""
        try:
            self.event_callback(self.server_id, event_data)
        except Exception as e:
            logger.error(f"[WS:{self.server_id}] Error in event callback: {e}")

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

        # Global event callback
        self.global_event_callback: Optional[Callable] = None

        logger.info("[WSManager] Initialized")

    def add_server(self, server_id: str, server_url: str, api_key: str):
        """Add an Emby server and establish WebSocket connection."""
        with self._lock:
            if server_id in self.connections:
                logger.warning(f"[WSManager] Server {server_id} already connected")
                return

            # Create connection
            conn = EmbyWebSocketConnection(
                server_id=server_id,
                server_url=server_url,
                api_key=api_key,
                event_callback=self._handle_event
            )

            self.connections[server_id] = conn
            conn.start()

            logger.info(f"[WSManager] Added server {server_id}")

    def remove_server(self, server_id: str):
        """Remove an Emby server and close WebSocket connection."""
        with self._lock:
            if server_id not in self.connections:
                logger.warning(f"[WSManager] Server {server_id} not found")
                return

            conn = self.connections[server_id]
            conn.stop()
            del self.connections[server_id]

            logger.info(f"[WSManager] Removed server {server_id}")

    def register_event_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific Emby event type."""
        self.event_handlers[message_type] = handler
        logger.info(f"[WSManager] Registered handler for {message_type}")

    def set_global_callback(self, callback: Callable):
        """Set a global callback for all events."""
        self.global_event_callback = callback

    def _handle_event(self, server_id: str, event_data: Dict):
        """Handle events received from any Emby server."""
        message_type = event_data.get("MessageType")

        # Call specific handler if registered
        if message_type in self.event_handlers:
            try:
                self.event_handlers[message_type](server_id, event_data)
            except Exception as e:
                logger.error(f"[WSManager] Error in handler for {message_type}: {e}")

        # Call global callback
        if self.global_event_callback:
            try:
                self.global_event_callback(server_id, event_data)
            except Exception as e:
                logger.error(f"[WSManager] Error in global callback: {e}")

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

    def stop_all(self):
        """Stop all WebSocket connections."""
        logger.info("[WSManager] Stopping all connections")
        with self._lock:
            for conn in self.connections.values():
                conn.stop()
            self.connections.clear()

    def setup_scan_progress_forwarding(self):
        """
        Setup forwarding di eventi RefreshProgress ai client browser.

        Quando Emby invia RefreshProgress, questo viene inoltrato
        al ScanConnectionManager per broadcast ai client WebSocket.
        """
        # Import lazy per evitare circular dependency
        from scan_websocket_manager import get_scan_connection_manager
        from app import _LIBRARY_SCAN_TRACKER

        async def forward_refresh_progress(server_id: str, event_data: Dict):
            """Forward evento RefreshProgress ai client sottoscritti."""
            try:
                data = event_data.get("Data", {})
                library_id = data.get("ItemId")
                progress = data.get("Progress", 0)  # 0-100

                if not library_id:
                    return

                logger.debug(f"[WSManager] RefreshProgress from {server_id}, library {library_id}: {progress}%")

                # Trova job associati a questo server/library
                matching_jobs = _LIBRARY_SCAN_TRACKER.find_jobs_by_library(server_id, str(library_id))

                if not matching_jobs:
                    logger.debug(f"[WSManager] No active jobs for server {server_id}, library {library_id}")
                    return

                # Broadcast a tutti job corrispondenti
                manager = get_scan_connection_manager()

                for job_id in matching_jobs:
                    await manager.broadcast_to_job(job_id, {
                        "type": "progress",
                        "job_id": job_id,
                        "library_id": str(library_id),
                        "progress": progress / 100.0,  # Normalizza a 0.0-1.0
                        "message": f"Scanning library {library_id}..."
                    })

                    logger.debug(f"[WSManager] Forwarded progress to job {job_id}: {progress}%")

            except Exception as e:
                logger.error(f"[WSManager] Error forwarding RefreshProgress: {e}")

        def sync_handler(server_id: str, event_data: Dict):
            """Handler sincrono che crea task async per forward."""
            try:
                # Crea task async in event loop corrente
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(forward_refresh_progress(server_id, event_data))
                else:
                    # Fallback se non c'è event loop
                    logger.warning("[WSManager] No event loop running, cannot forward progress")
            except Exception as e:
                logger.error(f"[WSManager] Error creating async task: {e}")

        # Registra handler per RefreshProgress
        self.register_event_handler("RefreshProgress", sync_handler)
        logger.info("[WSManager] Setup RefreshProgress forwarding to client WebSockets")


# Global singleton instance
_manager_instance = None


def get_websocket_manager() -> EmbyWebSocketManager:
    """Get global WebSocket manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = EmbyWebSocketManager()
    return _manager_instance
