"""Regression coverage for background scan lifecycle failures."""

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
