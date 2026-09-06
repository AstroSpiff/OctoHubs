"""Tracked Emby scan single-flight regressions."""

from __future__ import annotations

import threading

from emby_libraries.tracker import LibraryScanTracker


def test_same_server_library_can_only_reserve_one_active_scan_job():
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    barrier = threading.Barrier(2)
    results = []

    def reserve():
        barrier.wait()
        results.append(tracker.create_job_unless_active("server-1", ["library-1"]))

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    created = [result for result in results if result[0] is not None]
    reused = [result for result in results if result[0] is None]
    assert len(created) == 1
    assert len(reused) == 1
    assert reused[0][1] == [created[0][0]]
    assert len(tracker.get_all_jobs()) == 1
