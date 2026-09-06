"""Concurrency coverage for Latest notification delivery."""

from __future__ import annotations

from copy import deepcopy
import threading
from unittest.mock import patch

from emby_latest.notifications import send_notifications
from emby_latest.notification_delivery import (
    begin_notification_dispatch,
    complete_notification_dispatch,
    notification_dispatch_key,
    wait_for_notification_dispatch,
)


def _cache_payload() -> dict:
    return {
        "payload": {
            "movies": [
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "batch_id": "batch-1",
                    "item_type": "movie",
                    "title": "Movie",
                    "year": 2026,
                    "added_at": "2026-08-30T10:00:00+00:00",
                }
            ],
            "series": [],
        }
    }


def _latest_settings() -> dict:
    return {
        "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{{ title }}"}],
        "NOTIFICATION_RULES": [
            {
                "id": "rule-a",
                "name": "Rule A",
                "enabled": True,
                "server_ids": ["server-a"],
                "preset_id": "preset-a",
                "telegram_config_id": "telegram-a",
            }
        ],
    }


def _telegram_settings() -> dict:
    return {
        "PRESETS": [
            {
                "id": "telegram-a",
                "name": "Telegram",
                "bot_ids": ["bot-a"],
                "group_ids": ["group-a"],
                "channel_ids": [],
            }
        ],
        "BOTS": [{"id": "bot-a", "token": "token"}],
        "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
        "CHANNELS": [],
    }


def _config() -> dict:
    return {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}}


class _NotificationStorage:
    def __init__(self, *, persist_state: bool = True):
        self._lock = threading.Lock()
        self._state: dict = {}
        self._claims: dict[str, dict] = {}
        self.persist_state = persist_state

    def load_latest_cache(self, cache_kind):
        return deepcopy(_cache_payload()) if cache_kind == "batch" else {}

    def load_latest_state(self):
        with self._lock:
            return deepcopy(self._state) if self.persist_state else {}

    def save_latest_state(self, state):
        if self.persist_state:
            with self._lock:
                self._state = deepcopy(state)

    def claim_latest_notification_delivery(self, **payload):
        with self._lock:
            existing = self._claims.get(payload["delivery_key"])
            if existing is None or existing["status"] == "failed":
                self._claims[payload["delivery_key"]] = {
                    "status": "claimed",
                    "claim_token": payload["claim_token"],
                }
                return "acquired"
            return "sent" if existing["status"] == "sent" else "in_progress"

    def complete_latest_notification_delivery(self, **payload):
        with self._lock:
            existing = self._claims.get(payload["delivery_key"])
            if not existing or existing["claim_token"] != payload["claim_token"]:
                return False
            existing["status"] = "sent"
            return True

    def fail_latest_notification_delivery(self, **payload):
        with self._lock:
            existing = self._claims.get(payload["delivery_key"])
            if not existing or existing["claim_token"] != payload["claim_token"]:
                return False
            existing["status"] = "failed"
            return True


def _notification_patches(send_request):
    return (
        patch("emby_latest.settings._load_latest_settings", return_value=_latest_settings()),
        patch("telegram._load_telegram_settings", return_value=_telegram_settings()),
        patch("emby_latest.jellyseerr._apply_jellyseerr_request_info", return_value=None),
        patch("emby_latest.notifications._telegram_api_request", side_effect=send_request),
        patch("time.sleep", return_value=None),
    )


