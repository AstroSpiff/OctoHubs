"""Emby user manager registry wiring."""

from __future__ import annotations

from emby_users import registry


def test_user_manager_receives_the_shared_operation_tracker(monkeypatch):
    storage = object()
    shared_tracker = object()
    captured = {}

    class _Manager:
        def __init__(self, backend, config, operation_tracker=None):
            captured.update(
                backend=backend,
                config=config,
                operation_tracker=operation_tracker,
            )

        def update_config(self, config):
            captured["updated_config"] = config

    monkeypatch.setattr(registry, "_EMBY_USER_MANAGER", None)
    monkeypatch.setattr(registry, "EmbyUserManager", _Manager)

    manager = registry.get_emby_user_manager(
        ensure_db_backend=lambda: storage,
        get_db_backend=lambda: storage,
        get_active_config=lambda: {"configured": True},
        get_operation_tracker=lambda: shared_tracker,
    )

    assert manager is not None
    assert captured["backend"] is storage
    assert captured["operation_tracker"] is shared_tracker
    assert captured["updated_config"] == {"configured": True}
