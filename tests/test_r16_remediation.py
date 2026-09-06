"""Cross-cutting regressions found during the sixteenth review pass."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.storage import DatabaseStorage
from core.storage.storage_models import ScanResultEntry
from search.manual_search_results import _collect_provider_results
from search.outbound_execution import (
    initialize_search_executor,
    shutdown_search_executor,
)
from search.stream_limits import MAX_GLOBAL_OUTBOUND_SEARCHES


def test_manual_searches_share_the_global_outbound_concurrency_budget():
    assert shutdown_search_executor(timeout_seconds=5)
    initialize_search_executor()
    active = 0
    peak_active = 0
    activity_lock = threading.Lock()
    callers_ready = threading.Barrier(10)

    def provider(*_args):
        nonlocal active, peak_active
        with activity_lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            time.sleep(0.05)
            return [{"title": "result"}]
        finally:
            with activity_lock:
                active -= 1

    tasks = [
        ("prowlarr", provider, "query", "movie", {}),
        ("jackett", provider, "query", "movie", {}),
    ]

    def call_manual_search():
        callers_ready.wait(timeout=3)
        collected, _completed, _truncated = _collect_provider_results(tasks, [])
        return collected

    try:
        with ThreadPoolExecutor(max_workers=10) as callers:
            results = list(callers.map(lambda _index: call_manual_search(), range(10)))
        assert all(len(result) == 2 for result in results)
        assert peak_active <= MAX_GLOBAL_OUTBOUND_SEARCHES
    finally:
        assert shutdown_search_executor(timeout_seconds=5)
        initialize_search_executor()


def _scan_storage(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'scan-results.db'}"
    engine = create_engine(database_url, future=True)
    ScanResultEntry.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    return storage, engine


def test_scan_results_use_id_as_a_deterministic_timestamp_tiebreaker(tmp_path):
    storage, engine = _scan_storage(tmp_path)
    generated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with storage._get_session() as session:
        for marker in ("first", "second"):
            entry = ScanResultEntry(generated_at=generated_at)
            entry.payload = {"marker": marker}
            session.add(entry)
        session.commit()

    assert storage.load_last_result() == {"marker": "second"}
    assert storage.delete_scan_results(keep_last=1) == 1
    assert storage.load_last_result() == {"marker": "second"}
    storage.close()
    engine.dispose()


def test_scan_cleanup_serializes_with_a_concurrent_scan_writer(tmp_path):
    storage, engine = _scan_storage(tmp_path)
    storage.save_scan_result({"generated_at": "2026-09-01T12:00:00+00:00", "marker": "base"})
    transform_entered = threading.Event()
    release_transform = threading.Event()
    errors: list[BaseException] = []

    def transform(payload):
        transform_entered.set()
        assert release_transform.wait(timeout=3)
        return {**payload, "marker": "cleaned"}, "cleaned"

    def run_cleanup():
        try:
            assert storage.mutate_last_scan_result(transform) == "cleaned"
        except BaseException as exc:  # pragma: no cover - assertion relay
            errors.append(exc)

    def run_scan():
        try:
            storage.save_scan_result(
                {"generated_at": "2099-01-01T00:00:00+00:00", "marker": "new-scan"}
            )
        except BaseException as exc:  # pragma: no cover - assertion relay
            errors.append(exc)

    cleanup = threading.Thread(target=run_cleanup)
    cleanup.start()
    assert transform_entered.wait(timeout=3)
    scan = threading.Thread(target=run_scan)
    scan.start()
    time.sleep(0.05)
    assert scan.is_alive()
    release_transform.set()
    cleanup.join(timeout=3)
    scan.join(timeout=3)

    assert not errors
    assert not cleanup.is_alive()
    assert not scan.is_alive()
    assert storage.load_last_result()["marker"] == "new-scan"
    storage.close()
    engine.dispose()
