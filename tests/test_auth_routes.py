from types import SimpleNamespace

import pytest
from starlette.responses import HTMLResponse


class _Templates:
    def TemplateResponse(self, _request, _name, _context, status_code=200):
        return HTMLResponse("login", status_code=status_code)


def _init_auth_routes(current_user=lambda _request: None):
    from web import auth_routes

    auth_routes.init_auth_routes(
        templates=_Templates(),
        flash=lambda _request, _message, _category: None,
        get_flash_messages=lambda _request: [],
        get_csrf_token=lambda _request: "csrf",
        validate_csrf=lambda _request, token: token == "csrf",
        set_current_user=lambda _request, _user_id: None,
        get_current_user=current_user,
    )
    return auth_routes


@pytest.mark.anyio
async def test_login_page_opens_react_workspace_for_an_active_session():
    auth_routes = _init_auth_routes(current_user=lambda _request: SimpleNamespace(id=7))

    response = await auth_routes.login_page(SimpleNamespace())

    assert response.status_code == 303
    assert response.headers["location"] == "/app/operations"


@pytest.mark.anyio
async def test_login_submit_uses_react_workspace_as_the_safe_default(monkeypatch):
    auth_routes = _init_auth_routes()
    user = SimpleNamespace(
        id=7,
        username="roy",
        is_active=True,
        check_password=lambda _password: True,
        update_last_login=lambda: None,
    )
    threadpool_calls = []

    async def _run_in_threadpool(callable_obj, *args):
        threadpool_calls.append((callable_obj, args))
        return True

    monkeypatch.setattr("core.auth.get_user_by_username", lambda _username: user)
    monkeypatch.setattr("core.auth.log_audit_event", lambda *_args: None)
    monkeypatch.setattr(auth_routes, "run_in_threadpool", _run_in_threadpool)
    request = SimpleNamespace(session={}, query_params={})

    response = await auth_routes.login_submit(
        request,
        username="roy",
        password="password",
        next_page="",
        csrf_token="csrf",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app/operations"
    assert threadpool_calls == [(auth_routes.login_password_matches, (user, "password"))]


@pytest.mark.anyio
async def test_login_rate_limit_returns_429_before_database_lookup(monkeypatch):
    from web import auth_routes
    from web.login_security import LoginRateLimitDecision

    class _BlockedLimiter:
        def consume(self, _address, _username):
            return LoginRateLimitDecision(False, 42)

    auth_routes = _init_auth_routes()
    monkeypatch.setattr(auth_routes, "get_login_attempt_limiter", lambda: _BlockedLimiter())
    monkeypatch.setattr(
        "core.auth.get_user_by_username",
        lambda _username: pytest.fail("rate-limited login reached the database"),
    )
    request = SimpleNamespace(
        session={},
        query_params={},
        headers={},
        client=SimpleNamespace(host="192.0.2.10"),
    )

    response = await auth_routes.login_submit(
        request,
        username="roy",
        password="password",
        next_page="",
        csrf_token="csrf",
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


def test_bcrypt_password_over_72_bytes_is_a_normal_authentication_failure():
    from core.auth import User

    user = User(username="roy")
    user.set_password("valid-password")

    assert user.check_password("è" * 37) is False
