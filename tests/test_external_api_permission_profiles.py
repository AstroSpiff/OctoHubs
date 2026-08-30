"""End-to-end acceptance coverage for the three external API token profiles."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.fixture
def initialized_auth(tmp_path, monkeypatch):
    from core import auth

    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        allow_sqlite_for_tests=True,
    )
    return auth


class _Request:
    def __init__(
        self,
        *,
        method: str,
        path: str,
        payload: dict | None = None,
        token: str | None = None,
        session: dict | None = None,
    ):
        self.method = method
        self.scope = {"path": path}
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace()
        self.session = session or {}
        self.headers = {"X-CSRF-Token": "csrf-token", "User-Agent": "profile-acceptance-test"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self._payload = payload or {}

    async def json(self):
        return self._payload


def _catalog_source() -> dict:
    """Small representative source schema, filtered by the production catalog builder."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Acceptance", "version": "test"},
        "paths": {
            "/api/system/status": {"get": {"summary": "System status"}},
            "/api/workflow/start": {"post": {"summary": "Start workflow"}},
            "/api/account/tokens": {"get": {"summary": "List tokens"}, "post": {"summary": "Create token"}},
            "/api/admin/accounts": {"get": {"summary": "List accounts"}},
        },
    }


@pytest.mark.anyio
async def test_external_api_permission_profiles_cover_the_complete_control_cycle(initialized_auth):
    """Profiles created by the UI keep the v1 external control plane least-privilege."""
    from core.auth import api_token_permission_profile_scopes, revoke_api_token, verify_api_token
    from web import account_routes
    from web.external_api_catalog import build_external_openapi
    from web.session_auth import get_current_user, require_auth

    admin = initialized_auth.create_user("admin", "admin-password", role="admin")
    assert admin is not None
    account_routes.init_account_routes(
        get_current_user_optional=get_current_user,
        validate_csrf=lambda _request, csrf: csrf == "csrf-token",
        require_auth=require_auth,
    )

    secrets: dict[str, str] = {}
    token_ids: dict[str, int] = {}
    for profile in ("read_only", "operator", "administrator"):
        response = await account_routes.create_api_token_route(
            _Request(
                method="POST",
                path="/api/account/tokens",
                payload={"name": f"Acceptance {profile}", "permission_profile": profile},
                session={"user_id": admin.id},
            )
        )
        payload = json.loads(response.body.decode("utf-8"))
        assert response.status_code == 201
        assert payload["token"]["permission_profile"] == profile
        assert payload["token"]["scopes"] == api_token_permission_profile_scopes(profile)
        secrets[profile] = payload["secret"]
        token_ids[profile] = payload["token"]["id"]

    read_only_scopes = verify_api_token(secrets["read_only"])["scopes"]
    operator_scopes = verify_api_token(secrets["operator"])["scopes"]
    administrator_scopes = verify_api_token(secrets["administrator"])["scopes"]

    read_only_catalog = build_external_openapi(_catalog_source(), read_only_scopes)
    operator_catalog = build_external_openapi(_catalog_source(), operator_scopes)
    administrator_catalog = build_external_openapi(_catalog_source(), administrator_scopes)
    assert set(read_only_catalog["paths"]) == {
        "/api/v1/system/status",
        "/api/v1/account/tokens",
    }
    assert "/api/v1/workflow/start" not in read_only_catalog["paths"]
    assert "/api/v1/workflow/start" in operator_catalog["paths"]
    assert "/api/v1/account/tokens" in operator_catalog["paths"]
    assert "post" not in operator_catalog["paths"]["/api/v1/account/tokens"]
    assert "/api/v1/admin/accounts" in administrator_catalog["paths"]

    assert require_auth(
        _Request(method="GET", path="/api/v1/system/status", token=secrets["read_only"])
    ) == admin.id
    with pytest.raises(HTTPException) as read_only_denied:
        require_auth(
            _Request(method="POST", path="/api/v1/workflow/start", token=secrets["read_only"])
        )
    assert read_only_denied.value.status_code == 403
    assert require_auth(
        _Request(method="POST", path="/api/v1/workflow/start", token=secrets["operator"])
    ) == admin.id

    created_by_administrator = await account_routes.create_api_token_route(
        _Request(
            method="POST",
            path="/api/v1/account/tokens",
            token=secrets["administrator"],
            payload={"name": "Acceptance delegated", "permission_profile": "read_only"},
        )
    )
    assert created_by_administrator.status_code == 201

    expiring_response = await account_routes.create_api_token_route(
        _Request(
            method="POST",
            path="/api/account/tokens",
            payload={
                "name": "Acceptance expiry",
                "permission_profile": "read_only",
                "expires_in_days": 1,
            },
            session={"user_id": admin.id},
        )
    )
    expiring_payload = json.loads(expiring_response.body.decode("utf-8"))
    expiring_token = next(
        token
        for token in initialized_auth.list_api_tokens(admin.id)
        if token.id == expiring_payload["token"]["id"]
    )
    expiring_token.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    initialized_auth.db_session.commit()
    with pytest.raises(HTTPException) as expired_denied:
        require_auth(
            _Request(method="GET", path="/api/v1/system/status", token=expiring_payload["secret"])
        )
    assert expired_denied.value.status_code == 401

    assert revoke_api_token(admin.id, token_ids["read_only"]) is True
    with pytest.raises(HTTPException) as revoked_denied:
        require_auth(
            _Request(method="GET", path="/api/v1/system/status", token=secrets["read_only"])
        )
    assert revoked_denied.value.status_code == 401

    audit_actions = [entry.action for entry in initialized_auth.get_audit_logs(30)]
    assert "api_token_read" in audit_actions
    assert "api_token_denied" in audit_actions
    assert "api_token_operation" in audit_actions
