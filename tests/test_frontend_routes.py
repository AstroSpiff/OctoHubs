import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException


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
        "preferences": {"primary_navigation": "sidebar"},
    }


@pytest.mark.anyio
async def test_frontend_preferences_report_storage_outage_as_503(monkeypatch):
    from core.auth import AuthStorageError
    from web import frontend_routes

    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: SimpleNamespace(id=7, username="roy"),
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )

    def unavailable(*_args):
        raise AuthStorageError("database unavailable")

    monkeypatch.setattr("core.auth.save_user_interface_preferences", unavailable)
    with pytest.raises(HTTPException) as exc_info:
        await frontend_routes.frontend_preferences_route(
            _PreferencesRequest({"primary_navigation": "sidebar"}),
        )
    assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_frontend_preferences_use_the_documented_model_at_runtime():
    from web import frontend_routes

    frontend_routes.init_frontend_routes(
        get_current_user_optional=lambda _request: SimpleNamespace(id=7, username="roy"),
        get_csrf_token=lambda _request: "csrf-token",
        validate_csrf=lambda _request, token: token == "csrf-token",
    )

    with pytest.raises(HTTPException) as exc_info:
        await frontend_routes.frontend_preferences_route(
            _PreferencesRequest({"primary_navigation": "unsupported"}),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Modalita di navigazione non supportata"


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


def test_frontend_tab_order_keeps_tolerant_input_and_canonicalizes_positions():
    from web.frontend_routes import _parse_tab_order

    assert _parse_tab_order(
        {
            "page": "primary",
            "order": [
                {"tab_key": "probe"},
                7,
                {},
                {"tab_key": "probe", "position": 42},
                {"tab_key": "operations", "position": "ignored"},
            ],
        }
    ) == ("primary", ["probe", "operations"])


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


def test_every_private_ui_operation_has_explicit_openapi_contracts():
    from web.frontend_routes import router

    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    operations = {
        (path, method): operation
        for path, path_item in paths.items()
        if path.startswith("/api/ui/")
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations
    for (path, method), operation in operations.items():
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema.get("$ref"), (path, method, operation)
        if method in {"post", "put", "patch"}:
            assert operation.get("requestBody"), (path, method, operation)

    preferences = operations[("/api/ui/preferences", "put")]
    tab_order_get = operations[("/api/ui/tab-order", "get")]
    tab_order_post = operations[("/api/ui/tab-order", "post")]
    preferences_schema = preferences["requestBody"]["content"]["application/json"]["schema"]
    assert set(preferences_schema["properties"]) == {
        "primary_navigation",
        "secondary_navigation",
    }
    query_parameters = {item["name"]: item for item in tab_order_get["parameters"]}
    assert query_parameters["page"]["required"] is True
    assert query_parameters["page"]["schema"]["maxLength"] == 80
    tab_order_schema = tab_order_post["requestBody"]["content"]["application/json"]["schema"]
    assert set(tab_order_schema["properties"]) == {"page", "order"}


def test_every_private_ui_openapi_reference_resolves_from_document_root():
    from web.frontend_routes import router

    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    ui_paths = {
        path: path_item
        for path, path_item in document["paths"].items()
        if path.startswith("/api/ui/")
    }

    def resolve(reference):
        assert reference.startswith("#/"), reference
        current = document
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            assert part in current, reference
            current = current[part]
        return current

    visited_references = set()

    def assert_resolvable(value):
        if isinstance(value, list):
            for item in value:
                assert_resolvable(item)
            return
        if not isinstance(value, dict):
            return
        reference = value.get("$ref")
        if reference and reference not in visited_references:
            visited_references.add(reference)
            assert_resolvable(resolve(reference))
        for item in value.values():
            assert_resolvable(item)

    assert_resolvable(ui_paths)
    assert visited_references


@pytest.mark.parametrize(
    ("payload", "accepted"),
    [
        ({}, False),
        ({"unrelated": "ignored"}, False),
        ({"primary_navigation": None}, False),
        ({"primary_navigation": "top", "secondary_navigation": None}, False),
        ({"primary_navigation": "unsupported"}, False),
        ({"primary_navigation": "sidebar"}, True),
        ({"secondary_navigation": "sidebar"}, True),
        ({"primary_navigation": "top", "secondary_navigation": "tabs"}, True),
    ],
)
def test_preferences_openapi_and_runtime_accept_the_same_fixtures(payload, accepted):
    from pydantic import ValidationError

    from web.frontend_api_models import FrontendPreferencesRequest
    from web.frontend_routes import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()["paths"]["/api/ui/preferences"]["put"]["requestBody"]["content"]["application/json"]["schema"]

    alternatives = schema.get("anyOf", [])
    schema_accepts = any(
        all(field in payload for field in alternative.get("required", []))
        for alternative in alternatives
    )
    for name, value in payload.items():
        property_schema = schema.get("properties", {}).get(name)
        if property_schema and "enum" in property_schema:
            schema_accepts = schema_accepts and value in property_schema["enum"]

    try:
        FrontendPreferencesRequest.model_validate(payload)
        runtime_accepts = True
    except ValidationError:
        runtime_accepts = False

    assert schema_accepts is accepted
    assert runtime_accepts is accepted


@pytest.mark.parametrize(
    ("payload", "accepted"),
    [
        ({"page": "primary"}, False),
        ({"page": "primary", "order": []}, True),
        ({"page": "primary", "order": [{"tab_key": "probe"}]}, True),
    ],
)
def test_tab_order_openapi_and_runtime_require_the_same_top_level_fields(payload, accepted):
    from web.frontend_api_models import FrontendTabOrderRequest
    from web.frontend_routes import _parse_tab_order, router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()["paths"]["/api/ui/tab-order"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    schema_accepts = all(field in payload for field in schema["required"])

    try:
        normalized_page, normalized_order = _parse_tab_order(payload)
        FrontendTabOrderRequest.model_validate(
            {
                "page": normalized_page,
                "order": [{"tab_key": item} for item in normalized_order],
            }
        )
        runtime_accepts = True
    except (HTTPException, ValueError):
        runtime_accepts = False

    assert schema_accepts is accepted
    assert runtime_accepts is accepted


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
