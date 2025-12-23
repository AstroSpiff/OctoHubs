"""
Emby Streams Manager - In-memory storage for active playback sessions
Updated via webhooks for real-time updates with minimal overhead
"""
from typing import Dict, List, Any
from threading import Lock
from datetime import datetime
from time import time


class EmbyStreamsManager:
    """Manages active playback sessions per Emby server in memory."""

    def __init__(self):
        self._streams: Dict[str, List[Dict[str, Any]]] = {}
        self._last_update: Dict[str, float] = {}
        self._lock = Lock()

    def get_streams(self, server_id: str) -> List[Dict[str, Any]]:
        """Get active streams for a server."""
        with self._lock:
            return list(self._streams.get(server_id, []))

    def add_stream(self, server_id: str, session_data: Dict[str, Any]) -> None:
        """Add or update a stream when playback starts."""
        with self._lock:
            if server_id not in self._streams:
                self._streams[server_id] = []

            # Extract session ID
            session_id = session_data.get("Id")
            if not session_id:
                return

            # Remove existing session with same ID
            self._streams[server_id] = [
                s for s in self._streams[server_id]
                if s.get("Id") != session_id
            ]

            # Add updated session
            session_data["_last_update"] = datetime.now().isoformat()
            self._streams[server_id].append(session_data)
            self._last_update[server_id] = time()

    def remove_stream(self, server_id: str, session_id: str) -> None:
        """Remove a stream when playback stops."""
        with self._lock:
            if server_id not in self._streams:
                return

            self._streams[server_id] = [
                s for s in self._streams[server_id]
                if s.get("Id") != session_id
            ]
            self._last_update[server_id] = time()

    def update_stream(self, server_id: str, session_id: str, data: Dict[str, Any]) -> None:
        """Update stream progress/state."""
        with self._lock:
            if server_id not in self._streams:
                return

            for stream in self._streams[server_id]:
                if stream.get("Id") == session_id:
                    stream.update(data)
                    stream["_last_update"] = datetime.now().isoformat()
                    self._last_update[server_id] = time()
                    break

    def clear_server(self, server_id: str) -> None:
        """Clear all streams for a server."""
        with self._lock:
            self._streams.pop(server_id, None)
            self._last_update.pop(server_id, None)

    def refresh_from_api(self, server_id: str, streams: List[Dict[str, Any]]) -> None:
        """
        Refresh streams from API call (fallback for webhook misses).
        Used during initial load or when webhooks are not configured.
        """
        with self._lock:
            # Mark all as updated
            for stream in streams:
                stream["_last_update"] = datetime.now().isoformat()
            self._streams[server_id] = streams
            self._last_update[server_id] = time()

    def is_stale(self, server_id: str, max_age_seconds: int) -> bool:
        """Return True if streams are stale or never updated."""
        with self._lock:
            last_update = self._last_update.get(server_id)
        if not last_update:
            return True
        return (time() - last_update) > max_age_seconds


# Global singleton
_streams_manager = EmbyStreamsManager()


def get_streams_manager() -> EmbyStreamsManager:
    """Get the global streams manager instance."""
    return _streams_manager
