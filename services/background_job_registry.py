"""Lifecycle-owned registry for generic background threads."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from core.thread_lifecycle import join_owned_thread, start_owned_thread_confirmed


@dataclass
class _Job:
    operation: dict[str, Any]
    thread: threading.Thread
    stop_event: threading.Event


class BackgroundJobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._accepting_jobs = True

    def initialize(self) -> None:
        """Reopen a clean registry for a new in-process application lifespan."""
        with self._lock:
            active = [job for job in self._jobs.values() if job.thread.is_alive()]
            if active:
                raise RuntimeError("Impossibile riaprire il registro con job ancora attivi")
            self._jobs.clear()
            self._accepting_jobs = True

    def start(
        self,
        key: str | None,
        operation_factory: Callable[[], dict[str, Any]],
        target: Callable[[threading.Event], None],
    ) -> tuple[dict[str, Any], bool]:
        job_key = key or f"unkeyed:{uuid4().hex}"
        with self._lock:
            if not self._accepting_jobs:
                raise RuntimeError("Avvio job rifiutato durante lo shutdown")
            existing = self._jobs.get(job_key)
            if existing and existing.thread.is_alive():
                return existing.operation, False
            operation = operation_factory()
            stop_event = threading.Event()

            def run() -> None:
                try:
                    target(stop_event)
                finally:
                    with self._lock:
                        current = self._jobs.get(job_key)
                        if current and current.thread is threading.current_thread():
                            self._jobs.pop(job_key, None)

            # Workers receive a cooperative stop signal, but an unresponsive
            # integration must never keep a container process alive indefinitely.
            thread = threading.Thread(target=run, name=f"octohubs-job-{job_key}", daemon=True)
            self._jobs[job_key] = _Job(
                operation=operation,
                thread=thread,
                stop_event=stop_event,
            )
            def rollback_unstarted() -> None:
                self._jobs.pop(job_key, None)
                stop_event.set()

            start_owned_thread_confirmed(
                thread,
                rollback_unstarted=rollback_unstarted,
                context=f"background job {job_key}",
            )
            return operation, True

    def shutdown(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            self._accepting_jobs = False
            jobs = list(self._jobs.values())
        for job in jobs:
            job.stop_event.set()
        threads = [job.thread for job in jobs]
        for thread in threads:
            remaining = max(0.0, deadline - time.monotonic())
            join_owned_thread(thread, remaining)
        return not any(thread.is_alive() for thread in threads)

    def has_active_jobs(self) -> bool:
        """Return whether any lifecycle-owned job can still mutate persisted state."""
        with self._lock:
            return any(job.thread.is_alive() for job in self._jobs.values())

    def owns_operation(self, operation: dict[str, Any]) -> bool:
        """Return whether a native-started job still owns this operation."""
        with self._lock:
            return any(
                job.operation is operation and job.thread.is_alive()
                for job in self._jobs.values()
            )


background_job_registry = BackgroundJobRegistry()
