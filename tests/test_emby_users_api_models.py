"""OpenAPI contracts and secret boundaries for Emby user read endpoints."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from emby_users.response_models import (
    UserDetailsResponse,
    UserPasswordInfoResponse,
    UserSettingsInfoResponse,
    UserSettingsSchemaResponse,
)
from emby_users.routes import (
    api_emby_users_password_get,
    init_emby_user_routes,
    router as users_router,
)


def test_user_read_routes_publish_typed_contracts():
    app = FastAPI()
    app.include_router(users_router)
    schema = app.openapi()

    assert schema["paths"]["/api/emby/users/password"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UserPasswordInfoResponse"
    assert schema["paths"]["/api/emby/users/settings-schema"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UserSettingsSchemaResponse"
    assert schema["paths"]["/api/emby/users/settings"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UserSettingsInfoResponse"
    assert schema["paths"]["/api/emby/users/{server_id}/{user_id}/details"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/UserDetailsResponse"


def test_user_read_models_accept_existing_manager_payloads():
    password = UserPasswordInfoResponse.model_validate({
        "ok": True,
        "group_id": "group-1",
        "saved": True,
        "updated_at": "2026-08-29T12:00:00+00:00",
    })
    schema = UserSettingsSchemaResponse.model_validate({
        "schema_version": "1",
        "categories": [{"key": "policy"}],
        "library_groups": [{"key": "movies"}],
    })
    settings = UserSettingsInfoResponse.model_validate({
        "ok": True,
        "saved": False,
        "server_id": "green",
        "user_id": "roy",
        "settings": {"policy": {}},
        "from_emby": True,
        "library_items": [{"id": "movies"}],
        "feature_items": [],
    })
    details = UserDetailsResponse.model_validate({
        "last_activity_date": "2026-08-29T12:00:00+00:00",
        "last_played_title": "Film",
        "has_password": True,
    })

    assert password.password is None
    assert schema.categories[0]["key"] == "policy"
    assert settings.from_emby is True
    assert details.last_played_title == "Film"


def test_read_only_bearer_password_read_never_receives_saved_value():
    calls: list[bool] = []

    class PasswordManager:
        def get_password_info(self, **kwargs):
            calls.append(kwargs["include_password"])
            return {
                "ok": True,
                "group_id": "group-1",
                "saved": True,
                "password": "must-not-leak",
                "updated_at": "2026-08-29T12:00:00+00:00",
            }

    manager = SimpleNamespace(password_manager=PasswordManager())
    init_emby_user_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(auth_method="api_token", api_token_scopes=["read:users"]),
    )

    response = asyncio.run(
        api_emby_users_password_get(
            request,
            group_id="group-1",
            user=SimpleNamespace(role="admin"),
        )
    )

    assert calls == [False]
    assert response["saved"] is True
    assert "password" not in response


def test_password_manager_omits_the_field_for_an_unsaved_bearer_target():
    from emby_users.password_manager import PasswordManager

    manager = object.__new__(PasswordManager)
    manager.storage = SimpleNamespace(get_group_password=lambda _group_id: None)

    result = manager.get_group_password_info("group-1", include_password=False)

    assert result == {"ok": True, "group_id": "group-1", "saved": False, "updated_at": None}


@pytest.mark.parametrize("role", ["user", "admin"])
def test_session_with_mutation_capability_keeps_password_management_flow(role):
    calls: list[bool] = []

    class PasswordManager:
        def get_password_info(self, **kwargs):
            calls.append(kwargs["include_password"])
            return {"ok": True, "group_id": "group-1", "saved": True, "password": "saved-value", "updated_at": None}

    manager = SimpleNamespace(password_manager=PasswordManager())
    init_emby_user_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    request = SimpleNamespace(state=SimpleNamespace(auth_method="session"))

    response = asyncio.run(
        api_emby_users_password_get(
            request,
            group_id="group-1",
            user=SimpleNamespace(role=role),
        )
    )

    assert calls == [True]
    assert response["password"] == "saved-value"


@pytest.mark.parametrize(
    "auth_state",
    [
        SimpleNamespace(auth_method="session"),
        SimpleNamespace(auth_method="api_token", api_token_scopes=["write:users"]),
    ],
)
def test_viewer_receives_password_metadata_without_saved_value(auth_state):
    calls: list[bool] = []

    class PasswordManager:
        def get_password_info(self, **kwargs):
            calls.append(kwargs["include_password"])
            return {
                "ok": True,
                "group_id": "group-1",
                "saved": True,
                "password": "must-not-leak",
                "updated_at": None,
            }

    manager = SimpleNamespace(password_manager=PasswordManager())
    init_emby_user_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    request = SimpleNamespace(state=auth_state)

    response = asyncio.run(
        api_emby_users_password_get(
            request,
            group_id="group-1",
            user=SimpleNamespace(role="viewer"),
        )
    )

    assert calls == [False]
    assert response["saved"] is True
    assert "password" not in response


@pytest.mark.parametrize("scopes", [["write:users"], ["admin:all"]])
def test_bearer_with_mutation_capability_can_read_saved_password(scopes):
    calls: list[bool] = []

    class PasswordManager:
        def get_password_info(self, **kwargs):
            calls.append(kwargs["include_password"])
            return {
                "ok": True,
                "group_id": "group-1",
                "saved": True,
                "password": "saved-value",
                "updated_at": None,
            }

    manager = SimpleNamespace(password_manager=PasswordManager())
    init_emby_user_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(auth_method="api_token", api_token_scopes=scopes),
    )

    response = asyncio.run(
        api_emby_users_password_get(
            request,
            group_id="group-1",
            user=SimpleNamespace(role="admin"),
        )
    )

    assert calls == [True]
    assert response["password"] == "saved-value"
