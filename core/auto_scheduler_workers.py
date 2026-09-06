"""Lifecycle-owned workers used by the automatic task scheduler."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class AutoSchedulerWorkerPool:
    """Run at most one worker per task kind without blocking scheduling."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._stopping = False

    def start(
        self,
        kind: str,
        target: Callable[[threading.Event], bool | None],
        *,
        on_complete: Callable[[bool], None] | None = None,
    ) -> bool:
        normalized_kind = str(kind or "task")
        with self._lock:
            if self._stopping:
                return False
            existing = self._threads.get(normalized_kind)
            if existing is not None and existing.is_alive():
                return False

            stop_event = threading.Event()

            def run() -> None:
                succeeded = False
                try:
                    succeeded = target(stop_event) is not False and not stop_event.is_set()
                finally:
                    try:
                        if on_complete is not None:
                            on_complete(succeeded)
                    finally:
                        with self._lock:
                            if self._threads.get(normalized_kind) is threading.current_thread():
                                self._threads.pop(normalized_kind, None)
                                self._stop_events.pop(normalized_kind, None)

            thread = threading.Thread(
                target=run,
                name=f"octohubs-auto-{normalized_kind}",
                daemon=True,
            )
            self._threads[normalized_kind] = thread
            self._stop_events[normalized_kind] = stop_event
            try:
                thread.start()
            except BaseException:
                # Thread.start() can be interrupted after the native thread was
                # created. Retain ownership in that ambiguous case so shutdown
                # and wait can still reach the live worker.
                if not thread.is_alive():
                    self._threads.pop(normalized_kind, None)
                    self._stop_events.pop(normalized_kind, None)
                raise
            return True

    def cancel(self, kind: str) -> None:
        with self._lock:
            stop_event = self._stop_events.get(str(kind or "task"))
        if stop_event is not None:
            stop_event.set()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            stop_events = list(self._stop_events.values())
        for stop_event in stop_events:
            stop_event.set()

    def wait(self, timeout_seconds: float | None = None) -> bool:
        deadline = None
        if timeout_seconds is not None:
            deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        return not any(thread.is_alive() for thread in threads)

    def is_running(self, kind: str) -> bool:
        with self._lock:
            thread = self._threads.get(str(kind or "task"))
            return bool(thread and thread.is_alive())


__all__ = ["AutoSchedulerWorkerPool"]
