"""Contracts for the React research overview."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_research_overview_hides_available_content_without_mutating_source(monkeypatch):
    from services import research_overview

    results = {
        "items": [
            {"request_id": 436, "title": "Available"},
            {"request_id": 451, "title": "Pending"},
        ]
    }
    overview = [
        {"id": 436, "title": "Available", "media_type": "tv", "is_available": False, "season_status": [{"season": 1, "status": "available"}]},
        {"id": 451, "title": "Pending", "media_type": "movie", "is_available": False},
    ]
    monkeypatch.setattr(research_overview, "_get_total_blacklist_counts", lambda: (2, 3))

    payload = research_overview.build_research_overview_snapshot(
        {"SEARCH_RULES": {}, "QBITTORRENT_URL": "http://qb", "QBITTORRENT_USERNAME": "user", "QBITTORRENT_PASSWORD": "secret"},
        True,
        scan_status={"last_summary": results, "running": False},
        cached_overview=(overview, "2026-08-11T12:00:00+00:00"),
    )

    assert [request["id"] for request in payload["requests"]] == [451]
    assert [request["id"] for request in payload["all_requests"]] == [436, 451]
    assert [item["request_id"] for item in payload["results"]["items"]] == [451]
    assert payload["scan"] == {"running": False}
    assert payload["probe_counts"] == {"blacklist": 2, "incomplete": 3}
    assert payload["search_defaults"] == {"target_languages": [], "exclude_tags": []}
    assert payload["qbittorrent_available"] is True
    assert [item["request_id"] for item in results["items"]] == [436, 451]
    assert "secret" not in json.dumps(payload)


def test_research_api_surface_uses_only_canonical_paths():
    from search.routes import router as search_router
    from services.requests_routes import router as request_router
    from web.research_api_routes import router as research_router

    paths = {route.path for route in [*search_router.routes, *request_router.routes, *research_router.routes]}
    assert {
        "/api/research/tmdb/search",
        "/api/research/tmdb/tv/{tv_id}",
        "/api/research/tmdb/check-availability",
        "/api/research/stream",
        "/api/research/manual",
        "/api/research/manual/history",
        "/api/research/results/cleanup",
        "/api/research/torrents/archive",
        "/api/research/torrents/proxy",
        "/api/research/torrents/send",
        "/api/research/torrents/send-batch",
        "/api/research/media/details",
        "/api/research/requests/create",
    } <= paths
    assert not paths & {
        "/api/tmdb/search",
        "/api/tmdb/tv/{tv_id}",
        "/api/tmdb/check-availability",
        "/api/search/stream",
        "/api/search/manual",
        "/api/search/manual/history",
        "/api/search/results/cleanup",
        "/api/torrent/zip",
        "/api/torrent/proxy",
        "/api/send-torrent",
        "/api/send-torrent/batch",
        "/api/media/details",
        "/api/jellyseerr/request",
    }


def test_research_routes_publish_typed_overview_tmdb_and_request_contracts():
    from fastapi import FastAPI
    from search.routes import router as search_router
    from services.requests_routes import router as request_router
    from web.research_api_routes import router as research_router

    app = FastAPI()
    app.include_router(search_router)
    app.include_router(request_router)
    app.include_router(research_router)
    paths = app.openapi()["paths"]

    def response_schema(path: str, method: str) -> dict:
        return paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema("/api/research/overview", "get")["$ref"] == "#/components/schemas/ResearchOverviewResponse"
    assert response_schema("/api/research/tmdb/search", "get")["$ref"] == "#/components/schemas/ResearchTmdbSearchResponse"
    assert response_schema("/api/research/manual", "post")["$ref"] == "#/components/schemas/ResearchManualSearchResponse"
    assert response_schema("/api/research/media/details", "get")["$ref"] == "#/components/schemas/ResearchMediaDetailsResponse"
    assert response_schema("/api/research/requests/create", "post")["$ref"] == "#/components/schemas/ResearchActionResponse"
    assert response_schema("/api/research/requests/refresh-status", "get")["$ref"] == "#/components/schemas/ResearchRefreshStatusResponse"

    refresh = paths["/api/research/requests/refresh"]["post"]
    assert {item["name"] for item in refresh["parameters"]} == {"background"}


@pytest.mark.anyio
async def test_research_overview_api_requires_auth(monkeypatch):
    from web import research_api_routes

    observed = []
    research_api_routes.init_research_api_routes(
        require_auth=lambda request: observed.append(request),
        validate_csrf=lambda request, token: True,
        load_config=lambda: ({"SEARCH_RULES": {}}, True),
    )
    monkeypatch.setattr(research_api_routes, "build_research_overview_snapshot", lambda config, valid: {"success": True, "has_config": valid, "requests": []})

    request = SimpleNamespace()
    response = await research_api_routes.research_overview_api_route(request)

    assert observed == [request]
    assert json.loads(response.body.decode("utf-8")) == {"success": True, "has_config": True, "requests": []}

    assert not hasattr(research_api_routes, "legacy_research_dashboard_api_route")


@pytest.mark.anyio
async def test_research_search_rules_api_validates_csrf_and_returns_persisted_rules(monkeypatch):
    from web import research_api_routes

    observed_tokens = []
    research_api_routes.init_research_api_routes(
        require_auth=lambda _request: None,
        validate_csrf=lambda _request, token: observed_tokens.append(token) or token == "valid",
        load_config=lambda: ({"SEARCH_RULES": {}}, True),
    )
    monkeypatch.setattr(
        research_api_routes,
        "update_search_rule_settings",
        lambda payload, _config: {"search_rules": payload["search_rules"], "target_languages": [], "exclude_tags": []},
    )

    from web.research_api_models import SearchRulesPayload

    class Request:
        headers = {"X-CSRF-Token": "valid"}

    response = await research_api_routes.update_search_rules_api_route(
        Request(),
        SearchRulesPayload(search_rules={"min_seeders": 2}),
    )

    assert observed_tokens == ["valid"]
    assert json.loads(response.body.decode("utf-8"))["search_rules"] == {"min_seeders": 2}

    class InvalidRequest(Request):
        headers = {"X-CSRF-Token": "invalid"}

    with pytest.raises(HTTPException, match="CSRF"):
        await research_api_routes.update_search_rules_api_route(
            InvalidRequest(),
            SearchRulesPayload(search_rules={"min_seeders": 2}),
        )


@pytest.mark.anyio
async def test_research_request_actions_use_canonical_routes_and_keep_csrf(monkeypatch):
    from services import research_request_actions
    from services import scheduler_manager
    from web import research_api_routes

    csrf_tokens = []
    research_api_routes.init_research_api_routes(
        require_auth=lambda _request: None,
        validate_csrf=lambda _request, token: csrf_tokens.append(token) or token == "valid",
        load_config=lambda: ({"SEARCH_RULES": {}}, True),
    )
    monkeypatch.setattr(research_request_actions, "update_request_rules", lambda payload: ({"success": True, "rules": payload["rules"]}, 200))
    monkeypatch.setattr(research_request_actions, "start_background_refresh", lambda: ({"success": True, "background": True}, 202))
    monkeypatch.setattr(research_request_actions, "get_request_refresh_status", lambda: {"running": True})
    monkeypatch.setattr(research_api_routes, "_build_run_scan_snapshot", lambda payload: ({"success": True, "targets": payload.get("targets")}, 200))

    stopped = []
    monkeypatch.setattr(scheduler_manager.scan_manager, "stop_scan", lambda: stopped.append(True))

    class Request:
        headers = {"X-CSRF-Token": "valid"}
        query_params = {"background": "1"}

    request = Request()
    from web.research_api_models import RequestRulesPayload, ScanStartPayload

    rules = await research_api_routes.update_request_rules_api_route(
        request,
        RequestRulesPayload(rules=[{"request_id": 12}]),
    )
    refresh = await research_api_routes.refresh_requests_api_route(request)
    status = await research_api_routes.refresh_requests_status_api_route(request)
    scan = await research_api_routes.start_scan_api_route(
        request,
        ScanStartPayload(targets=[{"request_id": 12}]),
    )
    stop = await research_api_routes.stop_scan_api_route(request)

    assert json.loads(rules.body.decode("utf-8")) == {"success": True, "rules": [{"request_id": 12}]}
    assert json.loads(refresh.body.decode("utf-8")) == {"success": True, "background": True}
    assert json.loads(status.body.decode("utf-8")) == {"running": True}
    assert json.loads(scan.body.decode("utf-8")) == {"success": True, "targets": [{"request_id": 12}]}
    assert json.loads(stop.body.decode("utf-8"))["success"] is True
    assert csrf_tokens == ["valid", "valid", "valid", "valid"]
    assert stopped == [True]

    from services import manager
    from services import routes as service_routes

    assert not hasattr(service_routes, "update_request_rules")
    assert not hasattr(service_routes, "refresh_requests")
    assert not hasattr(manager, "_build_update_request_rules_snapshot")
    assert not hasattr(manager, "_build_refresh_requests_snapshot")
