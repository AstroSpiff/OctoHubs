from __future__ import annotations

from emby_users.auto_sync_manager import AutoSyncManager
from emby_users.group_manager import GroupManager


class _SettingsStorage:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def update_key_value(self, key, updater):
        updated = updater(self.values.get(key))
        self.values[key] = updated
        return updated


def test_disabling_automation_preserves_manual_sync_configuration_and_bootstrap() -> None:
    storage = _SettingsStorage()
    manager = GroupManager(storage, object(), lambda: {"groups": []})

    assert manager.save_group_settings(
        "family",
        False,
        "one_way",
        True,
        sync_playstate=True,
        sync_config=True,
        sync_library_access=True,
        sync_favorites=True,
        sync_playlists=True,
        config_categories=["profile", "display"],
        playstate_bootstrap_done=True,
        favorites_bootstrap_done=True,
        playlists_bootstrap_done=True,
    )

    saved = storage.values["group_settings:family"]
    assert saved == {
        "auto_sync": False,
        "sync_type": "one_way",
        "sync_resume": True,
        "sync_playstate": True,
        "sync_config": True,
        "sync_library_access": True,
        "sync_favorites": True,
        "sync_playlists": True,
        "config_categories": ["profile", "display"],
        "playstate_bootstrap_done": True,
        "favorites_bootstrap_done": True,
        "playlists_bootstrap_done": True,
    }


def test_disabling_a_domain_resets_only_that_domain_bootstrap() -> None:
    storage = _SettingsStorage()
    manager = GroupManager(storage, object(), lambda: {"groups": []})

    assert manager.save_group_settings(
        "family",
        False,
        "merge",
        False,
        sync_playstate=True,
        sync_favorites=False,
        sync_playlists=True,
        playstate_bootstrap_done=True,
        favorites_bootstrap_done=True,
        playlists_bootstrap_done=True,
    )

    saved = storage.values["group_settings:family"]
    assert isinstance(saved, dict)
    assert saved["playstate_bootstrap_done"] is True
    assert saved["favorites_bootstrap_done"] is False
    assert saved["playlists_bootstrap_done"] is True


def test_manual_sync_uses_saved_settings_when_automation_is_disabled(monkeypatch) -> None:
    group = {
        "id": "family",
        "auto_sync": False,
        "sync_type": "one_way",
        "sync_playstate": True,
        "sync_favorites": True,
    }
    captured: list[dict[str, object]] = []
    manager = AutoSyncManager.__new__(AutoSyncManager)
    manager._operation_tracker = None
    manager._get_users_dashboard_data = lambda: {"groups": [group]}
    manager._update_operation = lambda *_args, **_kwargs: None
    manager._mark_group_sync_result = lambda *_args, **_kwargs: True

    def run(candidate, operation_id=None):
        captured.append(dict(candidate))
        return {"status": "success", "message": "Completata"}

    manager._sync_group_singleflight = run
    monkeypatch.setattr(
        "emby_users.auto_sync_manager._publish_users_sync_updated",
        lambda: None,
    )

    result = manager.run_group_sync("family")

    assert result["ok"] is True
    assert captured == [group]


def test_automatic_sync_still_skips_groups_with_automation_disabled(monkeypatch) -> None:
    groups = [
        {"id": "manual", "auto_sync": False},
        {"id": "automatic", "auto_sync": True},
    ]
    attempted: list[str] = []
    manager = AutoSyncManager.__new__(AutoSyncManager)
    manager._get_users_dashboard_data = lambda: {"groups": groups}

    def run(group):
        attempted.append(group["id"])
        return {"status": "success"}

    manager._sync_group_singleflight = run
    monkeypatch.setattr(
        "emby_users.auto_sync_manager._publish_users_sync_updated",
        lambda: None,
    )

    result = manager.run_auto_sync()

    assert attempted == ["automatic"]
    assert result["succeeded"] == ["automatic"]
    assert result["attempted"] is True
