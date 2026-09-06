"""Single-flight and cooldown policy for expensive integration checks."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections.abc import Callable
from typing import Any


ConnectionCheckResult = tuple[dict[str, Any], int]


class ConnectionCheckCoordinator:
    """Run at most one check and reuse its recent immutable result."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._cached: ConnectionCheckResult | None = None
        self._completed_at = 0.0
        self._builder_identity: object | None = None
        self._generation = 0

    @staticmethod
    def _cooldown_seconds() -> float:
        try:
            configured = float(os.environ.get("SERVICE_CONNECTION_CHECK_COOLDOWN_SECONDS", "10"))
        except ValueError:
            configured = 10.0
        return max(1.0, min(configured, 300.0))

    def run(self, builder: Callable[[], ConnectionCheckResult]) -> ConnectionCheckResult:
        now = time.monotonic()
        with self._lock:
            same_builder = self._builder_identity is builder
            if same_builder and self._cached is not None and now - self._completed_at < self._cooldown_seconds():
                return copy.deepcopy(self._cached)
            if self._running:
                if same_builder and self._cached is not None:
                    return copy.deepcopy(self._cached)
                return {
                    "success": False,
                    "message": "Verifica dei servizi già in corso",
                }, 409
            if not same_builder:
                # A swapped builder (for example after a new application
                # lifespan or a test override) must never inherit a response
                # produced by the previous callable.  Clear the payload before
                # publishing the new identity so an exception cannot associate
                # stale data with the replacement builder.
                self._cached = None
                self._completed_at = 0.0
            self._running = True
            self._builder_identity = builder
            generation = self._generation

        try:
            result = builder()
        finally:
            with self._lock:
                if generation == self._generation:
                    self._running = False

        with self._lock:
            if generation == self._generation:
                self._cached = copy.deepcopy(result)
                self._completed_at = time.monotonic()
        return result

    def reset(self) -> None:
        """Clear ephemeral state during tests or a new in-process lifespan."""
        with self._lock:
            self._generation += 1
            self._running = False
            self._cached = None
            self._completed_at = 0.0
            self._builder_identity = None


connection_check_coordinator = ConnectionCheckCoordinator()
