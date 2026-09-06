"""Fault-injection regressions for workflow lease resource cleanup."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from core.storage.storage_workflows import (
    StorageWorkflowMixin,
    _WorkflowLease,
    _workflow_process_lease,
)


class _Dialect:
    name = "postgresql"


class _Result:
    def scalar(self):
        return True


class _FaultConnection:
    dialect = _Dialect()

    def __init__(self, failure):
        self.failure = failure
        self.invalidated = False
        self.close_attempted = False

    def execute(self, *_args, **_kwargs):
        if self.failure == "execute":
            raise RuntimeError("execute failed")
        return _Result()

    def commit(self):
        if self.failure == "commit":
            raise RuntimeError("commit failed")

    def rollback(self):
        if self.failure == "rollback":
            raise RuntimeError("rollback failed")

    def invalidate(self):
        self.invalidated = True
        if self.failure == "invalidate":
            raise RuntimeError("invalidate failed")

    def close(self):
        self.close_attempted = True
        if self.failure == "close":
            raise RuntimeError("close failed")


class _Engine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


class _InterruptingEngine:
    def connect(self):
        raise KeyboardInterrupt("connect interrupted")


class _CloseSignalConnection(_FaultConnection):
    def __init__(self):
        super().__init__(None)

    def close(self):
        self.close_attempted = True
        raise GeneratorExit("close interrupted")


class _Provider(StorageWorkflowMixin):
    def __init__(self, connection):
        self._engine: Any = _Engine(connection)

    def ensure_ready(self):
        return None

    def _get_session(self):
        raise AssertionError("not used by lease cleanup tests")


def _assert_process_mutex_released():
    assert _workflow_process_lease.acquire(blocking=False) is True
    _workflow_process_lease.release()


@pytest.mark.parametrize("failure", ["execute", "commit", "close"])
def test_release_lease_always_closes_and_releases_process_mutex(failure):
    connection = _FaultConnection(failure)
    provider = _Provider(connection)
    assert _workflow_process_lease.acquire(blocking=False) is True
    lease = _WorkflowLease(connection)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        provider.release_workflow_lease(lease)

    assert lease.released is True
    assert connection.close_attempted is True
    if failure == "close":
        assert connection.invalidated is True
    _assert_process_mutex_released()


@pytest.mark.parametrize("failure", ["execute", "commit"])
def test_acquire_lease_failure_discards_connection_and_releases_mutex(failure):
    connection = _FaultConnection(failure)
    provider = _Provider(connection)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        provider.acquire_workflow_lease()

    assert connection.invalidated is True
    assert connection.close_attempted is True
    _assert_process_mutex_released()


def test_acquire_lease_process_signal_still_releases_process_mutex():
    provider = _Provider(_FaultConnection(None))
    provider._engine = _InterruptingEngine()

    with pytest.raises(KeyboardInterrupt, match="connect interrupted"):
        provider.acquire_workflow_lease()

    _assert_process_mutex_released()


def test_release_lease_close_signal_still_marks_and_releases_resources():
    connection = _CloseSignalConnection()
    provider = _Provider(connection)
    assert _workflow_process_lease.acquire(blocking=False) is True
    lease = _WorkflowLease(connection)

    with pytest.raises(GeneratorExit, match="close interrupted"):
        provider.release_workflow_lease(lease)

    assert lease.released is True
    assert connection.invalidated is True
    assert connection.close_attempted is True
    _assert_process_mutex_released()


def test_repository_routes_workflow_lease_release_through_safe_helper():
    root = Path(__file__).resolve().parents[1]
    allowed = root / "core/workflow_lease_cleanup.py"
    findings = []
    for path in (root / "core").rglob("*.py"):
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "release_workflow_lease"
            ):
                findings.append(f"{path.relative_to(root)}:{node.lineno}")
    assert findings == []