def test_two_synchronized_notifiers_send_only_once():
    storage = _NotificationStorage(persist_state=True)
    entered_provider = threading.Event()
    release_provider = threading.Event()
    deliveries = []
    results = []

    def send_request(_token, _method, params):
        deliveries.append(params["chat_id"])
        entered_provider.set()
        assert release_provider.wait(timeout=3)
        return True, "OK", {}

    patches = _notification_patches(send_request)
    for active_patch in patches:
        active_patch.start()
    try:
        first = threading.Thread(
            target=lambda: results.append(send_notifications(10, config=_config(), db_storage=storage))
        )
        second = threading.Thread(
            target=lambda: results.append(send_notifications(10, config=_config(), db_storage=storage))
        )
        first.start()
        assert entered_provider.wait(timeout=3)
        second.start()
        assert second.is_alive()
        release_provider.set()
        first.join(timeout=3)
        second.join(timeout=3)
        assert not first.is_alive()
        assert not second.is_alive()
    finally:
        release_provider.set()
        for active_patch in reversed(patches):
            active_patch.stop()

    assert deliveries == ["chat"]
    assert [result["sent"] for result in results] == [1, 1]
    assert all(result["success"] for result in results)


def test_notification_waiter_observes_the_exact_partial_generation_outcome():
    owner = begin_notification_dispatch()
    waiter = begin_notification_dispatch()
    partial = {
        "success": False,
        "status": "partial",
        "sent": 1,
        "failed": 1,
        "errors": ["destination failed"],
    }

    assert owner.owner is True
    assert waiter.owner is False
    assert waiter.generation == owner.generation
    complete_notification_dispatch(owner, partial)

    assert wait_for_notification_dispatch(waiter, timeout_seconds=0) == partial


def test_notification_dispatch_identity_is_stable_and_request_scoped():
    storage = object()
    first = notification_dispatch_key(
        per_server_limit=10,
        server_filter="server-a",
        config={"B": 2, "A": 1},
        storage=storage,
    )

    assert first == notification_dispatch_key(
        per_server_limit=10,
        server_filter="server-a",
        config={"A": 1, "B": 2},
        storage=storage,
    )
    assert first != notification_dispatch_key(
        per_server_limit=10,
        server_filter="server-b",
        config={"A": 1, "B": 2},
        storage=storage,
    )
    assert first != notification_dispatch_key(
        per_server_limit=20,
        server_filter="server-a",
        config={"A": 1, "B": 2},
        storage=storage,
    )


def test_different_server_filters_run_distinct_notification_dispatches():
    storage = _NotificationStorage()
    first_entered = threading.Event()
    release_first = threading.Event()
    calls: list[str | None] = []
    results: dict[str, dict] = {}

    def dispatch(*, server_filter=None, **_kwargs):
        calls.append(server_filter)
        if server_filter == "server-a":
            first_entered.set()
            assert release_first.wait(timeout=3)
        return {
            "success": True,
            "status": "success",
            "sent": 1,
            "failed": 0,
            "errors": [],
            "server_filter": server_filter,
        }

    with patch(
        "emby_latest.notifications._send_notifications_unlocked",
        side_effect=dispatch,
    ):
        first = threading.Thread(
            target=lambda: results.setdefault(
                "a",
                send_notifications(
                    10,
                    server_filter="server-a",
                    config=_config(),
                    db_storage=storage,
                ),
            )
        )
        second = threading.Thread(
            target=lambda: results.setdefault(
                "b",
                send_notifications(
                    10,
                    server_filter="server-b",
                    config=_config(),
                    db_storage=storage,
                ),
            )
        )
        first.start()
        assert first_entered.wait(timeout=3)
        second.start()
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == ["server-a", "server-b"]
    assert results["a"]["server_filter"] == "server-a"
    assert results["b"]["server_filter"] == "server-b"


def test_persistent_delivery_key_prevents_resend_when_state_checkpoint_is_missing():
    storage = _NotificationStorage(persist_state=False)
    deliveries = []

    def send_request(_token, _method, params):
        deliveries.append(params["chat_id"])
        return True, "OK", {}

    patches = _notification_patches(send_request)
    for active_patch in patches:
        active_patch.start()
    try:
        first = send_notifications(10, config=_config(), db_storage=storage)
        second = send_notifications(10, config=_config(), db_storage=storage)
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()

    assert first["sent"] == 1
    assert second["sent"] == 0
    assert second["success"] is True
    assert deliveries == ["chat"]
