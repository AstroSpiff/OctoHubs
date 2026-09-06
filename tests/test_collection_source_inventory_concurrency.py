from __future__ import annotations

import copy
import threading

from emby_collections import source_inventory


class _AtomicInventoryStorage:
    def __init__(self) -> None:
        self.values = {}
        self._lock = threading.Lock()
        self.barrier: threading.Barrier | None = None
        self.update_calls = 0

    def get_key_value(self, key):
        barrier = self.barrier
        if barrier is not None:
            barrier.wait(timeout=3)
        with self._lock:
            return copy.deepcopy(self.values.get(key))

    def set_key_value(self, key, value):
        with self._lock:
            self.values[key] = copy.deepcopy(value)

    def update_key_value(self, key, updater):
        barrier = self.barrier
        if barrier is not None:
            barrier.wait(timeout=3)
        with self._lock:
            self.update_calls += 1
            updated = updater(copy.deepcopy(self.values.get(key)))
            self.values[key] = copy.deepcopy(updated)
            return copy.deepcopy(updated)


def _source(name: str, value: str) -> dict[str, str]:
    return {
        "name": name,
        "source_type": "tmdb_list",
        "source_value": value,
    }


def test_concurrent_inventory_adds_preserve_both_sources(monkeypatch):
    storage = _AtomicInventoryStorage()
    storage.barrier = threading.Barrier(2)
    monkeypatch.setattr(source_inventory, "_ensure_db_backend", lambda: storage)
    errors = []

    def add(payload):
        try:
            source_inventory.add_source_inventory_item(payload)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=add, args=(_source("First", "101"),)),
        threading.Thread(target=add, args=(_source("Second", "202"),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    storage.barrier = None
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert storage.update_calls == 2
    assert {
        item["source_value"]
        for item in source_inventory.list_source_inventory()
    } == {"101", "202"}


def test_concurrent_inventory_add_and_delete_do_not_restore_deleted_source(monkeypatch):
    storage = _AtomicInventoryStorage()
    monkeypatch.setattr(source_inventory, "_ensure_db_backend", lambda: storage)
    existing = source_inventory.add_source_inventory_item(_source("Old", "101"))
    storage.barrier = threading.Barrier(2)
    errors = []
    removed = []

    def add_new_source():
        try:
            source_inventory.add_source_inventory_item(_source("New", "202"))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def remove_old_source():
        try:
            removed.append(source_inventory.remove_source_inventory_item(existing["id"]))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=add_new_source),
        threading.Thread(target=remove_old_source),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    storage.barrier = None
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert removed == [True]
    assert storage.update_calls == 3
    assert [
        item["source_value"]
        for item in source_inventory.list_source_inventory()
    ] == ["202"]
