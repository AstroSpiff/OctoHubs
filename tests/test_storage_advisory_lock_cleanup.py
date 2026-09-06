from types import SimpleNamespace

import pytest

from core.storage.storage_core import StorageCoreMixin


class _Result:
    def scalar(self):
        return True


class _FailingUnlockSession:
    def __init__(self):
        self.execute_count = 0
        self.closed = False
        self.invalidated = False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        if self.execute_count == 2:
            raise RuntimeError("connection lost during unlock")
        return _Result()

    def rollback(self):
        return None

    def invalidate(self):
        self.invalidated = True

    def close(self):
        self.closed = True


class _Storage(StorageCoreMixin):
    def __init__(self, session):
        self.session = session

    def _get_session(self):
        return self.session


def test_advisory_lock_always_closes_session_when_unlock_fails():
    session = _FailingUnlockSession()

    with pytest.raises(RuntimeError, match="connection lost"):
        with _Storage(session).advisory_lock("test") as acquired:
            assert acquired is True

    assert session.invalidated is True
    assert session.closed is True


def test_advisory_lock_preserves_primary_error_when_unlock_also_fails():
    session = _FailingUnlockSession()

    with pytest.raises(ValueError, match="primary"):
        with _Storage(session).advisory_lock("test"):
            raise ValueError("primary")

    assert session.invalidated is True
    assert session.closed is True
