import json
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


def _bearer_request(secret: str, method: str, path: str, payload: dict | None = None):
    class _Request:
        headers = {
            "Authorization": f"Bearer {secret}",
            "User-Agent": "external-ai-test",
            "X-Real-IP": "203.0.113.10",
        }
        session = {}
        scope = {"path": path}
        state = SimpleNamespace()
        client = SimpleNamespace(host="172.18.0.2")

        def __init__(self):
            self.method = method
            self.url = SimpleNamespace(path=path)

        async def json(self):
            return payload or {}

    return _Request()


def _api_secret(auth_module, scopes: list[str]) -> str:
    user = auth_module.create_user("admin", "admin-password", role="admin")
    assert user is not None
    result = auth_module.create_api_token(user, "External AI", scopes)
    assert result is not None
    _token, secret = result
    return secret


@pytest.mark.anyio
async def test_api_token_can_read_system_status_without_csrf(initialized_auth, monkeypatch):
    from web import config_routes
    from web.session_auth import require_auth

    secret = _api_secret(initialized_auth, ["read:status"])
    monkeypatch.setenv("LOGIN_TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("LOGIN_TRUSTED_PROXY_CIDRS", "172.18.0.0/16")
    config_routes.init_config_routes(
        require_auth=require_auth,
    )
    monkeypatch.setattr(config_routes, "_build_system_status_snapshot", lambda *_args: {"ok": True, "sections": []})

    response = await config_routes.system_status_route(
        _bearer_request(secret, "GET", "/api/system/status")
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload == {"ok": True, "sections": []}
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs
    assert api_logs[0].username == "admin"
    assert api_logs[0].method == "GET"
    assert api_logs[0].path == "/api/system/status"
    assert api_logs[0].ip_address == "203.0.113.10"
    assert "read:status" in api_logs[0].detail
    assert secret not in api_logs[0].detail


@pytest.mark.anyio
async def test_api_token_can_read_external_realtime_changes_without_csrf(initialized_auth):
    from realtime import routes
    from realtime.external_change_feed import publish_external_change, reset_external_change_feed_for_tests
    from web.session_auth import require_auth

    secret = _api_secret(initialized_auth, ["read:status"])
    reset_external_change_feed_for_tests()
    routes.init_realtime_routes(require_auth)
    publish_external_change({"server_id": "green", "MessageType": "SessionsUpdate", "Data": {"private": "hidden"}})

    payload = await routes.external_realtime_changes_api(
        _bearer_request(secret, "GET", "/api/realtime/changes"),
        after=0,
        limit=10,
    )

    assert payload["events"][0]["topic"] == "emby.streams"
    assert payload["events"][0]["server_id"] == "green"
    assert payload["events"][0]["details"] == {}
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs
    assert api_logs[0].path == "/api/realtime/changes"
    assert "read:status" in api_logs[0].detail


@pytest.mark.anyio
async def test_v1_api_audit_keeps_the_original_external_path(initialized_auth, monkeypatch):
    from web import config_routes
    from web.session_auth import require_auth

    secret = _api_secret(initialized_auth, ["read:status"])
    config_routes.init_config_routes(require_auth=require_auth)
    monkeypatch.setattr(config_routes, "_build_system_status_snapshot", lambda *_args: {"ok": True})
    request = _bearer_request(secret, "GET", "/api/system/status")
    request.scope["octohubs_external_path"] = "/api/v1/system/status"

    await config_routes.system_status_route(request)

    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs[0].path == "/api/v1/system/status"


@pytest.mark.anyio
async def test_api_token_can_use_research_contract_without_session_csrf(initialized_auth, monkeypatch):
    from web import research_api_routes
    from web.research_api_models import SearchRulesPayload
    from web.session_auth import require_auth
    from web.ui_helpers import validate_csrf

    secret = _api_secret(initialized_auth, ["write:research"])
    research_api_routes.init_research_api_routes(
        require_auth=require_auth,
        validate_csrf=validate_csrf,
        load_config=lambda: ({"SEARCH_RULES": {}}, True),
    )
    monkeypatch.setattr(
        research_api_routes,
        "build_research_overview_snapshot",
        lambda _config, _valid: {"success": True, "requests": []},
    )
    monkeypatch.setattr(
        research_api_routes,
        "update_search_rule_settings",
        lambda payload, _config: {"search_rules": payload["search_rules"]},
    )

    overview = await research_api_routes.research_overview_api_route(
        _bearer_request(secret, "GET", "/api/research/overview"),
    )
    updated = await research_api_routes.update_search_rules_api_route(
        _bearer_request(secret, "PUT", "/api/research/search-rules"),
        SearchRulesPayload(search_rules={"min_seeders": 2}),
    )

    assert json.loads(overview.body.decode("utf-8"))["success"] is True
    assert json.loads(updated.body.decode("utf-8"))["search_rules"] == {"min_seeders": 2}
    logs = initialized_auth.get_audit_logs(10)
    assert any(log.action == "api_token_read" and log.path == "/api/research/overview" for log in logs)
    assert any(log.action == "api_token_write" and log.path == "/api/research/search-rules" for log in logs)


@pytest.mark.anyio
async def test_api_token_can_mutate_telegram_with_write_configuration_scope(initialized_auth, monkeypatch):
    from telegram import api_routes
    from web.session_auth import require_auth
    from web.ui_helpers import validate_csrf

    secret = _api_secret(initialized_auth, ["write:configuration"])
    api_routes.init_telegram_api_routes(
        require_auth=require_auth,
        validate_csrf=validate_csrf,
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )
    monkeypatch.setattr(api_routes, "_telegram_snapshot", lambda: {"success": True, "bots": []})
    monkeypatch.setattr(api_routes, "publish_configuration_update", lambda _section: None)
    monkeypatch.setattr(api_routes, "ensure_telegram_ready", lambda *_args: None)
    monkeypatch.setattr(api_routes, "run_telegram_configuration_action", lambda _action, _data: ("success", "ok"))

    response = await api_routes.telegram_action_api_route(
        _bearer_request(
            secret,
            "POST",
            "/api/telegram/action",
            {"action": "bot.save", "data": {"id": "bot-1"}},
        )
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["message"] == "ok"
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_write"]
    assert api_logs
    assert api_logs[0].path == "/api/telegram/action"
    assert "write:configuration" in api_logs[0].detail


@pytest.mark.anyio
async def test_api_token_can_read_latest_publications_with_dedicated_scope(initialized_auth, monkeypatch):
    from emby_latest import configuration_api, routes
    from web.session_auth import require_auth
    from web.ui_helpers import validate_csrf

    secret = _api_secret(initialized_auth, ["read:publications"])
    routes.init_emby_latest_routes(require_auth, validate_csrf)
    monkeypatch.setattr(
        configuration_api,
        "build_latest_configuration_snapshot",
        lambda: ({"success": True, "presets": [], "rules": []}, 200),
    )

    response = await routes.emby_latest_configuration(
        _bearer_request(secret, "GET", "/api/emby/latest/config"),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["success"] is True
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs
    assert api_logs[0].path == "/api/emby/latest/config"
    assert "read:publications" in api_logs[0].detail


@pytest.mark.anyio
async def test_api_token_can_read_collections_with_dedicated_scope(initialized_auth, monkeypatch):
    from emby_collections import routes
    from web.session_auth import require_user

    secret = _api_secret(initialized_auth, ["read:collections"])
    routes.init_emby_collections_routes(
        require_user,
        SimpleNamespace(info=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        routes,
        "list_collection_definitions",
        lambda: [{"id": "watchlist", "name": "Watchlist", "enabled": True}],
    )
    request = _bearer_request(secret, "GET", "/api/emby/collections")

    payload = await routes.api_emby_collections_list(user=require_user(request))

    assert payload == {
        "success": True,
        "collections": [{"id": "watchlist", "name": "Watchlist", "enabled": True}],
    }
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs
    assert api_logs[0].path == "/api/emby/collections"
    assert "read:collections" in api_logs[0].detail


@pytest.mark.anyio
async def test_api_token_can_read_probe_libraries_with_library_scope(initialized_auth, monkeypatch):
    from emby_runtime import routes
    from web.session_auth import require_auth
    from web.ui_helpers import validate_csrf

    secret = _api_secret(initialized_auth, ["read:libraries"])
    routes.init_emby_runtime_routes(require_auth, validate_csrf)
    monkeypatch.setattr(
        routes,
        "_build_emby_libraries_snapshot",
        lambda: ({"success": True, "servers": []}, 200),
    )

    response = await routes.emby_probe_libraries_api(
        _bearer_request(secret, "GET", "/api/emby/probe/libraries"),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload == {"success": True, "servers": []}
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_read"]
    assert api_logs
    assert api_logs[0].path == "/api/emby/probe/libraries"
    assert "read:libraries" in api_logs[0].detail


@pytest.mark.anyio
async def test_api_token_scope_blocks_unrelated_mutation(initialized_auth):
    from telegram import api_routes
    from web.session_auth import require_auth
    from web.ui_helpers import validate_csrf

    secret = _api_secret(initialized_auth, ["read:status"])
    api_routes.init_telegram_api_routes(
        require_auth=require_auth,
        validate_csrf=validate_csrf,
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )

    with pytest.raises(HTTPException) as error:
        await api_routes.telegram_action_api_route(
            _bearer_request(
                secret,
                "POST",
                "/api/telegram/action",
                {"action": "bot.save", "data": {"id": "bot-1"}},
            )
        )

    assert error.value.status_code == 403
    assert "write:configuration" in str(error.value.detail)
    api_logs = [log for log in initialized_auth.get_audit_logs(10) if log.action == "api_token_denied"]
    assert api_logs
    assert api_logs[0].path == "/api/telegram/action"
    assert "denied" in api_logs[0].detail
    assert "write:configuration" in api_logs[0].detail
