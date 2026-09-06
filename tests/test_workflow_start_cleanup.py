"""Failure-path canaries for workflow admission and recovery cleanup."""

from __future__ import annotations

import logging
import threading

import pytest
from sqlalchemy.exc import SQLAlchemyError

from core.storage.storage_errors import StorageError
from core.storage.storage_workflows import StorageWorkflowMixin
from core.tasks import ScanManager, WorkflowManager
from core.workflow_lease_cleanup import release_workflow_lease_safely


class _StartStorage:
    def __init__(self, claim_result, release_error):
        self.claim_result = claim_result
        self.release_error = release_error
        self.lease = object()
        self.release_calls = 0

    def acquire_workflow_lease(self):
        return self.lease

    def try_start_workflow_execution(self, **_kwargs):
        if isinstance(self.claim_result, BaseException):
            raise self.claim_result
        return self.claim_result

    def release_workflow_lease(self, lease):
        assert lease is self.lease
        self.release_calls += 1
        raise self.release_error


class _ThreadStartStorage:
    def __init__(self):
        self.lease = object()
        self.release_calls = 0
        self.finalize_calls = 0

    def acquire_workflow_lease(self):
        return self.lease

    def try_start_workflow_execution(self, **_kwargs):
        return True

    def release_workflow_lease(self, lease):
        assert lease is self.lease
        self.release_calls += 1

    def finalize_workflow_execution(self, **_kwargs):
        self.finalize_calls += 1
        return True


class _FallbackStartStorage:
    def __init__(self, primary):
        self.primary = primary
        self.finalize_calls = 0

    def create_workflow_execution(self, **_kwargs):
        raise self.primary

    def create_workflow_step(self, **_kwargs):
        raise AssertionError("step persistence must not follow the primary signal")

    def update_workflow_execution(self, **_kwargs):
        self.finalize_calls += 1


class _InterruptingOperationTracker:
    def __init__(self, primary):
        self.primary = primary

    def start(self, *_args, **_kwargs):
        raise self.primary


@pytest.mark.parametrize(
    ("claim_result", "release_error"),
    [
        (False, RuntimeError("SECONDARY release failure")),
        (False, KeyboardInterrupt("SECONDARY release interrupt")),
        (RuntimeError("PRIMARY claim failure"), RuntimeError("SECONDARY release failure")),
        (RuntimeError("PRIMARY claim failure"), GeneratorExit("SECONDARY release exit")),
    ],
    ids=[
        "claim-refused-release-error",
        "claim-refused-release-interrupt",
        "claim-error-release-error",
        "claim-error-release-exit",
    ],
)
def test_workflow_start_release_failure_cannot_strand_local_lifecycle(
    claim_result,
    release_error,
    caplog,
):
    storage = _StartStorage(claim_result, release_error)
    manager = WorkflowManager()
    manager._db_storage = storage

    with caplog.at_level(logging.ERROR):
        assert manager.start("full") is False

    assert storage.release_calls == 1
    assert manager._status == {
        "status": "idle",
        "workflow_type": None,
        "workflow_id": None,
        "start_time": None,
        "current_step_index": -1,
        "steps": [],
        "error": None,
        "workflow_job_ids": [],
        "operation_id": None,
        "context": {},
    }
    assert manager._workflow_lease is None
    assert str(release_error) in caplog.text
    if isinstance(claim_result, BaseException):
        assert "PRIMARY claim failure" in caplog.text

    # A failed admission must not poison the manager's next lifecycle.
    manager._db_storage = None
    assert manager.start("full") is True
    assert manager.wait(2) is True


def test_workflow_release_does_not_swallow_process_signal_without_primary_outcome():
    storage = _StartStorage(False, KeyboardInterrupt("release interrupted"))

    with pytest.raises(KeyboardInterrupt, match="release interrupted"):
        release_workflow_lease_safely(
            storage,
            storage.lease,
            context="direct release",
        )


def test_workflow_start_resets_before_propagating_primary_process_signal(caplog):
    primary = KeyboardInterrupt("PRIMARY claim interrupt")
    release_error = RuntimeError("SECONDARY release failure")
    storage = _StartStorage(primary, release_error)
    manager = WorkflowManager()
    manager._db_storage = storage

    with caplog.at_level(logging.ERROR), pytest.raises(KeyboardInterrupt) as caught:
        manager.start("full")

    assert caught.value is primary
    assert manager._status["status"] == "idle"
    assert manager._status["workflow_id"] is None
    assert manager._workflow_lease is None
    assert storage.release_calls == 1
    assert str(release_error) in caplog.text


