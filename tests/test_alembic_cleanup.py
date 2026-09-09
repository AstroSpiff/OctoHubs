"""Failure-path canaries for Alembic's PostgreSQL advisory-lock cleanup."""

from __future__ import annotations

import ast
import runpy
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import alembic.context as alembic_context
import pytest
import sqlalchemy

import core.database_fastapi_upgrade as database_fastapi_upgrade
import core.log_sanitization as log_sanitization


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_ENV = PROJECT_ROOT / "alembic" / "env.py"


def test_empty_alembic_registry_is_an_unversioned_database():
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            assert (
                database_fastapi_upgrade._current_revision(
                    connection, {"alembic_version"}
                )
                is None
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('one'), ('two')")
            )
            assert database_fastapi_upgrade._current_revision(
                connection, {"alembic_version"}
            ) == "__unsupported__"
    finally:
        engine.dispose()


class _Config:
    config_file_name = None
    config_ini_section = "alembic"
    attributes = {"octohubs_database_url": "postgresql://migration.test/octohubs"}

    @staticmethod
    def get_main_option(_name: str) -> str:
        return "postgresql://migration.test/octohubs"

    @staticmethod
    def get_section(_name: str, _default: object) -> dict[str, object]:
        return {}


class _Connection:
    def __init__(
        self,
        *,
        dialect: str = "postgresql",
        failures: dict[str, BaseException] | None = None,
    ) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.failures = dict(failures or {})
        self.events: list[str] = []
        self.commit_calls = 0

    def execute(self, statement, _parameters=None):
        operation = "unlock" if "pg_advisory_unlock" in str(statement) else "lock"
        self.events.append(operation)
        self._raise(operation)
        return object()

    def commit(self) -> None:
        self.commit_calls += 1
        operation = "cleanup_commit" if "unlock" in self.events else "initial_commit"
        self.events.append(operation)
        self._raise(operation)

    def in_transaction(self) -> bool:
        self.events.append("in_transaction")
        self._raise("in_transaction")
        return True

    def rollback(self) -> None:
        self.events.append("rollback")
        self._raise("rollback")

    def close(self) -> None:
        self.events.append("close")
        self._raise("close")

    def _raise(self, operation: str) -> None:
        error = self.failures.get(operation)
        if error is not None:
            raise error


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def connect(self) -> _Connection:
        return self.connection


def _run_online_environment(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
    *,
    migration_error: BaseException | None = None,
    preparation_error: BaseException | None = None,
) -> None:
    # Alembic imports these transitively through ``core.storage``. Load them
    # before replacing SQLAlchemy's factory so later tests cannot retain the
    # fake factory in module-level bindings.
    import core.database_migrations  # noqa: F401
    import core.storage.storage_models  # noqa: F401

    monkeypatch.setattr(alembic_context, "config", _Config(), raising=False)
    monkeypatch.setattr(alembic_context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(alembic_context, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(alembic_context, "begin_transaction", nullcontext)

    def run_migrations() -> None:
        connection.events.append("migrate")
        if migration_error is not None:
            raise migration_error

    monkeypatch.setattr(alembic_context, "run_migrations", run_migrations)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_args, **_kwargs: _Engine(connection))
    # This suite isolates Alembic lock/cleanup behavior. The published-schema
    # preparation has its own real-connection coverage and is outside the fake
    # connection contract exercised here.
    def prepare_published_schema(_connection: object) -> bool:
        if preparation_error is not None:
            raise preparation_error
        return False

    monkeypatch.setattr(
        database_fastapi_upgrade,
        "prepare_published_fastapi_schema",
        prepare_published_schema,
    )
    runpy.run_path(str(ALEMBIC_ENV), run_name="octohubs_alembic_cleanup_canary")


@pytest.mark.parametrize("failed_cleanup", ["rollback", "unlock", "cleanup_commit"])
def test_primary_migration_error_survives_every_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    failed_cleanup: str,
) -> None:
    primary = ValueError("PRIMARY")
    connection = _Connection(failures={failed_cleanup: RuntimeError("CLEANUP")})

    with pytest.raises(ValueError, match="PRIMARY") as raised:
        _run_online_environment(monkeypatch, connection, migration_error=primary)

    assert raised.value is primary
    assert connection.events == [
        "lock",
        "initial_commit",
        "initial_commit",
        "migrate",
        "in_transaction",
        "rollback",
        "unlock",
        "cleanup_commit",
        "close",
    ]


def test_first_cleanup_error_is_raised_after_all_steps_without_a_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = RuntimeError("ROLLBACK")
    connection = _Connection(
        failures={"rollback": first, "unlock": ValueError("UNLOCK")},
    )

    with pytest.raises(RuntimeError, match="ROLLBACK") as raised:
        _run_online_environment(monkeypatch, connection)

    assert raised.value is first
    assert connection.events[-4:] == ["rollback", "unlock", "cleanup_commit", "close"]


@pytest.mark.parametrize(
    ("migration_error", "cleanup_error", "expected_type", "message"),
    [
        (GeneratorExit("PRIMARY"), KeyboardInterrupt("SECONDARY"), GeneratorExit, "PRIMARY"),
        (None, KeyboardInterrupt("CLEANUP"), KeyboardInterrupt, "CLEANUP"),
    ],
)
def test_base_exception_semantics_preserve_primary_or_propagate_first_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    migration_error: BaseException | None,
    cleanup_error: BaseException,
    expected_type: type[BaseException],
    message: str,
) -> None:
    connection = _Connection(failures={"rollback": cleanup_error})

    with pytest.raises(expected_type, match=message):
        _run_online_environment(
            monkeypatch,
            connection,
            migration_error=migration_error,
        )

    assert connection.events[-4:] == ["rollback", "unlock", "cleanup_commit", "close"]


