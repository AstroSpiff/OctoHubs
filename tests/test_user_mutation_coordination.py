"""Concurrency regressions for remote Emby user mutations."""

from __future__ import annotations

import threading

from emby_users.password_manager import PasswordManager
from emby_users.mutation_coordinator import (
    UserMutationCoordinator,
    server_mutation_key,
    user_mutation_keys,
)
from emby_users.settings_manager import SettingsManager
from emby_users.user_ops_manager import UserOpsManager


class _Storage:
    def __init__(self):
        self.values = {}
        self.passwords = {}

    def set_key_value(self, key, value):
        self.values[key] = value

    def save_group_password(self, key, value):
        self.passwords[key] = value

    def delete_group_password(self, key):
        self.passwords.pop(key, None)


def test_concurrent_group_password_writes_cannot_interleave_targets():
    storage = _Storage()
    started = threading.Event()
    release = threading.Event()
    remote = {}

    def update(_server, user_id, password):
        if password == "first" and not started.is_set():
            started.set()
            release.wait(timeout=2)
        remote[user_id] = password
        return True, None

    manager = PasswordManager(
        storage=storage,
        get_server_by_id=lambda server_id: {"id": server_id},
        get_group_users=lambda _group_id: [
            ("server-a", "user-a", None),
            ("server-b", "user-b", None),
        ],
        get_unlinked_group_id=lambda server_id, user_id: f"{server_id}:{user_id}",
        update_user_password=update,
    )
    manager.encrypt_password = lambda value: f"encrypted:{value}"
    first_result = {}
    thread = threading.Thread(
        target=lambda: first_result.update(manager.set_group_password("group-a", "first"))
    )
    thread.start()
    assert started.wait(timeout=1)

    competing = manager.set_group_password("group-a", "second")
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert first_result["ok"] is True
    assert competing["ok"] is False
    assert competing["busy"] is True
    assert remote == {"user-a": "first", "user-b": "first"}
    assert storage.passwords["group-a"] == "encrypted:first"


def test_group_settings_fence_blocks_overlapping_single_user_write():
    storage = _Storage()
    users = [("server-a", "user-a", None), ("server-b", "user-b", None)]
    started = threading.Event()
    release = threading.Event()
    remote = {}

    def update_config(_server, user_id, payload):
        value = payload.get("AudioLanguagePreference")
        if value == "first" and user_id == "user-a":
            started.set()
            release.wait(timeout=2)
        remote[user_id] = value
        return True, None

    manager = SettingsManager(
        storage=storage,
        config={},
        get_server_by_id=lambda server_id: {"id": server_id},
        get_group_users=lambda _group_id: list(users),
        fetch_user_details=lambda _server, _user_id: ({"Policy": {}, "Configuration": {}}, None),
        update_user_policy=lambda _server, _user_id, _payload: (True, None),
        update_user_config=update_config,
        fetch_user_display_preferences=lambda _server, _user_id: ({"CustomPrefs": {}}, None),
        update_user_display_preferences=lambda _server, _user_id, _payload: (True, None),
    )
    manager._build_library_group_index = lambda: ([], {}, {}, {})
    first_result = {}
    thread = threading.Thread(
        target=lambda: first_result.update(
            manager.set_group_settings(
                "group-a", {"config": {"AudioLanguagePreference": "first"}}
            )
        )
    )
    thread.start()
    assert started.wait(timeout=1)

    competing = manager.update_user_settings(
        "server-a",
        "user-a",
        {"config": {"AudioLanguagePreference": "second"}},
    )
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert first_result["ok"] is True
    assert competing["ok"] is False
    assert competing["busy"] is True
    assert remote == {"user-a": "first", "user-b": "first"}


def test_direct_policy_toggles_share_one_user_read_modify_write_fence():
    remote_policy = {"EnableRemoteAccess": False, "EnableContentDownloading": False}
    update_started = threading.Event()
    release_update = threading.Event()

    def fetch(_server, _user_id):
        return {"Policy": dict(remote_policy)}, None

    def update(_server, _user_id, policy):
        update_started.set()
        assert release_update.wait(timeout=2)
        remote_policy.clear()
        remote_policy.update(policy)
        return True, None

    manager = UserOpsManager(
        get_server_by_id=lambda server_id: {"id": server_id},
        fetch_user_details=fetch,
        fetch_users_list=lambda _server: ([], None),
        update_user_policy=update,
        rename_user=lambda *_args: (True, None),
        fetch_user_last_playback=lambda *_args: None,
    )
    first_result: list[bool] = []
    thread = threading.Thread(
        target=lambda: first_result.append(
            manager.toggle_remote_access("server-a", "user-a", True)
        )
    )
    thread.start()
    assert update_started.wait(timeout=1)

    competing = manager.toggle_download_permissions("server-a", "user-a", True)
    release_update.set()
    thread.join(timeout=2)

    assert first_result == [True]
    assert competing is False
    assert remote_policy == {
        "EnableRemoteAccess": True,
        "EnableContentDownloading": False,
    }


def test_password_reads_reject_storage_only_synthetic_group_ids():
    manager = PasswordManager(
        storage=_Storage(),
        get_server_by_id=lambda server_id: {"id": server_id},
        get_group_users=lambda _group_id: [],
        get_unlinked_group_id=lambda server_id, user_id: f"unlinked_{server_id}_{user_id}",
        update_user_password=lambda *_args: (True, None),
    )

    assert manager.get_password_info(group_id="unlinked_server-a_user-a") == {
        "ok": False,
        "error": "Invalid target",
    }


def test_server_delete_fence_overlaps_every_user_mutation_key_set():
    coordinator = UserMutationCoordinator(None)
    started = threading.Event()
    release = threading.Event()

    def hold_user_mutation():
        with coordinator.guard(user_mutation_keys("server-a", "user-a")) as acquired:
            assert acquired is True
            started.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=hold_user_mutation)
    thread.start()
    assert started.wait(timeout=1)
    with coordinator.guard([server_mutation_key("server-a")]) as delete_acquired:
        assert delete_acquired is False
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
