"""Concurrent account mutations must preserve one active administrator."""

from __future__ import annotations

import threading

import pytest


@pytest.fixture
def initialized_auth(tmp_path):
    from core import auth

    previous_session = auth.db_session
    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'admin-concurrency.db'}",
        allow_sqlite_for_tests=True,
    )
    try:
        yield auth
    finally:
        auth.shutdown_auth()
        auth.db_session = previous_session


@pytest.mark.parametrize("operation", ["demote", "delete"])
def test_concurrent_admin_mutations_cannot_remove_every_active_admin(
    initialized_auth,
    operation,
):
    auth = initialized_auth
    assert auth.create_user("admin-a", "password-a", role="admin") is not None
    assert auth.create_user("admin-b", "password-b", role="admin") is not None
    barrier = threading.Barrier(2)
    results = []

    def mutate(username):
        try:
            account = auth.get_user_by_username(username)
            assert account is not None
            barrier.wait(timeout=3)
            if operation == "demote":
                results.append(auth.update_user_details(account, role="viewer"))
            else:
                results.append(auth.delete_user(account))
        finally:
            auth.db_session.remove()

    first = threading.Thread(target=mutate, args=("admin-a",))
    second = threading.Thread(target=mutate, args=("admin-b",))
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert sorted(results) == [False, True]
    active_admins = auth.db_session.query(auth.User).filter(
        auth.User.is_active.is_(True),
        auth.User.is_admin.is_(True),
    ).count()
    assert active_admins == 1
