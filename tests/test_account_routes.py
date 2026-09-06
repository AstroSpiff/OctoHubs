import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _Request:
    def __init__(self, payload=None):
        self.headers = {"X-CSRF-Token": "csrf-token"}
        self._payload = payload or {}
        self.state = SimpleNamespace()

    async def json(self):
        return self._payload


class _QueryRequest(_Request):
    def __init__(self, query_params=None):
        super().__init__()
        self.query_params = query_params or {}


@pytest.fixture
def initialized_auth(tmp_path, monkeypatch):
    from core import auth

    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        allow_sqlite_for_tests=True,
    )
    return auth


def _init_routes(current_user):
    from web import account_routes

    account_routes.init_account_routes(
        get_current_user_optional=lambda _request: current_user,
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    return account_routes


@pytest.mark.anyio
async def test_administrator_manages_access_accounts_without_touching_shared_data(initialized_auth):
    admin = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert admin is not None
    routes = _init_routes(admin)

    created = await routes.create_account_route(
        _Request({
            "username": "operator.one",
            "password": "operator-password",
            "email": "operator@example.test",
            "role": "user",
        })
    )
    created_payload = json.loads(created.body.decode("utf-8"))
    account_id = created_payload["account"]["id"]
    assert created.status_code == 201
    assert created_payload["account"]["role"] == "user"

    updated = await routes.update_account_route(
        account_id,
        _Request({"role": "viewer", "is_active": False}),
    )
    updated_payload = json.loads(updated.body.decode("utf-8"))
    assert updated_payload["account"]["role"] == "viewer"
    assert updated_payload["account"]["is_active"] is False

    listed = await routes.list_accounts_route(_Request())
    listed_payload = json.loads(listed.body.decode("utf-8"))
    assert {account["username"] for account in listed_payload["accounts"]} == {"admin", "operator.one"}


@pytest.mark.anyio
async def test_last_active_administrator_cannot_be_demoted_or_disabled(initialized_auth):
    admin = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert admin is not None
    routes = _init_routes(admin)

    with pytest.raises(HTTPException) as error:
        await routes.update_account_route(admin.id, _Request({"is_active": False}))

    assert error.value.status_code == 409
    assert initialized_auth.get_user_by_id(admin.id).is_active is True

    with pytest.raises(HTTPException) as role_error:
        await routes.update_account_route(admin.id, _Request({"role": "viewer"}))

    assert role_error.value.status_code == 409
    assert initialized_auth.get_user_by_id(admin.id).get_role() == "admin"


@pytest.mark.anyio
async def test_account_update_database_failure_is_not_reported_as_a_conflict(
    initialized_auth,
    monkeypatch,
):
    admin = initialized_auth.create_user("admin", "admin-password", role="admin")
    account = initialized_auth.create_user("operator", "operator-password", role="user")
    assert admin is not None and account is not None
    routes = _init_routes(admin)

    def fail_update(*_args, **_kwargs):
        raise initialized_auth.AccountUpdateStorageError("database unavailable")

    monkeypatch.setattr(initialized_auth, "update_user_account", fail_update)

    with pytest.raises(HTTPException) as error:
        await routes.update_account_route(account.id, _Request({"role": "viewer"}))

    assert error.value.status_code == 503
    assert "Database" in str(error.value.detail)


@pytest.mark.anyio
async def test_account_password_change_requires_the_existing_password(initialized_auth):
    user = initialized_auth.create_user("viewer", "existing-password", role="viewer")
    assert user is not None
    routes = _init_routes(user)

    with pytest.raises(HTTPException) as error:
        await routes.update_own_password_route(
            _Request({"current_password": "wrong-password", "new_password": "new-password"})
        )

    assert error.value.status_code == 422

    response = await routes.update_own_password_route(
        _Request({"current_password": "existing-password", "new_password": "new-password"})
    )
    assert response.status_code == 200
    assert initialized_auth.get_user_by_id(user.id).check_password("new-password") is True


@pytest.mark.anyio
async def test_account_password_routes_reject_values_over_72_utf8_bytes(initialized_auth):
    admin = initialized_auth.create_user("admin", "admin-password", role="admin")
    other = initialized_auth.create_user("other", "other-password", role="user")
    assert admin is not None and other is not None
    routes = _init_routes(admin)
    over_limit = "è" * 36 + "a"

    with pytest.raises(HTTPException) as create_error:
        await routes.create_account_route(
            _Request({"username": "new-user", "password": over_limit, "role": "user"})
        )
    assert create_error.value.status_code == 422
    assert initialized_auth.get_user_by_username("new-user") is None

    with pytest.raises(HTTPException) as reset_error:
        await routes.update_account_route(other.id, _Request({"password": over_limit}))
    assert reset_error.value.status_code == 422
    assert initialized_auth.get_user_by_id(other.id).check_password("other-password") is True

    routes = _init_routes(other)
    with pytest.raises(HTTPException) as own_error:
        await routes.update_own_password_route(
            _Request({"current_password": "other-password", "new_password": over_limit})
        )
    assert own_error.value.status_code == 422
    assert initialized_auth.get_user_by_id(other.id).check_password("other-password") is True


@pytest.mark.anyio
async def test_non_admin_cannot_list_access_accounts(initialized_auth):
    user = initialized_auth.create_user("operator", "operator-password", role="user")
    assert user is not None
    routes = _init_routes(user)

    with pytest.raises(HTTPException) as error:
        await routes.list_accounts_route(_Request())

    assert error.value.status_code == 403


@pytest.mark.anyio
async def test_user_can_create_list_and_revoke_api_tokens(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert user is not None
    routes = _init_routes(user)

    created = await routes.create_api_token_route(
        _Request({"name": "External AI", "permission_profile": "operator"})
    )
    created_payload = json.loads(created.body.decode("utf-8"))

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert created_payload["secret"].startswith("ohs_")
    assert created_payload["token"]["name"] == "External AI"
    assert created_payload["token"]["permission_profile"] == "operator"
    assert "read:status" in created_payload["token"]["scopes"]
    assert "write:event_bridge" in created_payload["token"]["scopes"]
    token_model = initialized_auth.list_api_tokens(user.id)[0]
    initialized_auth.log_api_token_usage(
        user,
        token_model,
        ["read:status"],
        "read:status",
        SimpleNamespace(
            method="GET",
            headers={},
            url=SimpleNamespace(path="/api/system/status"),
        ),
        allowed=True,
    )

    listed = await routes.list_api_tokens_route(_Request())
    listed_payload = json.loads(listed.body.decode("utf-8"))
    assert listed_payload["tokens"][0]["prefix"] == created_payload["token"]["prefix"]
    assert listed_payload["tokens"][0]["last_action"]["action"] == "api_token_read"
    assert listed_payload["tokens"][0]["last_action"]["path"] == "/api/system/status"
    assert [profile["id"] for profile in listed_payload["available_permission_profiles"]] == [
        "read_only",
        "operator",
        "administrator",
    ]

    revoked = await routes.revoke_api_token_route(created_payload["token"]["id"], _Request())
    assert revoked.status_code == 200
    assert initialized_auth.verify_api_token(created_payload["secret"]) is None


@pytest.mark.anyio
async def test_api_token_rotation_keeps_expiry_and_invalidates_the_previous_secret(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert user is not None
    routes = _init_routes(user)

    created = await routes.create_api_token_route(
        _Request({"name": "External AI", "permission_profile": "read_only", "expires_in_days": 30})
    )
    created_payload = json.loads(created.body.decode("utf-8"))
    assert created_payload["token"]["expires_at"] is not None
    previous_token_id = created_payload["token"]["id"]
    previous_secret = created_payload["secret"]

    rotated = await routes.rotate_api_token_route(previous_token_id, _Request())
    rotated_payload = json.loads(rotated.body.decode("utf-8"))
    assert rotated.status_code == 201
    assert rotated.headers["cache-control"] == "no-store"
    assert rotated_payload["secret"].startswith("ohs_")
    assert rotated_payload["secret"] != previous_secret
    assert rotated_payload["token"]["expires_at"] == created_payload["token"]["expires_at"]
    assert initialized_auth.verify_api_token(previous_secret) is None
    assert initialized_auth.verify_api_token(rotated_payload["secret"]) is not None

    replacement = initialized_auth.list_api_tokens(user.id)[0]
    replacement.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    initialized_auth.db_session.commit()
    assert initialized_auth.verify_api_token(rotated_payload["secret"]) is None

    with pytest.raises(HTTPException) as error:
        await routes.rotate_api_token_route(replacement.id, _Request())
    assert error.value.status_code == 409


def test_api_token_active_cap_and_revoked_history_are_bounded(initialized_auth):
    user = initialized_auth.create_user("token-owner", "token-owner-password", role="user")
    assert user is not None

    active = [
        initialized_auth.create_api_token(user, f"Token {index}", ["read:status"])
        for index in range(initialized_auth.API_TOKEN_MAX_ACTIVE_PER_ACCOUNT)
    ]
    assert all(result is not None for result in active)
    assert initialized_auth.create_api_token(user, "Too many", ["read:status"]) is None

    for result in active:
        assert result is not None
        assert initialized_auth.revoke_api_token(user.id, result[0].id) is True
    for index in range(initialized_auth.API_TOKEN_MAX_HISTORY_PER_ACCOUNT + 5):
        result = initialized_auth.create_api_token(
            user,
            f"Rotated {index}",
            ["read:status"],
        )
        assert result is not None
        assert initialized_auth.revoke_api_token(user.id, result[0].id) is True

    rows = initialized_auth.db_session.query(initialized_auth.ApiToken).filter_by(
        user_id=user.id
    ).all()
    assert len(rows) == initialized_auth.API_TOKEN_MAX_HISTORY_PER_ACCOUNT
    assert len(initialized_auth.list_api_tokens(user.id)) <= initialized_auth.API_TOKEN_MAX_LISTED_PER_ACCOUNT


@pytest.mark.anyio
async def test_api_token_audit_is_owned_filtered_exportable_and_never_contains_the_secret(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    other_user = initialized_auth.create_user("other", "other-password", role="user")
    assert user is not None and other_user is not None
    routes = _init_routes(user)
    created = await routes.create_api_token_route(
        _Request({"name": "External AI", "permission_profile": "read_only"})
    )
    created_payload = json.loads(created.body.decode("utf-8"))
    token = initialized_auth.list_api_tokens(user.id)[0]
    initialized_auth.log_api_token_usage(
        user,
        token,
        ["read:status"],
        "read:status",
        SimpleNamespace(method="GET", headers={}, url=SimpleNamespace(path="/api/v1/system/status")),
        allowed=True,
    )
    initialized_auth.log_api_token_usage(
        user,
        token,
        ["read:status"],
        "write:configuration",
        SimpleNamespace(method="POST", headers={}, url=SimpleNamespace(path="/api/telegram/action")),
        allowed=False,
    )
    other_token_result = initialized_auth.create_api_token(other_user, "Other token", ["read:status"])
    assert other_token_result is not None
    other_token, other_secret = other_token_result
    initialized_auth.log_api_token_usage(
        other_user,
        other_token,
        ["read:status"],
        "read:status",
        SimpleNamespace(method="GET", headers={}, url=SimpleNamespace(path="/api/system/status")),
        allowed=True,
    )

    response = await routes.api_token_audit_route(_QueryRequest({"result": "denied"}))
    payload = json.loads(response.body.decode("utf-8"))
    assert len(payload["events"]) == 1
    assert payload["events"][0]["result"] == "denied"
    assert payload["events"][0]["token_id"] == token.id
    assert created_payload["secret"] not in json.dumps(payload)
    assert other_secret not in json.dumps(payload)

    versioned = await routes.api_token_audit_route(_QueryRequest({"api_version": "v1"}))
    versioned_payload = json.loads(versioned.body.decode("utf-8"))
    assert len(versioned_payload["events"]) == 1
    assert versioned_payload["events"][0]["api_version"] == "v1"
    assert versioned_payload["filters"]["api_version"] == "v1"

    exported = await routes.api_token_audit_export_route(_QueryRequest({"token_id": str(token.id)}))
    export_payload = json.loads(exported.body.decode("utf-8"))
    assert len(export_payload["events"]) == 2
    assert exported.headers["content-disposition"].endswith('"octohubs-api-token-audit.json"')

    with pytest.raises(HTTPException) as error:
        await routes.api_token_audit_route(_QueryRequest({"result": "unexpected"}))
    assert error.value.status_code == 422

    with pytest.raises(HTTPException) as error:
        await routes.api_token_audit_route(_QueryRequest({"api_version": "v2"}))
    assert error.value.status_code == 422


@pytest.mark.anyio
async def test_api_token_cannot_create_another_api_token(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert user is not None
    routes = _init_routes(user)
    request = _Request({"name": "Nested token", "permission_profile": "read_only"})
    request.state.auth_method = "api_token"

    with pytest.raises(HTTPException) as error:
        await routes.create_api_token_route(request)

    assert error.value.status_code == 403


@pytest.mark.anyio
async def test_non_administrator_cannot_create_or_see_administrator_token_profile(initialized_auth):
    user = initialized_auth.create_user("operator", "operator-password", role="user")
    assert user is not None
    routes = _init_routes(user)

    listed = await routes.list_api_tokens_route(_Request())
    listed_payload = json.loads(listed.body.decode("utf-8"))
    assert [profile["id"] for profile in listed_payload["available_permission_profiles"]] == [
        "read_only",
        "operator",
    ]

    with pytest.raises(HTTPException) as error:
        await routes.create_api_token_route(
            _Request({"name": "Too broad", "permission_profile": "administrator"}),
        )
    assert error.value.status_code == 403


@pytest.mark.anyio
async def test_api_token_without_account_scope_cannot_enter_account_area(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert user is not None
    token_result = initialized_auth.create_api_token(user, "External AI", ["read:status"])
    assert token_result is not None
    _token, secret = token_result

    from web import account_routes
    from web.session_auth import get_current_user_optional, require_auth
    from web.ui_helpers import validate_csrf

    account_routes.init_account_routes(get_current_user_optional, validate_csrf, require_auth)
    request = SimpleNamespace(
        headers={"Authorization": f"Bearer {secret}"},
        session={},
        scope={"path": "/api/account/me"},
        method="GET",
        url=SimpleNamespace(path="/api/account/me"),
        state=SimpleNamespace(),
    )

    with pytest.raises(HTTPException) as error:
        await account_routes.account_profile_route(request)

    assert error.value.status_code == 403


def test_account_dependency_reuses_authenticated_user_without_second_authentication(
    monkeypatch,
):
    from core import auth
    from web import account_routes
    from web import api_token_rate_limit
    from web.session_auth import get_current_user_optional, require_auth

    calls = {"verify": 0, "preauth": 0, "postauth": 0}
    user = SimpleNamespace(id=7, is_active=True, role="admin")

    def verify(_secret):
        calls["verify"] += 1
        return {
            "user": user,
            "token": SimpleNamespace(id=3),
            "scopes": ["read:account"],
        }

    def preauth(_address):
        calls["preauth"] += 1
        return True, 0

    def postauth(_token_id):
        calls["postauth"] += 1
        return True, 0

    monkeypatch.setattr(auth, "verify_api_token", verify)
    monkeypatch.setattr(auth, "log_api_token_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_token_rate_limit.api_token_pre_auth_rate_limiter, "consume", preauth)
    monkeypatch.setattr(api_token_rate_limit.api_token_rate_limiter, "consume", postauth)
    account_routes.init_account_routes(
        get_current_user_optional,
        lambda *_args: True,
        require_auth,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(),
        session={},
        method="GET",
        scope={"type": "http", "path": "/api/account/me", "query_string": b""},
        headers={"Authorization": "Bearer secret"},
        client=SimpleNamespace(host="192.0.2.10"),
    )

    assert account_routes._account_auth_dependency(request) == 7
    assert account_routes._current_user(request) is user
    assert calls == {"verify": 1, "preauth": 1, "postauth": 1}


@pytest.mark.anyio
async def test_account_scope_allows_profile_and_token_management_cannot_escalate(initialized_auth):
    user = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert user is not None
    routes = _init_routes(user)

    profile_request = _Request()
    profile_request.state.auth_method = "api_token"
    profile_request.state.api_token_scopes = ["read:account"]
    profile = await routes.account_profile_route(profile_request)
    assert json.loads(profile.body.decode("utf-8"))["account"]["username"] == "admin"

    denied_request = _Request({"name": "Too broad", "permission_profile": "read_only"})
    denied_request.state.auth_method = "api_token"
    denied_request.state.api_token_scopes = ["manage:tokens", "read:status"]
    with pytest.raises(HTTPException) as error:
        await routes.create_api_token_route(denied_request)
    assert error.value.status_code == 403

    allowed_request = _Request({"name": "Read-only child", "permission_profile": "read_only"})
    allowed_request.state.auth_method = "api_token"
    allowed_request.state.api_token_scopes = ["admin:all"]
    created = await routes.create_api_token_route(allowed_request)
    assert created.status_code == 201
