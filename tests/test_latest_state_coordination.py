from copy import deepcopy
import threading
import time

import pytest

from emby_latest import db_state


class _MemoryStorage:
    def __init__(self, state=None, *, fail_save=False):
        self.state = deepcopy(state or {})
        self.fail_save = fail_save

    def load_latest_state(self):
        return deepcopy(self.state)

    def save_latest_state(self, state):
        if self.fail_save:
            raise RuntimeError("database unavailable")
        self.state = deepcopy(state)

    def clear_latest_state(self):
        self.state = {}


def _state(*, title="Movie", notified=False):
    return {
        "server-a": {
            "movies": {
                "items": {
                    "tmdb:1": {
                        "title": title,
                        "notified": notified,
                        "notified_at": "2026-08-30T10:00:00+00:00" if notified else "",
                    }
                }
            },
            "series": {"items": {}},
        }
    }


def test_collector_replacement_preserves_a_concurrent_notification_checkpoint():
    storage = _MemoryStorage(_state(title="Old"))
    repository = db_state.bind(storage)
    collector_snapshot = repository.load_state()
    collector_snapshot["server-a"]["movies"]["items"]["tmdb:1"]["title"] = "Fresh"

    repository.update_state(
        lambda current: db_state.merge_notification_updates(current, _state(notified=True)),
    )
    repository.replace_state_preserving_notifications(collector_snapshot)

    entry = storage.state["server-a"]["movies"]["items"]["tmdb:1"]
    assert entry["title"] == "Fresh"
    assert entry["notified"] is True


def test_latest_state_persistence_errors_are_not_reported_as_success():
    storage = _MemoryStorage(_state(), fail_save=True)
    with pytest.raises(RuntimeError, match="database unavailable"):
        db_state.save_state(_state(title="New"), db_storage=storage)


def test_clear_waits_for_inflight_state_update_and_wins_after_it():
    storage = _MemoryStorage(_state(title="Old"))
    updater_started = threading.Event()
    release_updater = threading.Event()

    def update() -> None:
        def mutate(current):
            updater_started.set()
            assert release_updater.wait(timeout=2)
            current["server-a"]["movies"]["items"]["tmdb:1"]["title"] = "Fresh"

        db_state.update_state(mutate, db_storage=storage)

    writer = threading.Thread(target=update)
    writer.start()
    assert updater_started.wait(timeout=1)

    reset = threading.Thread(target=db_state.clear_state, kwargs={"db_storage": storage})
    reset.start()
    time.sleep(0.05)
    assert reset.is_alive()

    release_updater.set()
    writer.join(timeout=2)
    reset.join(timeout=2)

    assert not writer.is_alive()
    assert not reset.is_alive()
    assert storage.state == {}
