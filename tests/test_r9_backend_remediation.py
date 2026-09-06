"""Regression coverage for ninth-pass backend failure paths."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from core.storage import StorageError


class _JsonRequest:
    def __init__(self, payload: dict, *, csrf: str = "csrf") -> None:
        self.headers = {"X-CSRF-Token": csrf}
        self.session = {}
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.anyio
async def test_telegram_database_error_is_generic_and_log_is_redacted(capsys):
    from telegram import api_routes

    secret = "CANARY_TELEGRAM_PASSWORD"

    def fail_database():
        raise StorageError(f"postgresql://user:{secret}@db/octohubs")

    api_routes.init_telegram_api_routes(
        require_auth=lambda _request: {"id": 1},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=fail_database,
    )

    with pytest.raises(HTTPException) as raised:
        await api_routes.telegram_action_api_route(
            _JsonRequest({"action": "bot.remove", "data": {"id": "bot-1"}})
        )

    assert raised.value.detail == "Database Telegram non disponibile."
    assert secret not in str(raised.value.detail)
    log = capsys.readouterr().out
    assert "StorageError" in log
    assert secret not in log
    assert "[REDACTED]" in log


@pytest.mark.anyio
async def test_emby_database_error_is_generic_and_log_is_redacted(capsys):
    from emby_actions import routes

    secret = "CANARY_EMBY_PASSWORD"

    def fail_database():
        raise StorageError(f"postgresql://user:{secret}@db/octohubs")

    routes.init_emby_action_routes(
        require_auth=lambda _request: {"id": 1},
        validate_csrf=lambda _request, token: token == "csrf",
        flash=lambda *_args, **_kwargs: None,
        ensure_db_backend=fail_database,
        load_config=lambda: None,
    )
    response = await routes.emby_action_api(
        _JsonRequest({"action": "refresh_libraries", "server_id": "green"})
    )
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload["message"] == "Database Emby non disponibile"
    assert secret not in response.body.decode()
    log = capsys.readouterr().out
    assert "StorageError" in log
    assert secret not in log
    assert "[REDACTED]" in log


def test_atomic_account_patch_rolls_back_every_field_on_commit_failure(tmp_path, monkeypatch):
    from core import auth

    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'atomic-account.db'}",
        allow_sqlite_for_tests=True,
    )
    try:
        assert auth.create_user("admin", "admin-password", role="admin") is not None
        account = auth.create_user(
            "operator",
            "old-password",
            email="old@example.test",
            role="user",
        )
        assert account is not None
        original_hash = account.password_hash
        session = auth.db_session()

        def fail_commit():
            raise SQLAlchemyError("forced commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(auth.AccountUpdateStorageError):
            auth.update_user_account(
                account,
                email="new@example.test",
                role="viewer",
                is_active=False,
                password="new-password",
            )
        session.rollback()
        session.expire_all()
        stored = session.get(auth.User, account.id)
        assert stored is not None
        assert stored.email == "old@example.test"
        assert stored.get_role() == "user"
        assert stored.is_active is True
        assert stored.password_hash == original_hash
    finally:
        auth.shutdown_auth()


@pytest.mark.anyio
@pytest.mark.parametrize("consume_initial", [False, True])
async def test_events_sse_releases_lease_and_subscriber_on_early_close(consume_initial):
    from realtime import connection_limits
    from realtime.routes import emby_events_stream_api, init_realtime_routes
    from realtime.subscribers import sse_subscribers

    connection_limits.reset_connection_limits()
    sse_subscribers.close_all()
    init_realtime_routes(lambda _request: SimpleNamespace(id=91))
    response = await emby_events_stream_api(SimpleNamespace())
    iterator = response.body_iterator
    if consume_initial:
        assert "Connected" in await iterator.__anext__()
    await iterator.aclose()

    assert connection_limits._COUNTS == {}
    assert sse_subscribers._subscribers == []


def test_workflow_exception_log_preserves_traceback_but_redacts_dsn(capsys):
    from services.workflows import _log_workflow_exception

    secret = "CANARY_WORKFLOW_PASSWORD"
    try:
        raise RuntimeError(f"postgresql://user:{secret}@db/octohubs")
    except RuntimeError as exc:
        _log_workflow_exception("[TEST] failure", exc)

    log = capsys.readouterr().out
    assert "Traceback (most recent call last)" in log
    assert "RuntimeError" in log
    assert secret not in log
    assert "[REDACTED]" in log
