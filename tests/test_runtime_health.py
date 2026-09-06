"""Application liveness and readiness probe coverage."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI

from runtime import health as runtime_health
from web import health_routes


def test_liveness_does_not_depend_on_runtime_dependencies():
    response = health_routes.liveness_probe()

    assert response.status_code == 200
    assert response.body == b"ok\n"
    assert response.headers["cache-control"] == "no-store"


def test_readiness_requires_completed_startup_and_database(monkeypatch):
    monkeypatch.setattr(runtime_health, "database_ready", lambda: True)
    runtime_health.mark_runtime_starting()

    response = health_routes.explicit_readiness_probe()
    assert response.status_code == 503
    assert response.body == b"not ready\n"

    runtime_health.mark_runtime_started()
    response = health_routes.explicit_readiness_probe()
    assert response.status_code == 200
    assert response.body == b"ok\n"


def test_readiness_fails_closed_when_database_is_unavailable(monkeypatch):
    runtime_health.mark_runtime_started()
    monkeypatch.setattr(runtime_health, "database_ready", lambda: False)

    response = health_routes.readiness_probe()

    assert response.status_code == 503
    assert response.body == b"not ready\n"


def test_database_probe_sanitizes_connection_failures(monkeypatch):
    from core import config_manager

    def fail_database():
        raise RuntimeError("credential-bearing database error")

    monkeypatch.setattr(config_manager, "_ensure_db_backend", fail_database)
    runtime_health.mark_runtime_starting()

    assert runtime_health.database_ready() is False


def test_database_readiness_caches_the_complete_successful_probe(monkeypatch):
    from core import config_manager

    class Backend:
        connection_checks = 0
        migration_checks = 0

        def test_connection(self):
            self.connection_checks += 1
            return True, None

        def validate_migrations(self):
            self.migration_checks += 1
            return {"ok": True}

    backend = Backend()
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: backend)
    runtime_health.mark_runtime_starting()

    try:
        assert runtime_health.database_ready() is True
        assert runtime_health.database_ready() is True
        assert backend.connection_checks == 1
        assert backend.migration_checks == 1
    finally:
        runtime_health.mark_runtime_starting()


def test_database_readiness_is_single_flight_at_cache_expiry(monkeypatch):
    from core import config_manager

    worker_count = 8
    start = threading.Barrier(worker_count)
    count_lock = threading.Lock()

    class Backend:
        connection_checks = 0
        migration_checks = 0

        def test_connection(self):
            with count_lock:
                self.connection_checks += 1
            return True, None

        def validate_migrations(self):
            with count_lock:
                self.migration_checks += 1
            time.sleep(0.05)
            return {"ok": True}

    backend = Backend()
    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: backend)
    runtime_health.mark_runtime_starting()

    def probe(_index: int) -> bool:
        start.wait(timeout=2)
        return runtime_health.database_ready()

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(probe, range(worker_count)))
        assert results == [True] * worker_count
        assert backend.connection_checks == 1
        assert backend.migration_checks == 1
    finally:
        runtime_health.mark_runtime_starting()


def test_health_routes_are_public_and_hidden_from_openapi():
    app = FastAPI()
    app.include_router(health_routes.router)

    health_routes_by_path = {
        route.path: route
        for route in health_routes.router.routes
        if getattr(route, "path", "").startswith("/health")
    }
    assert set(health_routes_by_path) == {"/health", "/health/live", "/health/ready"}
    assert all(not route.include_in_schema for route in health_routes_by_path.values())
    assert app.openapi()["paths"] == {}
