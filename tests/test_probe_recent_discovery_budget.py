"""Regression coverage for bounded Emby recent-discovery pages."""

from __future__ import annotations

from datetime import datetime, timezone
import threading

from emby_probe.manager import EmbyProbeManager
from emby_probe.recent import RECENT_DISCOVERY_MAX_PAGE_SIZE


class _RecentStorage:
    def __init__(self) -> None:
        self.checkpoints: list[tuple[str, datetime]] = []

    def get_probe_config(self, _server_id: str) -> dict:
        return {}

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
