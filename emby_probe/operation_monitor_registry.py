"""Lifecycle ownership for Probe operation-monitor threads."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ProbeOperationMonitorRegistry:
    """Own monitor threads so shutdown can fence and join every callback."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._monitors: dict[threading.Thread, threading.Event] = {}
        self._accepting = True

    def initialize(self) -> None:
        with self._lock:
            if any(thread.is_alive() for thread in self._monitors):
                raise RuntimeError("Monitor Probe ancora attivi durante la riapertura")
            self._monitors.clear()
            self._accepting = True

    def start(self, callback: Callable[[threading.Event], None]) -> None:
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
            self._monitors[thread] = stop_event
            try:
                thread.start()
            except BaseException:
                self._monitors.pop(thread, None)
                raise

    def shutdown(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._lock:
            self._accepting = False
            monitors = list(self._monitors.items())
        for _thread, stop_event in monitors:
            stop_event.set()
        for thread, _stop_event in monitors:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return all(
            thread is threading.current_thread() or not thread.is_alive()
            for thread, _stop_event in monitors
        )
