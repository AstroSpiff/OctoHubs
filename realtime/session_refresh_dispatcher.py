"""Coalescing worker for blocking Emby Sessions refreshes."""

from __future__ import annotations

import threading
import logging
import time
from collections import deque
from typing import Any, Callable

from core.log_sanitization import format_exception_for_log

logger = logging.getLogger(__name__)


class SessionRefreshDispatcher:
    def __init__(self, callback: Callable[[str, Any], None], max_workers: int = 2):
        self._callback = callback
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._pending: dict[str, Any] = {}
        self._running: set[str] = set()
        self._ready: deque[str] = deque()
        self._closed = False
        self._workers = [
            threading.Thread(
                target=self._worker,
                name=f"emby-sessions-{index + 1}",
                daemon=True,
            )
            for index in range(max(1, int(max_workers)))
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, server_id: str, data: Any) -> bool:
        with self._condition:
            if self._closed:
                return False
            self._pending[server_id] = data
            if server_id in self._running:
                return True
            self._running.add(server_id)
            self._ready.append(server_id)
            self._condition.notify()
        return True

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._ready and not self._closed:
                    self._condition.wait()
                if self._closed and not self._ready:
                    return
                server_id = self._ready.popleft()
            self._drain(server_id)

    def _drain(self, server_id: str) -> None:
        while True:
            with self._lock:
                if self._closed or server_id not in self._pending:
                    self._pending.pop(server_id, None)
                    self._running.discard(server_id)
                    return
                data = self._pending.pop(server_id)
            try:
                self._callback(server_id, data)
            except Exception as exc:
                logger.error("Emby Sessions refresh failed for server %s:\n%s", server_id, format_exception_for_log(exc))

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._ready.clear()
            self._condition.notify_all()
        for worker in self._workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        return all(not worker.is_alive() for worker in self._workers)
