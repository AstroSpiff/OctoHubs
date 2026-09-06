"""Regression and class-level canaries for R36 backend cleanup remediation."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from core.auth_session_scope import AuthRequestScope, RequestAwareSessionRegistry
from core.storage.storage_errors import StorageError
from core.storage.storage_users import StorageUsersMixin
from emby_latest.refresh_coordination import latest_refresh_guard
from emby_latest.state_coordination import latest_state_update_guard


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _FailingGuardSession:
    def get_bind(self):
        return _Bind()

    def commit(self):
        return None

    def rollback(self):
        raise SQLAlchemyError("secondary rollback failure")

    def invalidate(self):
        raise SQLAlchemyError("secondary invalidate failure")

    def close(self):
        raise SQLAlchemyError("secondary close failure")

    def remove(self):
        raise SQLAlchemyError("secondary remove failure")


class _GuardStorage:
    def __init__(self):
        self.session = _FailingGuardSession()

    def _get_session(self):
        return self.session


@pytest.mark.parametrize("guard", [latest_refresh_guard, latest_state_update_guard])
def test_latest_guards_preserve_body_error_when_every_cleanup_step_fails(guard):
    primary = ValueError("primary Latest failure")

    with pytest.raises(ValueError) as caught:
        with guard(_GuardStorage()):
            raise primary

    assert caught.value is primary


class _ExistingIconRule:
    icon_path = "old"
    image_data = None
    mime_type = None


class _ExistingIconBinding:
    profile_id = "old"


class _IconSession:
    def __init__(self, existing: object):
        self.existing = existing
        self.get_calls = 0

    def get(self, _model, _key):
        self.get_calls += 1
        if self.get_calls == 1:
            return object()
        if self.get_calls == 2:
            return self.existing
        raise SQLAlchemyError("secondary lookup must not run")

    def commit(self):
        raise SQLAlchemyError("primary icon commit failure")

    def rollback(self):
        raise SQLAlchemyError("secondary rollback failure")

    def invalidate(self):
        return None

    def close(self):
        return None


class _IconStorage(StorageUsersMixin):
    def __init__(self, existing: object):
        self.session = _IconSession(existing)

    def _get_session(self):
        return self.session


@pytest.mark.parametrize(
    ("existing", "save"),
    [
        (_ExistingIconRule(), lambda storage: storage.save_icon_rule("p", "c", "/icon")),
        (
            _ExistingIconBinding(),
            lambda storage: storage.save_icon_binding("user", "server:user", "p"),
        ),
    ],
)
def test_icon_writers_never_query_a_session_after_failed_rollback(existing, save):
    storage = _IconStorage(existing)

    with pytest.raises(StorageError, match="primary icon commit failure"):
        save(storage)

    assert storage.session.get_calls == 2


class _SessionFactory:
    def __call__(self, **_kwargs):
        return object()


class _TrackedSession:
    def __init__(self, name: str, events: list[str], *, fail: bool = False):
        self.name = name
        self.events = events
        self.fail = fail

    def close(self):
        self.events.append(f"close:{self.name}")
        if self.fail:
            raise RuntimeError("postgresql://user:CANARY_R36_PASSWORD@db/octohubs")

    def invalidate(self):
        self.events.append(f"invalidate:{self.name}")
        if self.fail:
            raise RuntimeError("postgresql://user:CANARY_R36_PASSWORD@db/octohubs")


def test_auth_registry_attempts_every_session_after_thread_and_session_failures(
    monkeypatch,
    caplog,
):
    events: list[str] = []
    registry = RequestAwareSessionRegistry(_SessionFactory())

    def fail_thread_remove():
        events.append("remove:thread")
        raise RuntimeError("postgresql://user:CANARY_R36_PASSWORD@db/octohubs")

    monkeypatch.setattr(registry._thread_sessions, "remove", fail_thread_remove)
    registry._request_sessions = {
        AuthRequestScope(): _TrackedSession("first", events, fail=True),
        AuthRequestScope(): _TrackedSession("second", events),
    }

    with caplog.at_level("ERROR"):
        assert registry.close_all() is False

    assert events == [
        "remove:thread",
        "close:first",
        "invalidate:first",
        "close:second",
    ]
    assert registry._request_sessions == {}
    assert "CANARY_R36_PASSWORD" not in caplog.text


@pytest.mark.parametrize(
    ("close_mode", "dispose_fails", "expected"),
    [
        ("true", False, True),
        ("false", False, False),
        ("raise", False, False),
        ("true", True, False),
    ],
)
def test_shutdown_auth_always_attempts_engine_disposal(
    monkeypatch,
    close_mode,
    dispose_fails,
    expected,
):
    from core import auth

    events: list[str] = []

    class Engine:
        def dispose(self):
            events.append("dispose")
            if dispose_fails:
                raise RuntimeError("engine disposal failure")

    class Registry:
        session_factory = SimpleNamespace(kw={"bind": Engine()})

        def close_all(self):
            events.append("close_all")
            if close_mode == "raise":
                raise RuntimeError("session cleanup failure")
            return close_mode == "true"

    monkeypatch.setattr(auth, "db_session", Registry())

    assert auth.shutdown_auth() is expected
    assert events == ["close_all", "dispose"]
    assert auth.db_session is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("auth_mode", "database_fails"),
    [("raise", False), ("false", False), ("true", True)],
)
async def test_runtime_attempts_every_pool_and_reports_any_cleanup_failure(
    monkeypatch,
    auth_mode,
    database_fails,
):
    import app_state
    from core import auth, config_manager
    import emby_probe
    from realtime import subscribers
    from runtime import bootstrap
    from services import connection_check_guard, scheduler_manager

    events: list[str] = []
    monkeypatch.setattr(scheduler_manager, "begin_scheduler_shutdown", lambda: None)
    monkeypatch.setattr(bootstrap.workflow_manager, "begin_shutdown", lambda: None)
    monkeypatch.setattr(
        emby_probe,
        "get_probe_manager",
        lambda: SimpleNamespace(begin_shutdown=lambda: None),
    )
    monkeypatch.setattr(bootstrap, "_threaded_shutdown_steps", lambda: ())
    monkeypatch.setattr(bootstrap, "_async_shutdown_steps", lambda: ())
    monkeypatch.setattr(app_state, "shutdown_operation_tracker", lambda _timeout: True)
    monkeypatch.setattr(app_state, "clear_app_event_loop", lambda: None)
    monkeypatch.setattr(app_state, "set_connection_check_state", lambda *_args: None)
    monkeypatch.setattr(connection_check_guard.connection_check_coordinator, "reset", lambda: None)
    monkeypatch.setattr(subscribers.sse_subscribers, "close_all", lambda: None)
    monkeypatch.setattr(subscribers.websocket_subscribers, "close_all", lambda: None)

    def fail_auth_shutdown():
        events.append("auth")
        if auth_mode == "raise":
            raise RuntimeError("auth cleanup failure")
        return auth_mode == "true"

    def close_application_pool():
        events.append("database")
        if database_fails:
            raise RuntimeError("application pool cleanup failure")

    monkeypatch.setattr(auth, "shutdown_auth", fail_auth_shutdown)
    monkeypatch.setattr(config_manager, "close_database_backend", close_application_pool)

    assert await bootstrap.shutdown_runtime_services(0.1) is False
    assert events == ["auth", "database"]


def _enclosing_function(parents: dict[ast.AST, ast.AST], node: ast.AST) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return ""


CleanupCall = tuple[str, str, str, str, str]


def _cleanup_inventory(source: str, relative_path: str) -> Counter[CleanupCall]:
    """Inventory cleanup calls without relying on the receiver variable name."""
    operations = {"rollback", "close", "remove", "invalidate"}
    tree = ast.parse(source)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    inventory: Counter[CleanupCall] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = _enclosing_function(parents, node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in operations:
            inventory[
                (
                    relative_path,
                    function_name,
                    ast.unparse(node.func.value),
                    node.func.attr,
                    "direct",
                )
            ] += 1
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in operations
        ):
            inventory[
                (
                    relative_path,
                    function_name,
                    ast.unparse(node.args[0]),
                    str(node.args[1].value),
                    "getattr",
                )
            ] += 1
    return inventory


def test_sqlalchemy_cleanup_receivers_are_canonical_or_semantically_allowlisted():
    root = Path(__file__).resolve().parents[1]
    allowed: dict[CleanupCall, tuple[int, str]] = {
        # This rollback establishes the SQLite test-only admin mutation boundary;
        # there is no primary error to preserve and failure must abort the guard.
        ("core/auth_admin_invariant.py", "active_admin_mutation_guard", "session", "rollback", "direct"): (1, "fail-fast guard"),
        # Workflow leases own raw SQLAlchemy Connections and already isolate
        # rollback/invalidate/close while releasing their process mutex in finally.
        ("core/storage/storage_workflows.py", "_discard_workflow_connection", "connection", "invalidate", "direct"): (1, "raw SQLAlchemy Connection"),
        ("core/storage/storage_workflows.py", "_discard_workflow_connection", "connection", "close", "direct"): (1, "raw SQLAlchemy Connection"),
        ("core/storage/storage_workflows.py", "acquire_workflow_lease", "connection", "close", "direct"): (1, "raw SQLAlchemy Connection"),
        ("core/storage/storage_workflows.py", "release_workflow_lease", "connection", "rollback", "direct"): (1, "raw SQLAlchemy Connection"),
        ("core/storage/storage_workflows.py", "release_workflow_lease", "connection", "invalidate", "direct"): (2, "raw SQLAlchemy Connection"),
        ("core/storage/storage_workflows.py", "release_workflow_lease", "connection", "close", "direct"): (1, "raw SQLAlchemy Connection"),
        ("core/storage/storage_core.py", "advisory_lock", "session", "invalidate", "getattr"): (1, "advisory-lock discard fallback"),
        # Alembic owns a migration Connection, outside application Session scope.
        ("alembic/env.py", "run_migrations_online", "connection", "rollback", "direct"): (1, "Alembic Connection"),
        # Explicit resource-boundary wrappers.
        ("core/config_manager.py", "close_database_backend", "backend", "close", "direct"): (1, "DatabaseStorage wrapper"),
        ("web/auth_db_session_middleware.py", "_remove_auth_session", "registry", "remove", "direct"): (1, "request-aware registry wrapper"),
        ("core/http_response_limits.py", "close_response_safely", "response", "close", "getattr"): (1, "bounded HTTP response wrapper"),
        ("core/websocket_io.py", "close_bounded", "websocket", "close", "direct"): (1, "bounded WebSocket wrapper"),
        # Non-SQLAlchemy response, socket, spooled-file and coroutine owners.
        ("emby_latest/notification_images.py", "_download_emby_image", "response", "close", "direct"): (1, "HTTP response"),
        ("emby_libraries/image_snapshots.py", "_build_emby_image_stream", "response", "close", "direct"): (4, "HTTP response"),
        ("emby_probe/csv_export.py", "build_probe_csv_export", "spool", "close", "direct"): (5, "spooled file"),
        ("emby_probe/routes.py", "csv_stream", "spool", "close", "direct"): (1, "spooled file"),
        ("emby_runtime/api_clients_indexers.py", "search_jackett", "response", "close", "getattr"): (1, "HTTP response"),
        ("emby_runtime/api_clients_indexers.py", "search_prowlarr", "response", "close", "getattr"): (1, "HTTP response"),
        ("emby_runtime/library_poller.py", "_spawn_background_task", "coroutine", "close", "direct"): (1, "unstarted coroutine"),
        ("emby_runtime/library_poller.py", "schedule_tracking_library", "coroutine", "close", "direct"): (1, "unstarted coroutine"),
        ("search/torrent_download.py", "_open_pinned_response", "connection", "close", "direct"): (1, "stdlib HTTPConnection"),
        ("search/torrent_download.py", "_open_validated_socket", "sock", "close", "direct"): (1, "socket"),
        ("search/torrent_download.py", "download_torrent", "response", "close", "direct"): (1, "stdlib HTTPResponse"),
        ("search/torrent_download.py", "download_torrent", "connection", "close", "direct"): (1, "stdlib HTTPConnection"),
        ("scripts/container_secret_lock.py", "main", "os", "close", "direct"): (2, "OS file descriptor"),
        # Transport and subscriber lifecycle owners; their surrounding methods
        # provide timeout, exception isolation, or collection ownership.
        ("emby_runtime/event_bridge_manager.py", "_register_unlocked", "previous_socket", "close", "getattr"): (1, "owned WebSocket replacement"),
        ("emby_runtime/event_bridge_manager.py", "close", "websocket", "close", "getattr"): (1, "owned WebSocket"),
        ("emby_runtime/event_bridge_manager.py", "close_server_connection", "websocket", "close", "direct"): (1, "owned WebSocket"),
        ("emby_runtime/scan_websocket_manager.py", "_close_slow_client", "websocket", "close", "direct"): (1, "bounded WebSocket"),
        ("emby_runtime/scan_websocket_manager.py", "shutdown", "websocket", "close", "direct"): (1, "bounded WebSocket"),
        ("emby_runtime/websocket_manager.py", "stop", "self.ws", "close", "direct"): (1, "websocket-client transport"),
        ("realtime/subscribers.py", "close_all", "subscriber", "close", "direct"): (1, "owned subscriber"),
        ("realtime/subscribers.py", "unsubscribe", "subscriber", "close", "direct"): (1, "owned subscriber"),
        ("realtime/subscribers.py", "publish", "self._subscribers", "remove", "direct"): (1, "list membership"),
        ("realtime/subscribers.py", "unsubscribe", "self._subscribers", "remove", "direct"): (1, "list membership"),
    }
    observed: Counter[CleanupCall] = Counter()

    for path in [*root.glob("**/*.py")]:
        if any(
            part in {".git", "__pycache__", "node_modules", "tests", "venv"}
            for part in path.parts
        ):
            continue
        relative = str(path.relative_to(root))
        observed.update(_cleanup_inventory(path.read_text(encoding="utf-8"), relative))

    expected = Counter({call: count for call, (count, _reason) in allowed.items()})
    assert observed == expected


def test_cleanup_inventory_catches_renamed_receivers_and_getattr_variants():
    source = """
def unsafe_cleanup(db):
    db.close()
    close = getattr(db, "close", None)
    invalidate = getattr(db, "invalidate", None)
    close()
    invalidate()
"""

    assert _cleanup_inventory(source, "mutation.py") == Counter(
        {
            ("mutation.py", "unsafe_cleanup", "db", "close", "direct"): 1,
            ("mutation.py", "unsafe_cleanup", "db", "close", "getattr"): 1,
            ("mutation.py", "unsafe_cleanup", "db", "invalidate", "getattr"): 1,
        }
    )
