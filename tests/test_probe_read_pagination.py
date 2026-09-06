"""Regression coverage for bounded Probe read endpoints."""

from __future__ import annotations

import asyncio

from emby_probe import routes, snapshots


class _Backend:
    def __init__(self):
        self.calls = []

    def get_probe_queue(self, server_id, **kwargs):
        self.calls.append(("queue", server_id, kwargs))
        return [{"id": index + 1, "item_id": str(index)} for index in range(3)]

    def get_probe_history(self, server_id, limit, **kwargs):
        self.calls.append(("history", server_id, {"limit": limit, **kwargs}))
        return [{"id": 10 - index, "item_id": str(index)} for index in range(3)]

    def get_probe_blacklist(self, server_id, **kwargs):
        self.calls.append(("blacklist", server_id, kwargs))
        return [{"id": 20 - index, "item_id": str(index)} for index in range(3)]


def test_probe_snapshots_reject_unbounded_windows(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr(snapshots, "_ensure_db_backend", lambda: backend)

    for value in ("-1", "0", "501", "1000000000", "invalid"):
        payload, status = snapshots._probe_history_get_snapshot(
            "green", value, "libraries"
        )
        assert status == 422
        assert payload["success"] is False

    assert backend.calls == []


def test_probe_snapshots_return_bounded_pages(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr(snapshots, "_ensure_db_backend", lambda: backend)

    queue, queue_status = snapshots._probe_queue_get_snapshot(
        "green", "recent", "2", "0"
    )
    history, history_status = snapshots._probe_history_get_snapshot(
        "green", "2", "libraries", "4"
    )
    blacklist, blacklist_status = snapshots._probe_blacklist_get_snapshot(
        "green", "0", None, "libraries", "2", "6"
    )

    assert (queue_status, history_status, blacklist_status) == (200, 200, 200)
    assert len(queue["queue"]) == len(history["history"]) == len(blacklist["blacklist"]) == 2
    assert queue["next_offset"] == 2
    assert history["next_offset"] == 6
    assert blacklist["next_offset"] == 8
    assert backend.calls == [
        ("queue", "green", {"scope": "recent", "limit": 3, "offset": 0}),
        ("history", "green", {"limit": 3, "scope": "libraries", "offset": 4}),
        (
            "blacklist",
            "green",
            {
                "min_retry_count": 0,
                "error_type": None,
                "scope": "libraries",
                "limit": 3,
                "offset": 6,
            },
        ),
    ]


def test_probe_cursor_pages_use_stable_row_ids(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr(snapshots, "_ensure_db_backend", lambda: backend)

    queue, queue_status = snapshots._probe_queue_get_snapshot(
        "green", "recent", "2", "0", "0"
    )
    history, history_status = snapshots._probe_history_get_snapshot(
        "green", "2", "libraries", "0", "11"
    )
    blacklist, blacklist_status = snapshots._probe_blacklist_get_snapshot(
        "green", "0", "error", "libraries", "2", "0", "21"
    )

    assert (queue_status, history_status, blacklist_status) == (200, 200, 200)
    assert queue["next_offset"] is history["next_offset"] is blacklist["next_offset"] is None
    assert queue["next_cursor"] == 2
    assert history["next_cursor"] == 9
    assert blacklist["next_cursor"] == 19
    assert backend.calls == [
        (
            "queue",
            "green",
            {"scope": "recent", "limit": 3, "offset": 0, "cursor_id": 0},
        ),
        (
            "history",
            "green",
            {"limit": 3, "scope": "libraries", "offset": 0, "cursor_id": 11},
        ),
        (
            "blacklist",
            "green",
            {
                "min_retry_count": 0,
                "error_type": "error",
                "scope": "libraries",
                "limit": 3,
                "offset": 0,
                "cursor_id": 21,
            },
        ),
    ]


def test_probe_csv_export_streams_successive_pages(monkeypatch):
    calls = []

    def page(_server_id, _min_retry, _error_type, _scope, _limit, offset):
        calls.append(offset)
        if offset == "0":
            return {
                "success": True,
                "blacklist": [
                    {
                        "server_id": "green",
                        "item_name": "=unsafe",
                        "retry_count": 3,
                        "error_type": "ERROR",
                    }
                ],
                "next_offset": 1,
            }, 200
        return {
            "success": True,
            "blacklist": [
                {
                    "server_id": "green",
                    "item_name": "second",
                    "retry_count": 0,
                    "error_type": "INCOMPLETE",
                }
            ],
            "next_offset": None,
        }, 200

    monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 1)
    monkeypatch.setattr(routes, "load_config", lambda: ({"EMBY": {"SERVERS": []}}, True))
    monkeypatch.setattr(routes, "_probe_blacklist_get_snapshot", page)

    class _Request:
        query_params = {"server_id": "green", "scope": "libraries"}

    async def collect():
        response = await routes.probe_export_csv(_Request())
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(chunks).decode()

    body = asyncio.run(collect())

    assert calls == ["0", "1"]
    assert "'=unsafe" in body
    assert "second" in body