@pytest.mark.parametrize("failed_operation", ["lock", "initial_commit"])
def test_lock_acquisition_phase_failure_still_attempts_complete_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    failed_operation: str,
) -> None:
    primary = RuntimeError("LOCK ACQUISITION PHASE")
    connection = _Connection(failures={failed_operation: primary})

    with pytest.raises(RuntimeError, match="LOCK ACQUISITION PHASE") as raised:
        _run_online_environment(monkeypatch, connection)

    assert raised.value is primary
    assert "migrate" not in connection.events
    assert connection.events[-4:] == ["rollback", "unlock", "cleanup_commit", "close"]


def test_published_schema_preparation_failure_uses_the_same_cleanup_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = RuntimeError("PREPARATION")
    connection = _Connection()

    with pytest.raises(RuntimeError, match="PREPARATION") as raised:
        _run_online_environment(
            monkeypatch,
            connection,
            preparation_error=primary,
        )

    assert raised.value is primary
    assert "migrate" not in connection.events
    assert connection.events[-4:] == ["rollback", "unlock", "cleanup_commit", "close"]


def test_unknown_transaction_state_still_attempts_every_cleanup_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_error = RuntimeError("TRANSACTION STATE")
    connection = _Connection(failures={"in_transaction": state_error})

    with pytest.raises(RuntimeError, match="TRANSACTION STATE") as raised:
        _run_online_environment(monkeypatch, connection)

    assert raised.value is state_error
    assert connection.events[-5:] == [
        "in_transaction",
        "rollback",
        "unlock",
        "cleanup_commit",
        "close",
    ]


@pytest.mark.parametrize("migration_error", [None, ValueError("NON-POSTGRES PRIMARY")])
def test_non_postgresql_path_never_runs_advisory_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    migration_error: BaseException | None,
) -> None:
    connection = _Connection(dialect="sqlite")

    if migration_error is None:
        _run_online_environment(monkeypatch, connection)
    else:
        with pytest.raises(ValueError, match="NON-POSTGRES PRIMARY"):
            _run_online_environment(
                monkeypatch,
                connection,
                migration_error=migration_error,
            )

    assert connection.events == ["migrate", "close"]


@pytest.mark.parametrize(
    ("migration_error", "cleanup_failures", "expected"),
    [
        (ValueError("PRIMARY"), {"close": RuntimeError("CLOSE")}, "PRIMARY"),
        (
            None,
            {"rollback": RuntimeError("ROLLBACK"), "close": ValueError("CLOSE")},
            "ROLLBACK",
        ),
        (None, {"close": RuntimeError("CLOSE")}, "CLOSE"),
    ],
)
def test_connection_close_is_attempted_once_without_masking_earlier_failures(
    monkeypatch: pytest.MonkeyPatch,
    migration_error: BaseException | None,
    cleanup_failures: dict[str, BaseException],
    expected: str,
) -> None:
    connection = _Connection(failures=cleanup_failures)

    with pytest.raises(BaseException, match=expected):
        _run_online_environment(
            monkeypatch,
            connection,
            migration_error=migration_error,
        )

    assert connection.events.count("close") == 1
    assert connection.events[-1] == "close"


def test_cleanup_error_is_not_suppressed_by_an_unrelated_outer_except_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_error = RuntimeError("ROLLBACK")
    connection = _Connection(failures={"rollback": cleanup_error})

    try:
        raise ValueError("UNRELATED OUTER ERROR")
    except ValueError:
        with pytest.raises(RuntimeError, match="ROLLBACK") as raised:
            _run_online_environment(monkeypatch, connection)

    assert raised.value is cleanup_error
    assert connection.events[-1] == "close"


def test_diagnostic_failure_cannot_mask_primary_or_skip_later_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = ValueError("PRIMARY")
    connection = _Connection(failures={"rollback": RuntimeError("ROLLBACK")})

    def fail_to_render(_exc: BaseException) -> str:
        raise GeneratorExit("DIAGNOSTIC")

    monkeypatch.setattr(log_sanitization, "format_exception_for_log", fail_to_render)

    with pytest.raises(ValueError, match="PRIMARY") as raised:
        _run_online_environment(monkeypatch, connection, migration_error=primary)

    assert raised.value is primary
    assert connection.events[-4:] == ["rollback", "unlock", "cleanup_commit", "close"]


def test_alembic_online_finally_uses_the_failure_isolated_cleanup_boundary() -> None:
    """Prevent raw cleanup calls from returning to Alembic's outer finally."""
    tree = ast.parse(ALEMBIC_ENV.read_text(encoding="utf-8"))
    online = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_migrations_online"
    )
    outer_cleanup = [
        child
        for node in ast.walk(online)
        if isinstance(node, ast.Try)
        for child in node.finalbody
    ]
    direct_cleanup_calls = [
        call.func.attr
        for node in outer_cleanup
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in {"rollback", "commit", "execute"}
    ]

    assert direct_cleanup_calls == []
    assert any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_release_postgresql_migration_lock"
        for node in outer_cleanup
        for call in ast.walk(node)
    )
