from types import SimpleNamespace
import json

import pytest
from fastapi import HTTPException
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
        if args == ("roy",):
            return user
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
    assert len(threadpool_calls) == 4
    assert threadpool_calls[0][1] == ("roy",)
    assert threadpool_calls[1] == (auth_routes.login_password_matches, (user, "password"))


@pytest.mark.anyio
async def test_login_rate_limit_returns_429_before_database_lookup(monkeypatch):
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


def test_logout_is_only_exposed_as_a_post_mutation():
    auth_routes = _init_auth_routes()
    logout_route = next(route for route in auth_routes.router.routes if route.path == "/logout")

    assert logout_route.methods == {"POST"}


@pytest.mark.anyio
async def test_logout_requires_csrf_and_preserves_the_session_on_failure(monkeypatch):
    auth_routes = _init_auth_routes(current_user=lambda _request: SimpleNamespace(id=7))
    monkeypatch.setattr(
        "core.auth.log_audit_event",
        lambda *_args: pytest.fail("invalid CSRF reached the audit log"),
    )
    request = SimpleNamespace(session={"user_id": 7}, headers={})

    with pytest.raises(HTTPException) as exc_info:
        await auth_routes.logout(request)

    assert exc_info.value.status_code == 403
    assert request.session == {"user_id": 7}


@pytest.mark.anyio
async def test_logout_clears_the_session_and_returns_the_login_destination(monkeypatch):
    user = SimpleNamespace(id=7, username="roy")
    auth_routes = _init_auth_routes(current_user=lambda _request: user)
    audit_calls = []
    monkeypatch.setattr("core.auth.log_audit_event", lambda *args: audit_calls.append(args))
    request = SimpleNamespace(
        session={"user_id": 7, "permanent": True},
        headers={"X-CSRF-Token": "csrf"},
    )

    response = await auth_routes.logout(request)

    assert response.status_code == 200
    assert json.loads(response.body) == {"success": True, "redirect": "/login"}
    assert request.session == {}
    assert audit_calls == [(user, "logout", "success", request)]
