from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
import pytest

from runtime.app_setup import create_app
from web import api_docs_routes


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _User:
    def __init__(self, role: str) -> None:
        self.role = role

    def get_role(self) -> str:
        return self.role


def _docs_request(
    monkeypatch,
    tmp_path: Path,
    user: _User | None,
    *,
    path: str,
    authorization: str = "",
) -> Request:
    swagger_html = tmp_path / "swagger.html"
    swagger_html.write_text(
        '<!doctype html><html><body><div id="swagger-ui"></div>'
        '<script type="module" src="/app/assets/swagger.js"></script></body></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(api_docs_routes, "_SWAGGER_HTML", swagger_html)
    api_docs_routes.init_api_docs_routes(lambda _request: user)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/example")
    async def example_route():
        return {"ok": True}

    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "scheme": "https",
            "server": ("octohubs.example.test", 443),
            "client": ("127.0.0.1", 50000),
            "app": app,
        }
    )


def test_application_replaces_the_insecure_fastapi_documentation_routes(monkeypatch):
    monkeypatch.setenv(
        "PASSWORD_SECRET",
        "test-only-api-docs-password-secret-0000000000000000",
    )
    app = create_app()
    route_paths = [
        getattr(candidate, "path", "")
        for route in app.routes
        for candidate in (
            getattr(getattr(route, "original_router", None), "routes", None)
            or [route]
        )
    ]

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    assert route_paths.count("/docs") == 1
    assert route_paths.count("/redoc") == 1
    assert route_paths.count("/openapi.json") == 1


@pytest.mark.anyio
async def test_docs_redirect_anonymous_browser_to_login(monkeypatch, tmp_path):
    response = await api_docs_routes.api_docs_route(
        _docs_request(monkeypatch, tmp_path, None, path="/docs")
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fdocs"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_docs_reject_non_admin_session(monkeypatch, tmp_path):
    with pytest.raises(HTTPException) as rejected:
        await api_docs_routes.api_docs_route(
            _docs_request(monkeypatch, tmp_path, _User("user"), path="/docs")
        )

    assert rejected.value.status_code == 403


@pytest.mark.anyio
async def test_docs_serve_only_local_assets_to_admin_session(monkeypatch, tmp_path):
    response = await api_docs_routes.api_docs_route(
        _docs_request(monkeypatch, tmp_path, _User("admin"), path="/docs")
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert Path(response.path).name == "swagger.html"


@pytest.mark.anyio
async def test_complete_openapi_schema_requires_admin_session(monkeypatch, tmp_path):
    with pytest.raises(HTTPException) as anonymous:
        await api_docs_routes.private_openapi_route(
            _docs_request(monkeypatch, tmp_path, None, path="/openapi.json")
        )
    with pytest.raises(HTTPException) as regular:
        await api_docs_routes.private_openapi_route(
            _docs_request(monkeypatch, tmp_path, _User("viewer"), path="/openapi.json")
        )
    admin = await api_docs_routes.private_openapi_route(
        _docs_request(monkeypatch, tmp_path, _User("admin"), path="/openapi.json")
    )

    assert anonymous.value.status_code == 401
    assert regular.value.status_code == 403
    assert admin.status_code == 200
    assert "/api/example" in json.loads(admin.body)["paths"]
    assert admin.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_complete_schema_rejects_bearer_even_for_admin_account(monkeypatch, tmp_path):
    with pytest.raises(HTTPException) as rejected:
        await api_docs_routes.private_openapi_route(
            _docs_request(
                monkeypatch,
                tmp_path,
                _User("admin"),
                path="/openapi.json",
                authorization="Bearer ohs_not-a-session",
            )
        )

    assert rejected.value.status_code == 403


def test_swagger_source_has_no_remote_asset_or_mutation_surface():
    html = (PROJECT_ROOT / "frontend/swagger.html").read_text(encoding="utf-8")
    source = (PROJECT_ROOT / "frontend/src/api-docs/swagger.ts").read_text(encoding="utf-8")

    assert "https://" not in html
    assert "http://" not in html
    assert 'url: "/openapi.json"' in source
    assert 'tagsSorter: "alpha"' in source
    assert "supportedSubmitMethods: []" in source
    assert 'validatorUrl: ""' in source
