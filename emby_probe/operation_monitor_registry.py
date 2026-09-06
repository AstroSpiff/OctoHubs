"""Lifecycle ownership for Probe operation-monitor threads."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from core.thread_lifecycle import join_owned_thread, start_owned_thread_confirmed


class ProbeOperationMonitorRegistry:
    """Own monitor threads so shutdown can fence and join every callback."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._monitors: dict[threading.Thread, tuple[threading.Event, str | None]] = {}
        self._accepting = True

    def initialize(self) -> None:
        with self._lock:
            if any(thread.is_alive() for thread in self._monitors):
                raise RuntimeError("Monitor Probe ancora attivi durante la riapertura")
            self._monitors.clear()
            self._accepting = True

    def start(
        self,
        callback: Callable[[threading.Event], None],
        *,
        owner_token: str | None = None,
    ) -> None:
        stop_event = threading.Event()

        def run() -> None:
            try:
                callback(stop_event)
            finally:
                with self._lock:
                    self._monitors.pop(threading.current_thread(), None)

        thread = threading.Thread(
            target=run,
            name="probe-operation-monitor",
            daemon=True,
        )
        with self._lock:
            if not self._accepting:
                raise RuntimeError("Monitor Probe rifiutato durante lo shutdown")
            self._monitors[thread] = (stop_event, owner_token)

            def rollback_unstarted() -> None:
                self._monitors.pop(thread, None)

            start_owned_thread_confirmed(
                thread,
                rollback_unstarted=rollback_unstarted,
                context="Probe operation monitor",
            )

    def owns(self, owner_token: str) -> bool:
        with self._lock:
            return any(
                token == owner_token and thread.is_alive()
                for thread, (_stop, token) in self._monitors.items()
            )

    def shutdown(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._lock:
            self._accepting = False
            monitors = list(self._monitors.items())
        for _thread, (stop_event, _token) in monitors:
            stop_event.set()
        for thread, (_stop_event, _token) in monitors:
            join_owned_thread(thread, max(0.0, deadline - time.monotonic()))
        return all(
            thread is threading.current_thread() or not thread.is_alive()
            for thread, (_stop_event, _token) in monitors
        )