def test_workflow_thread_start_signal_releases_every_published_resource(monkeypatch):
    storage = _ThreadStartStorage()
    manager = WorkflowManager()
    manager._db_storage = storage
    primary = KeyboardInterrupt("workflow thread start interrupted")
    monkeypatch.setattr(threading.Thread, "start", lambda _thread: (_ for _ in ()).throw(primary))

    with pytest.raises(KeyboardInterrupt) as caught:
        manager.start("full")

    assert caught.value is primary
    assert storage.finalize_calls == 1
    assert storage.release_calls == 1
    assert manager._status["status"] == "idle"
    assert manager._thread is None
    assert manager._workflow_lease is None
    assert manager._workflow_heartbeat_stop is None
    assert manager._workflow_heartbeat_thread is None

    monkeypatch.undo()
    manager._db_storage = None
    assert manager.start("full") is True
    assert manager.wait(2) is True


def test_workflow_fallback_persistence_signal_resets_published_lifecycle():
    primary = KeyboardInterrupt("fallback persistence interrupted")
    storage = _FallbackStartStorage(primary)
    manager = WorkflowManager()
    manager._db_storage = storage

    with pytest.raises(KeyboardInterrupt) as caught:
        manager.start("full")

    assert caught.value is primary
    assert storage.finalize_calls == 1
    assert manager._status["status"] == "idle"
    assert manager._thread is None
    assert manager._workflow_lease is None


def test_workflow_operation_tracking_signal_releases_claim_and_resets():
    primary = KeyboardInterrupt("operation tracking interrupted")
    storage = _ThreadStartStorage()
    manager = WorkflowManager()
    manager._db_storage = storage
    manager._operation_tracker = _InterruptingOperationTracker(primary)

    with pytest.raises(KeyboardInterrupt) as caught:
        manager.start("full")

    assert caught.value is primary
    assert storage.finalize_calls == 1
    assert storage.release_calls == 1
    assert manager._status["status"] == "idle"
    assert manager._thread is None
    assert manager._workflow_lease is None
    assert manager._workflow_heartbeat_stop is None
    assert manager._workflow_heartbeat_thread is None


def test_scan_thread_start_signal_resets_published_lifecycle(monkeypatch):
    manager = ScanManager()
    primary = KeyboardInterrupt("scan thread start interrupted")
    monkeypatch.setattr(threading.Thread, "start", lambda _thread: (_ for _ in ()).throw(primary))

    with pytest.raises(KeyboardInterrupt) as caught:
        manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: {})

    assert caught.value is primary
    assert manager.is_running() is False
    assert manager._thread is None
    assert manager.get_status()["message"] == "Ricerca non avviata"

    monkeypatch.undo()
    assert manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: {}) is True
    assert manager.wait(2) is True


class _Query:
    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return None


class _RecoverySession:
    def __init__(self):
        self.closed = False
        self.rolled_back = False

    def query(self, *_args, **_kwargs):
        return _Query()

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _RecoveryStorage(StorageWorkflowMixin):
    def __init__(self, release_error=None):
        self.lease = object()
        self.session = _RecoverySession()
        self.release_calls = 0
        self.release_error = release_error or RuntimeError("SECONDARY release failure")

    def acquire_workflow_lease(self):
        return self.lease

    def _get_session(self):
        return self.session

    def _prune_workflows(self, _session, _now):
        raise SQLAlchemyError("PRIMARY prune failure")

    def release_workflow_lease(self, lease):
        assert lease is self.lease
        self.release_calls += 1
        raise self.release_error


class _RecoverySessionFailureStorage(StorageWorkflowMixin):
    def __init__(self):
        self.lease = object()
        self.release_calls = 0

    def acquire_workflow_lease(self):
        return self.lease

    def _get_session(self):
        raise RuntimeError("PRIMARY session acquisition failure")

    def release_workflow_lease(self, lease):
        assert lease is self.lease
        self.release_calls += 1


def test_recovery_preserves_prune_error_when_lease_release_also_fails(caplog):
    release_error = GeneratorExit("SECONDARY release exit")
    storage = _RecoveryStorage(release_error)

    with caplog.at_level(logging.ERROR), pytest.raises(StorageError, match="PRIMARY prune failure"):
        storage.recover_and_prune_workflows()

    assert storage.session.rolled_back is True
    assert storage.session.closed is True
    assert storage.release_calls == 1
    assert str(release_error) in caplog.text


def test_recovery_releases_lease_when_session_acquisition_fails():
    storage = _RecoverySessionFailureStorage()

    with pytest.raises(RuntimeError, match="PRIMARY session acquisition failure"):
        storage.recover_and_prune_workflows()

    assert storage.release_calls == 1
