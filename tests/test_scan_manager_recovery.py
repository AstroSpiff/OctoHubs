"""Regression coverage for background scan lifecycle failures."""

import threading

from core.tasks import ScanManager


def test_scan_manager_is_reusable_after_callback_failure():
    manager = ScanManager()

    def fail_scan(*_args, **_kwargs):
        raise RuntimeError("boom")

    assert manager.start_scan({}, process_requests_func=fail_scan) is True
    manager._thread.join(timeout=2)

    status = manager.get_status()
    assert status["running"] is False
    assert status["message"] == "Ricerca non riuscita"

    assert manager.start_scan(
        {},
        process_requests_func=lambda *_args, **_kwargs: {"processed": 0},
    ) is True
    manager._thread.join(timeout=2)
    assert manager.get_status()["running"] is False


def test_scan_manager_wait_cannot_miss_a_worker_being_registered(monkeypatch):
    manager = ScanManager()
    constructor_entered = threading.Event()
    release_constructor = threading.Event()
    wait_finished = threading.Event()
    original_thread = threading.Thread

    class DeferredThread:
        def __init__(self, **_kwargs):
            self.alive = False
            constructor_entered.set()
            assert release_constructor.wait(2)

        def start(self):
            self.alive = True

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return self.alive

    monkeypatch.setattr("core.tasks.threading.Thread", DeferredThread)
    starter = original_thread(
        target=lambda: manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: None)
    )
    starter.start()
    assert constructor_entered.wait(2)

    result = []

    def wait_for_worker():
        result.append(manager.wait(0))
        wait_finished.set()

    waiter = original_thread(target=wait_for_worker)
    waiter.start()
    assert not wait_finished.wait(0.05)

    manager.stop_scan()
    release_constructor.set()
    starter.join(2)
    waiter.join(2)

    assert wait_finished.is_set()
    assert result == [False]
