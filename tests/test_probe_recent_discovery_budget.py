"""Regression coverage for bounded Emby recent-discovery pages."""

from __future__ import annotations

from datetime import datetime, timezone
import threading

from emby_probe.manager import EmbyProbeManager
from emby_probe.recent import RECENT_DISCOVERY_MAX_PAGE_SIZE


class _RecentStorage:
    def __init__(self, config: dict | None = None) -> None:
        self.checkpoints: list[tuple[str, datetime]] = []
        self.config = config or {}

    def get_probe_config(self, _server_id: str) -> dict:
        return self.config

    def get_recent_scan_timestamp(self, _server_id: str):
        return None

    def load_probe_blacklist(self, _server_id: str, *, scope: str) -> dict:
        assert scope == "recent"
        return {}

    def add_to_probe_queue(self, _items: list[dict]) -> None:
        raise AssertionError("Gli elementi completi non devono entrare in coda")

    def save_recent_scan_timestamp(
        self,
        server_id: str,
        timestamp: datetime,
    ) -> None:
        self.checkpoints.append((server_id, timestamp))


def test_recent_discovery_paginates_rich_items_within_json_node_budget(monkeypatch):
    manager = EmbyProbeManager()
    storage = _RecentStorage()
    manager.configure(lambda: storage)
    manager._status = {
        "server-a": {
            "recent_discovery": {
                "running": True,
                "found": 0,
                "total_scanned": 0,
            }
        }
    }
    item_count = RECENT_DISCOVERY_MAX_PAGE_SIZE * 2 + 7
    items = [
        {
            "Id": f"item-{index}",
            "Name": f"Item {index}",
            "Type": "Movie",
            "Path": f"/media/item-{index}.strm",
            "DateCreated": datetime.now(timezone.utc).isoformat(),
            "RunTimeTicks": 1,
            "MediaStreams": [{"Type": "Video"}],
        }
        for index in range(item_count)
    ]
    item_requests: list[tuple[int, int]] = []

    def call_emby_api(_server, path, *, method="GET", params=None, **_kwargs):
        assert method == "GET"
        if path == "Library/VirtualFolders":
            return True, []
        assert path == "Items"
        start = int(params["StartIndex"])
        page_size = int(params["Limit"])
        item_requests.append((start, page_size))
        return True, {"Items": items[start : start + page_size]}

    monkeypatch.setattr("emby_probe.recent._call_emby_api", call_emby_api)

    manager._recent_discovery_worker(
        {"id": "server-a", "name": "Blue"},
        "server-a",
        threading.Event(),
        200,
    )

    status = manager.get_status("server-a")["recent_discovery"]
    assert item_requests == [(0, 50), (50, 50), (100, 50), (150, 50)]
    assert all(page_size <= RECENT_DISCOVERY_MAX_PAGE_SIZE for _, page_size in item_requests)
    assert status["running"] is False
    assert status["total_scanned"] == item_count
    assert "Discovery completata" in status["last_log"]
    assert storage.checkpoints and storage.checkpoints[0][0] == "server-a"


def _run_bounded_discovery(
    monkeypatch,
    *,
    config: dict,
    items: list[dict],
    status_updates: list[dict] | None = None,
):
    manager = EmbyProbeManager()
    storage = _RecentStorage(config)
    manager.configure(lambda: storage)
    manager._status = {
        "server-a": {
            "recent_discovery": {
                "running": True,
                "found": 0,
                "total_scanned": 0,
            }
        }
    }
    if status_updates is not None:
        original_update = manager._update_status

        def record_update(server_id: str, worker_type: str, **kwargs):
            status_updates.append(dict(kwargs))
            original_update(server_id, worker_type, **kwargs)

        monkeypatch.setattr(manager, "_update_status", record_update)
    stop_flag = threading.Event()

    def call_emby_api(_server, path, *, method="GET", params=None, **_kwargs):
        assert method == "GET"
        if path == "Library/VirtualFolders":
            return True, [{"Id": "movies", "Name": "Film", "Locations": ["/media"]}]
        assert path == "Items"
        start = int(params["StartIndex"])
        page_size = int(params["Limit"])
        return True, {"Items": items[start : start + page_size]}

    monkeypatch.setattr("emby_probe.recent._call_emby_api", call_emby_api)
    manager._recent_discovery_worker(
        {"id": "server-a", "name": "Blue"},
        "server-a",
        stop_flag,
        200,
    )
    return manager.get_status("server-a")["recent_discovery"], stop_flag


def _complete_item(index: int, created_at: datetime | None = None) -> dict:
    return {
        "Id": f"item-{index}",
        "Name": f"Item {index}",
        "Type": "Movie",
        "Path": f"/media/item-{index}.strm",
        "DateCreated": (created_at or datetime.now(timezone.utc)).isoformat(),
        "RunTimeTicks": 1,
        "MediaStreams": [{"Type": "Video"}],
    }


def test_recent_discovery_age_boundary_is_success_not_user_interruption(monkeypatch):
    old_item = _complete_item(
        1,
        datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    status, stop_flag = _run_bounded_discovery(
        monkeypatch,
        config={"max_days": 7},
        items=[old_item],
    )

    assert not stop_flag.is_set()
    assert "Discovery completata" in status["last_log"]
    assert "finestra di 7 giorni" in status["last_log"]
    assert "interrotta" not in status["last_log"].lower()


def test_recent_discovery_item_budget_is_success_not_user_interruption(monkeypatch):
    status, stop_flag = _run_bounded_discovery(
        monkeypatch,
        config={"max_items": 500, "window_size": 2000},
        items=[_complete_item(index) for index in range(501)],
    )

    assert not stop_flag.is_set()
    assert status["total_scanned"] == 500
    assert status["limit"] == 500
    assert "Discovery completata" in status["last_log"]
    assert "limite di 500 elementi" in status["last_log"]


def test_recent_discovery_complete_window_is_success_not_user_interruption(monkeypatch):
    status, stop_flag = _run_bounded_discovery(
        monkeypatch,
        config={"window_size": 100, "window_threshold": 0.9},
        items=[_complete_item(index) for index in range(100)],
    )

    assert not stop_flag.is_set()
    assert status["total_scanned"] == 100
    assert "Discovery completata" in status["last_log"]
    assert "finestra di 100 elementi" in status["last_log"]


def test_recent_discovery_publishes_live_item_and_library_without_extra_api_calls(
    monkeypatch,
):
    updates: list[dict] = []
    _run_bounded_discovery(
        monkeypatch,
        config={},
        items=[_complete_item(1)],
        status_updates=updates,
    )[0]

    assert any(
        update.get("current_item") == "Item 1"
        and update.get("current_library_name") == "Film"
        for update in updates
    )
