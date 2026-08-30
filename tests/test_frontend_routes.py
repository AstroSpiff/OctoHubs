import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException


class _PreferencesRequest:
    def __init__(self, payload):
        self.headers = {"X-CSRF-Token": "csrf-token"}
        self._payload = payload

    async def json(self):
        return self._payload


class _TabOrderGetRequest:
    def __init__(self, page):
        self.query_params = {"page": page}


@pytest.mark.anyio
async def test_frontend_session_route_exposes_user_and_csrf_token():
    from web import frontend_routes

    user = SimpleNamespace(id=7, username="roy", email="roy@example.test", get_role=lambda: "admin")
    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: user,
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )

    response = await frontend_routes.frontend_session_route(SimpleNamespace())
    payload = json.loads(response.body.decode("utf-8"))

    assert payload == {
        "ok": True,
        "user": {"id": 7, "username": "roy", "email": "roy@example.test", "role": "admin"},
        "preferences": {"primary_navigation": "top", "secondary_navigation": "tabs"},
        "csrf_token": "csrf-token",
    }


@pytest.mark.anyio
async def test_frontend_preferences_are_saved_for_the_current_account(monkeypatch):
    from web import frontend_routes

    user = SimpleNamespace(id=7, username="roy")
    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: user,
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    monkeypatch.setattr(
        "core.auth.get_user_interface_preferences",
        lambda user_id: {"primary_navigation": "top", "secondary_navigation": "tabs"},
    )
    saved = {}
    monkeypatch.setattr(
        "core.auth.save_user_interface_preferences",
        lambda user_id, preferences: saved.update(user_id=user_id, preferences=preferences) or preferences,
    )

    response = await frontend_routes.frontend_preferences_route(
        _PreferencesRequest({"primary_navigation": "sidebar"}),
    )

    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == {
        "success": True,
        "preferences": {"primary_navigation": "sidebar", "secondary_navigation": "tabs"},
    }
    assert saved == {
        "user_id": 7,
        "preferences": {"primary_navigation": "sidebar", "secondary_navigation": "tabs"},
    }


@pytest.mark.anyio
async def test_frontend_tab_order_is_saved_for_the_current_account(monkeypatch):
    from web import frontend_routes

    user = SimpleNamespace(id=7, username="roy", role="viewer")
    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: user,
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    monkeypatch.setattr("web.frontend_routes._personal_tab_order", lambda user_id, page: ["probe", "operations"])

    response = await frontend_routes.frontend_tab_order_get_route(_TabOrderGetRequest("primary"))

    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == {
        "success": True,
        "order": [
            {"tab_key": "probe", "position": 0},
            {"tab_key": "operations", "position": 1},
        ],
    }

    saved = {}
    monkeypatch.setattr(
        "core.auth.save_user_interface_order",
        lambda user_id, page, order: saved.update(user_id=user_id, page=page, order=order) or order,
    )
    response = await frontend_routes.frontend_tab_order_post_route(
        _PreferencesRequest({
            "page": "primary",
            "order": [
                {"tab_key": "probe", "position": 0},
                {"tab_key": "operations", "position": 1},
            ],
        }),
    )

    assert response.status_code == 200
    assert saved == {"user_id": 7, "page": "primary", "order": ["probe", "operations"]}


@pytest.mark.anyio
async def test_frontend_tab_order_does_not_read_shared_legacy_layouts(monkeypatch):
    from web import frontend_routes

    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: SimpleNamespace(id=7, username="roy"),
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    monkeypatch.setattr("web.frontend_routes._personal_tab_order", lambda _user_id, _page: None)

    response = await frontend_routes.frontend_tab_order_get_route(_TabOrderGetRequest("research"))

    assert json.loads(response.body.decode("utf-8")) == {"success": True, "order": []}


@pytest.mark.anyio
async def test_frontend_tab_order_requires_csrf(monkeypatch):
    from web import frontend_routes

    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: SimpleNamespace(id=7, username="roy"),
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    request = _PreferencesRequest({"page": "primary", "order": []})
    request.headers = {"X-CSRF-Token": "wrong"}

    with pytest.raises(HTTPException) as raised:
        await frontend_routes.frontend_tab_order_post_route(request)

    assert raised.value.status_code == 403


def test_frontend_asset_resolution_never_leaves_dist_directory():
    from web.frontend_routes import _frontend_file

    assert _frontend_file("../../config.json") is None


@pytest.mark.anyio
async def test_frontend_route_keeps_query_string_when_redirecting_to_login():
    from web import frontend_routes

    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: None,
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )
    request = SimpleNamespace(url=SimpleNamespace(path="/app/configuration", query="focus=event-bridge-configuration"))

    response = await frontend_routes.frontend_application_route(request, "configuration")

    next_value = parse_qs(urlparse(response.headers["location"]).query)["next"]
    assert next_value == ["/app/configuration?focus=event-bridge-configuration"]
