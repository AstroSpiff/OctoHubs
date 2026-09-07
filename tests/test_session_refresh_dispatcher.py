"""Bounded shutdown tests for the Emby Sessions dispatcher."""

from __future__ import annotations

import threading
import time

from realtime.session_refresh_dispatcher import SessionRefreshDispatcher


def test_shutdown_honors_deadline_for_blocked_callback():
    entered = threading.Event()
    release = threading.Event()

    def callback(_server_id, _data):
        entered.set()
        release.wait(2)

    dispatcher = SessionRefreshDispatcher(callback, max_workers=1)
    assert dispatcher.submit("server-a", {})
    assert entered.wait(1)

    started = time.monotonic()
    assert dispatcher.shutdown(0.02) is False
    assert time.monotonic() - started < 0.2
    assert dispatcher.submit("server-a", {}) is False
    release.set()


def test_shutdown_reports_completed_drain():
    dispatcher = SessionRefreshDispatcher(lambda _server_id, _data: None, max_workers=1)
    assert dispatcher.submit("server-a", {})
    assert dispatcher.shutdown(1.0) is True


def test_manager_rejects_sessions_arriving_during_shutdown(monkeypatch):
    from realtime import manager

    shutdown_entered = threading.Event()
    release_shutdown = threading.Event()

    class BlockingDispatcher:
        def submit(self, _server_id, _data):
            raise AssertionError("a closed lifecycle must not accept new work")

        def shutdown(self, _timeout_seconds):
            shutdown_entered.set()
            assert release_shutdown.wait(timeout=1)
            return True

    monkeypatch.setattr(manager, "_sessions_dispatcher", BlockingDispatcher())
    monkeypatch.setattr(manager, "_sessions_dispatcher_accepting", True)
    result = []
    shutdown = threading.Thread(
        target=lambda: result.append(manager.shutdown_session_refresh_dispatcher(1)),
    )
    shutdown.start()
    assert shutdown_entered.wait(timeout=1)

    assert manager._schedule_sessions_update("server-a", {}) is False
    assert manager._sessions_dispatcher is not None

    release_shutdown.set()
    shutdown.join(timeout=1)
    assert result == [True]
    assert manager._sessions_dispatcher is None


def test_manager_creates_only_one_dispatcher_for_concurrent_startup(monkeypatch):
    from realtime import manager
    from realtime import session_refresh_dispatcher

    created = []

    class FakeDispatcher:
        def __init__(self, _callback):
            created.append(self)

        def submit(self, _server_id, _data):
            return True

        def shutdown(self, _timeout_seconds):
            return True

    monkeypatch.setattr(session_refresh_dispatcher, "SessionRefreshDispatcher", FakeDispatcher)
    monkeypatch.setattr(manager, "_sessions_dispatcher", None)
    monkeypatch.setattr(manager, "_sessions_dispatcher_accepting", False)

    callers = [threading.Thread(target=manager.initialize_session_refresh_dispatcher) for _ in range(8)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=1)

    assert len(created) == 1
    assert manager._sessions_dispatcher is created[0]
    assert manager.shutdown_session_refresh_dispatcher(1) is True
