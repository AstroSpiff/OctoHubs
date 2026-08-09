"""In-memory manager for active Emby playback sessions."""

from typing import Dict, List, Any, Callable, Optional, Tuple
from threading import Lock
from datetime import datetime, timezone


class EmbyStreamsManager:
    """Manages active playback sessions per Emby server in memory."""

    def __init__(self, now: Optional[Callable[[], datetime]] = None):
        self._last_updates: Dict[str, datetime] = {}
        self._last_refresh_attempts: Dict[str, datetime] = {}
        self._last_errors: Dict[str, Any] = {}
        self._last_events: Dict[str, Dict[str, Any]] = {}
        self._stale_servers: Dict[str, str] = {}
        self._refresh_locks: Dict[str, Lock] = {}
        self._streams: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = Lock()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _current_time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current

    def _current_iso(self) -> str:
        return self._current_time().isoformat()

    def _get_refresh_lock(self, server_id: str) -> Lock:
        with self._lock:
            lock = self._refresh_locks.get(server_id)
            if lock is None:
                lock = Lock()
                self._refresh_locks[server_id] = lock
            return lock

    def get_streams(self, server_id: str) -> List[Dict[str, Any]]:
        """Get active streams for a server."""
        with self._lock:
            return list(self._streams.get(server_id, []))

    def get_error(self, server_id: str):
        """Get the latest refresh error for a server, if any."""
        with self._lock:
            return self._last_errors.get(server_id)

    def add_stream(self, server_id: str, session_data: Dict[str, Any]) -> None:
        """Add or update a stream when playback starts."""
        with self._lock:
            if server_id not in self._streams:
                self._streams[server_id] = []

            # Extract session ID
            session_id = session_data.get("session_id") or session_data.get("Id")
            if not session_id:
                return

            # Remove existing session with same ID
            self._streams[server_id] = [
                s for s in self._streams[server_id]
                if (s.get("session_id") or s.get("Id")) != session_id
            ]

            # Add updated session
            session_data["_last_update"] = self._current_iso()
            self._streams[server_id].append(session_data)
            self._last_updates[server_id] = self._current_time()
            self._last_refresh_attempts[server_id] = self._current_time()
            self._last_errors.pop(server_id, None)
            self._stale_servers.pop(server_id, None)

    def remove_stream(self, server_id: str, session_id: str) -> None:
        """Remove a stream when playback stops."""
        with self._lock:
            if server_id not in self._streams:
                return

            self._streams[server_id] = [
                s for s in self._streams[server_id]
                if (s.get("session_id") or s.get("Id")) != session_id
            ]
            current = self._current_time()
            self._last_updates[server_id] = current
            self._last_refresh_attempts[server_id] = current
            self._last_errors.pop(server_id, None)
            self._stale_servers.pop(server_id, None)

    def update_stream(self, server_id: str, session_id: str, data: Dict[str, Any]) -> None:
        """Update stream progress/state."""
        with self._lock:
            if server_id not in self._streams:
                return

            for stream in self._streams[server_id]:
                if (stream.get("session_id") or stream.get("Id")) == session_id:
                    stream.update(data)
                    stream["_last_update"] = self._current_iso()
                    current = self._current_time()
                    self._last_updates[server_id] = current
                    self._last_refresh_attempts[server_id] = current
                    self._last_errors.pop(server_id, None)
                    self._stale_servers.pop(server_id, None)
                    break

    def clear_server(self, server_id: str) -> None:
        """Clear all streams for a server."""
        with self._lock:
            self._streams.pop(server_id, None)
            self._last_updates.pop(server_id, None)
            self._last_refresh_attempts.pop(server_id, None)
            self._last_errors.pop(server_id, None)
            self._last_events.pop(server_id, None)
            self._stale_servers.pop(server_id, None)
            self._refresh_locks.pop(server_id, None)

    def mark_stale(self, server_id: str, reason: str = "event") -> None:
        """Mark a server stream cache as stale after a WebSocket event."""
        if not server_id:
            return
        with self._lock:
            self._stale_servers[server_id] = reason
            self._last_events[server_id] = {
                "reason": reason,
                "at": self._current_iso(),
            }

    def refresh_from_api(self, server_id: str, streams: List[Dict[str, Any]]) -> None:
        """
        Refresh streams from API call (fallback for webhook misses).
        Used during initial load or when webhooks are not configured.
        """
        with self._lock:
            now = self._current_time()
            now_iso = now.isoformat()
            # Mark all as updated
            for stream in streams:
                stream["_last_update"] = now_iso
            self._streams[server_id] = streams
            self._last_updates[server_id] = now
            self._last_refresh_attempts[server_id] = now
            self._last_errors.pop(server_id, None)
            self._stale_servers.pop(server_id, None)

    def record_refresh_error(self, server_id: str, error: Any) -> None:
        """Store an API refresh error without discarding the last valid streams."""
        with self._lock:
            self._last_refresh_attempts[server_id] = self._current_time()
            self._last_errors[server_id] = error
            self._stale_servers.pop(server_id, None)

    def refresh_server(
        self,
        server: Dict[str, Any],
        fetch_sessions: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[Any]]],
        *,
        max_age_seconds: int = 5,
        force: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        """Refresh a server via API only when the shared cache needs it."""
        server_id = str((server or {}).get("id") or "")
        if not server_id:
            return [], "Server id mancante"

        if not force and not self.is_stale(server_id, max_age_seconds):
            return self.get_streams(server_id), self.get_error(server_id)

        refresh_lock = self._get_refresh_lock(server_id)
        with refresh_lock:
            if not force and not self.is_stale(server_id, max_age_seconds):
                return self.get_streams(server_id), self.get_error(server_id)

            streams, error = fetch_sessions(server)
            if error is None:
                self.refresh_from_api(server_id, streams or [])
            else:
                self.record_refresh_error(server_id, error)
            return self.get_streams(server_id), error

    def is_stale(self, server_id: str, max_age_seconds: int) -> bool:
        """Check if the data for a server is stale (needs API refresh)."""
        with self._lock:
            if server_id in self._stale_servers:
                return True

            last_attempt = self._last_refresh_attempts.get(server_id)
            if not last_attempt:
                return True  # Never updated, so it's stale

            now = self._current_time()
            age = (now - last_attempt).total_seconds()
            return age > max_age_seconds


# Global singleton
_streams_manager = EmbyStreamsManager()


def get_streams_manager() -> EmbyStreamsManager:
    """Get the global streams manager instance."""
    return _streams_manager
