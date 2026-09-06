"""Latest reset must not report partial cleanup as success."""

from __future__ import annotations

import pytest

from emby_latest import db_cache, settings


class _FailingCacheStorage:
    def clear_latest_cache(self, _cache_kind=None):
        raise RuntimeError("cache unavailable")


def test_clear_cache_propagates_storage_failure():
    with pytest.raises(RuntimeError, match="cache unavailable"):
        db_cache.clear_cache(db_storage=_FailingCacheStorage())


def test_reset_stops_and_propagates_when_cache_clear_fails(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        settings,
        "clear_cache",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("cache unavailable")),
    )
    monkeypatch.setattr(settings, "clear_state", lambda **_kwargs: calls.append("state"))

    with pytest.raises(RuntimeError, match="cache unavailable"):
        settings._reset_latest_cache_state(db_storage=object())

    assert calls == []


def test_notification_state_clear_propagates_storage_failure(monkeypatch):
    monkeypatch.setattr(
        settings,
        "clear_state",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    with pytest.raises(RuntimeError, match="state unavailable"):
        settings._clear_latest_notification_state(db_storage=object())
