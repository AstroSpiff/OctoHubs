"""Group password partial-success reconciliation."""

from __future__ import annotations

from emby_users.password_manager import PasswordManager


class _Storage:
    def __init__(self):
        self.saved = {}

    def save_group_password(self, group_id, value):
        self.saved[group_id] = value

    def delete_group_password(self, group_id):
        self.saved.pop(group_id, None)


def test_group_password_persists_each_successful_remote_target_immediately():
    storage = _Storage()
    outcomes = iter(((True, None), (False, "offline")))
    manager = PasswordManager(
        storage=storage,
        get_server_by_id=lambda server_id: {"id": server_id},
        get_group_users=lambda _group_id: [
            ("server-a", "user-a", None),
            ("server-b", "user-b", None),
        ],
        get_unlinked_group_id=lambda server_id, user_id: f"{server_id}:{user_id}",
        update_user_password=lambda *_args: next(outcomes),
    )
    manager.encrypt_password = lambda _value: "encrypted-new-password"

    result = manager.set_group_password("group-1", "new-password")

    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["reconciliation_required"] is True
    assert storage.saved == {"server-a:user-a": "encrypted-new-password"}
    assert "group-1" not in storage.saved


def test_single_password_reports_partial_when_local_persistence_fails():
    class _FailingStorage(_Storage):
        def save_group_password(self, group_id, value):
            raise RuntimeError("db unavailable password=CANARY")

    manager = PasswordManager(
        storage=_FailingStorage(),
        get_server_by_id=lambda server_id: {"id": server_id},
        get_group_users=lambda _group_id: [],
        get_unlinked_group_id=lambda server_id, user_id: f"{server_id}:{user_id}",
        update_user_password=lambda *_args: (True, None),
    )
    manager.encrypt_password = lambda _value: "encrypted"

    result = manager.update_user_password("server-a", "user-a", "new-password")

    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["applied"] == 1
    assert result["reconciliation_required"] is True
