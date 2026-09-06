"""Minimal liveness and readiness state for container orchestration."""

from __future__ import annotations

import threading
import time


_state_lock = threading.Lock()
_state_changed = threading.Condition(_state_lock)
_startup_complete = False
_schema_cache_ok = False
_schema_cache_at = 0.0
_database_check_in_progress = False
_state_generation = 0
_SCHEMA_CACHE_SECONDS = 30.0
_READINESS_WAITER_SECONDS = 2.0


def mark_runtime_starting() -> None:
    """Reset readiness while a new application instance is being built."""
    global _startup_complete, _schema_cache_ok, _schema_cache_at, _state_generation
    with _state_changed:
        _startup_complete = False
        _schema_cache_ok = False
        _schema_cache_at = 0.0
        _state_generation += 1
        _state_changed.notify_all()


def mark_runtime_started() -> None:
    """Allow readiness probes to validate runtime dependencies."""
    global _startup_complete
    with _state_lock:
        _startup_complete = True


def runtime_started() -> bool:
    with _state_lock:
        return _startup_complete


def database_ready() -> bool:
    """Return a short-lived, single-flight database readiness result."""
    global _database_check_in_progress, _schema_cache_ok, _schema_cache_at
    now = time.monotonic()
    with _state_changed:
        if now - _schema_cache_at < _SCHEMA_CACHE_SECONDS:
            return _schema_cache_ok
        wait_deadline = now + _READINESS_WAITER_SECONDS
        while _database_check_in_progress:
            remaining = wait_deadline - time.monotonic()
            if remaining <= 0:
                return False
            _state_changed.wait(timeout=remaining)
            now = time.monotonic()
            if now - _schema_cache_at < _SCHEMA_CACHE_SECONDS:
                return _schema_cache_ok
        _database_check_in_progress = True
        check_generation = _state_generation

    schema_ok = False
    try:
        from core.config_manager import _ensure_db_backend

        backend = _ensure_db_backend()
        ready, _message = backend.test_connection()
        if ready:
            validation = backend.validate_migrations()
            schema_ok = bool(validation.get("ok"))
    except Exception:
        schema_ok = False
    finally:
        with _state_changed:
            if check_generation == _state_generation:
                _schema_cache_ok = schema_ok
                _schema_cache_at = time.monotonic()
            else:
                schema_ok = False
            _database_check_in_progress = False
            _state_changed.notify_all()
    return schema_ok


def runtime_ready() -> bool:
    """Readiness requires completed startup and a reachable PostgreSQL backend."""
    return runtime_started() and database_ready()
