from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from web.session_auth import get_current_user_optional, require_auth, require_user, required_api_scope


def _request_with_user(user_id: int, method: str = "GET"):
    return SimpleNamespace(session={"user_id": user_id}, method=method, scope={}, headers={}, state=SimpleNamespace())


def _request_with_bearer(secret: str, method: str, path: str):
    path_only, _, query = path.partition("?")
    return SimpleNamespace(
        session={},
        method=method,
        scope={"path": path_only, "query_string": query.encode()},
        headers={"Authorization": f"Bearer {secret}"},
        state=SimpleNamespace(),
    )


def test_require_auth_accepts_an_active_user(monkeypatch):
    monkeypatch.setattr(
        "core.auth.get_user_by_id",
        lambda user_id: SimpleNamespace(id=user_id, is_active=True),
    )

    assert require_auth(_request_with_user(7)) == 7


@pytest.mark.parametrize("user", [None, SimpleNamespace(id=7, is_active=False)])
def test_require_auth_rejects_deleted_or_inactive_users(monkeypatch, user):
    monkeypatch.setattr("core.auth.get_user_by_id", lambda _user_id: user)

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_user(7))

    assert error.value.status_code == 401


@pytest.mark.parametrize("dependency", [require_auth, require_user])
def test_viewer_can_read_but_cannot_mutate(monkeypatch, dependency):
    viewer = SimpleNamespace(id=7, is_active=True, role="viewer")
    monkeypatch.setattr("core.auth.get_user_by_id", lambda _user_id: viewer)

    assert dependency(_request_with_user(7, "GET"))

    with pytest.raises(HTTPException) as error:
        dependency(_request_with_user(7, "POST"))

    assert error.value.status_code == 403
    assert "sola lettura" in str(error.value.detail)


def test_regular_user_can_mutate(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="user")
    monkeypatch.setattr("core.auth.get_user_by_id", lambda _user_id: user)

    assert require_auth(_request_with_user(7, "PATCH")) == 7


def test_viewer_cannot_start_an_interactive_search_socket(monkeypatch):
    viewer = SimpleNamespace(id=7, is_active=True, role="viewer")
    monkeypatch.setattr("core.auth.get_user_by_id", lambda _user_id: viewer)
    request = _request_with_user(7, "")
    request.scope = {"type": "websocket", "path": "/ws/search/session-1"}

    with pytest.raises(HTTPException) as error:
        require_auth(request)

    assert error.value.status_code == 403


def test_require_auth_accepts_api_token_with_required_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["write:event_bridge"]}
        if token == "secret"
        else None,
    )
    request = _request_with_bearer("secret", "PUT", "/api/event-bridge/settings")

    assert require_auth(request) == 7
    assert request.state.auth_method == "api_token"
    assert request.state.api_token_scopes == ["write:event_bridge"]


def test_required_api_scope_normalizes_public_v1_path():
    assert required_api_scope("GET", "/api/v1/research/overview") == "read:research"
    assert required_api_scope("POST", "/api/v1/telegram/action") == "write:configuration"
    assert required_api_scope("GET", "/api/v1/emby/users/list") == "read:users"
    assert required_api_scope("POST", "/api/v1/emby/users/toggle-remote") == "write:users"
    assert required_api_scope("POST", "/api/v1/emby/users/clone") == "run:operations"
    assert required_api_scope("GET", "/api/v1/emby/icons/config") == "read:users"
    assert required_api_scope("GET", "/api/v1/account/me") == "read:account"
    assert required_api_scope("GET", "/api/ui/session") == "read:account"
    assert required_api_scope("PUT", "/api/ui/preferences") == "write:account"


def test_optional_user_dependency_enforces_scope_for_ui_bearer_tokens(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {
            "user": user,
            "token": SimpleNamespace(id=3),
            "scopes": ["read:status"],
        },
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as error:
        get_current_user_optional(
            _request_with_bearer("secret", "PUT", "/api/ui/preferences")
        )

    assert error.value.status_code == 403
    assert "write:account" in str(error.value.detail)


def test_api_token_usage_is_audited_once_per_request(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:event_bridge"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))
    request = _request_with_bearer("secret", "PUT", "/api/event-bridge/settings")

    assert require_auth(request) == 7
    assert require_auth(request) == 7

    assert len(entries) == 1
    args, kwargs = entries[0]
    assert args[:4] == (user, token, ["write:event_bridge"], "write:event_bridge")
    assert kwargs == {"allowed": True}


def test_require_auth_rejects_api_token_without_required_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:status"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "PUT", "/api/event-bridge/settings"))

    assert error.value.status_code == 403
    assert "write:event_bridge" in str(error.value.detail)
    assert len(entries) == 1
    args, kwargs = entries[0]
    assert args[:4] == (user, token, ["read:status"], "write:event_bridge")
    assert kwargs == {"allowed": False}


def test_read_status_api_token_does_not_read_server_inventory(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["read:status"]},
    )

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "GET", "/api/emby/servers"))

    assert error.value.status_code == 403
    assert "read:servers" in str(error.value.detail)


def test_server_status_api_token_requires_stream_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:servers"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "GET", "/api/emby/server-status/green"))

    assert error.value.status_code == 403
    assert "read:streams" in str(error.value.detail)
    assert len(entries) == 1
    args, kwargs = entries[0]
    assert args[:4] == (user, token, ["read:servers"], "read:streams")
    assert kwargs == {"allowed": False}


def test_server_status_api_token_accepts_stream_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:streams"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", "/api/emby/server-status/green")) == 7
    assert len(entries) == 1
    args, kwargs = entries[0]
    assert args[:4] == (user, token, ["read:streams"], "read:streams")
    assert kwargs == {"allowed": True}


@pytest.mark.parametrize("path", ["/api/emby/status", "/api/emby/status-stream"])
def test_emby_live_snapshot_api_token_requires_stream_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:status"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "GET", path))

    assert error.value.status_code == 403
    assert "read:streams" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:status"], "read:streams")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize("path", ["/api/emby/status", "/api/emby/status-stream"])
def test_emby_live_snapshot_api_token_accepts_stream_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:streams"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:streams"], "read:streams")
    assert entries[0][1] == {"allowed": True}


def test_emby_action_targets_api_token_accepts_library_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: None)

    assert require_auth(_request_with_bearer("secret", "GET", "/api/emby/actions/targets")) == 7


def test_library_api_token_requires_library_read_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:status"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "GET", "/api/emby/grouped-libraries"))

    assert error.value.status_code == 403
    assert "read:libraries" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:status"], "read:libraries")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/emby/grouped-libraries"),
        ("GET", "/api/emby/actions/targets"),
        ("GET", "/api/emby/active-library-scans"),
        ("GET", "/api/emby/active-scan-jobs"),
        ("GET", "/api/emby/active-scans"),
        ("GET", "/api/emby/scan-jobs"),
        ("GET", "/api/emby/scan-jobs/history"),
        ("GET", "/api/emby/scan-job/test-job"),
        ("GET", "/api/emby/associations"),
        ("GET", "/api/emby/group-order"),
        ("GET", "/api/emby/debug-vf-query"),
        ("GET", "/api/emby/movie-versions"),
        ("GET", "/api/emby/series-seasons"),
        ("GET", "/api/emby/season-episodes"),
        ("GET", "/api/emby/lookup"),
        ("GET", "/api/emby/item-details"),
        ("GET", "/api/emby/image"),
        ("POST", "/api/emby/availability"),
        ("GET", "/api/emby/probe/libraries"),
        ("GET", "/api/scan-status"),
    ],
)
def test_library_api_token_accepts_library_read_scope(monkeypatch, method, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:libraries"], "read:libraries")
    assert entries[0][1] == {"allowed": True}


def test_library_write_scope_can_read_library_data(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["write:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: None)

    assert require_auth(_request_with_bearer("secret", "GET", "/api/emby/grouped-libraries")) == 7


def test_library_mutation_api_token_requires_library_write_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/associations"))

    assert error.value.status_code == 403
    assert "write:libraries" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:libraries"], "write:libraries")
    assert entries[0][1] == {"allowed": False}


def test_library_history_reset_api_token_requires_library_write_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/scan-jobs/reset"))

    assert error.value.status_code == 403
    assert "write:libraries" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:libraries"], "write:libraries")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/probe/config",
        "/api/emby/probe/queue",
        "/api/emby/probe/history",
        "/api/emby/probe/blacklist",
        "/api/emby/probe/export-csv",
        "/api/emby/probe/debug-recent-items",
    ],
)
def test_probe_read_api_tokens_accept_library_read_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:libraries"], "read:libraries")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/probe/config",
        "/api/emby/probe/queue",
        "/api/emby/probe/history",
        "/api/emby/probe/blacklist",
    ],
)
def test_probe_local_mutation_api_tokens_require_library_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "DELETE" if path != "/api/emby/probe/config" else "POST", path))

    assert error.value.status_code == 403
    assert "write:libraries" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:libraries"], "write:libraries")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/probe/discovery/start",
        "/api/emby/probe/discovery/stop",
        "/api/emby/probe/recent/start",
        "/api/emby/probe/recent/start-all",
        "/api/emby/probe/recent/processing/start",
        "/api/emby/probe/recent/combo/start",
        "/api/emby/probe/libraries/combo/start",
        "/api/emby/probe/processing/start",
        "/api/emby/probe/retry",
    ],
)
def test_probe_worker_api_tokens_require_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", path))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:libraries"], "run:operations")
    assert entries[0][1] == {"allowed": False}


def test_probe_worker_api_tokens_accept_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", "/api/emby/probe/libraries/combo/start")) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/collections",
        "/api/emby/collections/options",
        "/api/emby/collections/collection-1/poster",
        "/api/emby/collections/collection-1/backdrop",
        "/api/emby/collections/collection-1/sync-details",
        "/api/emby/collections/trakt-lists",
        "/api/emby/collections/mdblist-lists",
        "/api/emby/collections/source-inventory",
    ],
)
def test_collection_read_api_tokens_accept_collection_read_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:collections"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:collections"], "read:collections")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/collections",
        "/api/emby/collections/collection-1/toggle",
        "/api/emby/collections/collection-1/delete",
        "/api/emby/collections/collection-1/poster",
        "/api/emby/collections/collection-1/poster/delete",
        "/api/emby/collections/collection-1/backdrop",
        "/api/emby/collections/collection-1/backdrop/delete",
        "/api/emby/collections/source-inventory",
        "/api/emby/collections/source-inventory/source-1/delete",
    ],
)
def test_collection_mutation_api_tokens_accept_collection_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:collections"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", path)) == 7
    assert entries[0][0][:4] == (user, token, ["write:collections"], "write:collections")
    assert entries[0][1] == {"allowed": True}


def test_collection_mutation_api_tokens_require_collection_write_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:collections"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/collections/collection-1/sync"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:collections"], "run:operations")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/emby/collections/collection-1/sync"),
        ("POST", "/api/emby/collections/sync-all"),
        ("GET", "/api/emby/collections/trakt-lists?background=1"),
        ("GET", "/api/emby/collections/mdblist-lists?background=true"),
    ],
)
def test_collection_operational_api_tokens_require_run_operations(monkeypatch, method, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


def test_collection_write_scope_does_not_start_sync_without_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:collections"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "GET", "/api/emby/collections/trakt-lists?background=1"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:collections"], "run:operations")
    assert entries[0][1] == {"allowed": False}


def test_library_scan_api_token_requires_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:libraries"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/scan-group-tracked"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:libraries"], "run:operations")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/emby/users/list"),
        ("GET", "/api/emby/users/operations"),
        ("GET", "/api/emby/users/password"),
        ("GET", "/api/emby/users/settings-schema"),
        ("GET", "/api/emby/users/settings-presets"),
        ("GET", "/api/emby/users/settings-presets/default"),
        ("GET", "/api/emby/users/settings"),
        ("GET", "/api/emby/users/green/user-1/details"),
        ("POST", "/api/emby/users/check"),
        ("GET", "/api/emby/icons/config"),
        ("GET", "/api/emby/icons/image/profile/green"),
    ],
)
def test_user_read_api_tokens_accept_user_read_scope(monkeypatch, method, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:users"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:users"], "read:users")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/users/toggle-remote",
        "/api/emby/users/toggle-download",
        "/api/emby/users/link",
        "/api/emby/users/unlink",
        "/api/emby/users/group/rename",
        "/api/emby/users/rename",
        "/api/emby/users/password",
        "/api/emby/users/password-group",
        "/api/emby/users/settings-presets",
        "/api/emby/users/settings-presets/default/duplicate",
        "/api/emby/users/settings-presets/default/delete",
        "/api/emby/users/settings",
        "/api/emby/users/settings-group",
        "/api/emby/users/group/settings",
        "/api/emby/users/delete",
        "/api/emby/users/group/delete-users",
        "/api/emby/icons/profile",
        "/api/emby/icons/binding",
        "/api/emby/icons/rule",
    ],
)
def test_user_write_api_tokens_accept_user_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:users"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", path)) == 7
    assert entries[0][0][:4] == (user, token, ["write:users"], "write:users")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/users/operations/clear-completed",
        "/api/emby/users/group/sync-now",
        "/api/emby/users/settings-apply",
        "/api/emby/users/create",
        "/api/emby/users/clone",
    ],
)
def test_user_operational_api_tokens_require_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:users"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", path))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:users"], "run:operations")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "path",
    [
        "/api/emby/users/operations/clear-completed",
        "/api/emby/users/group/sync-now",
        "/api/emby/users/settings-apply",
        "/api/emby/users/create",
        "/api/emby/users/clone",
    ],
)
def test_user_operational_api_tokens_accept_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", path)) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize("path", ["/api/emby/actions", "/api/emby/stop-task"])
def test_emby_operational_api_tokens_require_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:servers"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", path))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:servers"], "run:operations")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize("path", ["/api/emby/actions", "/api/emby/stop-task"])
def test_emby_operational_api_tokens_accept_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", path)) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


def test_operations_snapshot_api_token_accepts_read_status(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:status"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", "/api/operations")) == 7
    assert entries[0][0][:4] == (user, token, ["read:status"], "read:status")
    assert entries[0][1] == {"allowed": True}


def test_operations_mutation_api_token_requires_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:status"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/operations/clear-completed"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:status"], "run:operations")
    assert entries[0][1] == {"allowed": False}


def test_operations_mutation_api_token_accepts_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", "/api/operations/clear-completed")) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/research/overview"),
        ("GET", "/api/research/requests/refresh-status"),
        ("GET", "/api/research/tmdb/search"),
        ("GET", "/api/research/tmdb/tv/123"),
        ("POST", "/api/research/tmdb/check-availability"),
        ("GET", "/api/research/media/details"),
        ("GET", "/api/research/manual/history"),
        ("GET", "/api/research/torrents/proxy"),
        ("POST", "/api/research/torrents/proxy"),
        ("POST", "/api/research/torrents/archive"),
    ],
)
def test_research_read_api_tokens_accept_research_read_scope(monkeypatch, method, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:research"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:research"], "read:research")
    assert entries[0][1] == {"allowed": True}


def test_research_write_scope_can_read_research_data(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["write:research"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: None)

    assert require_auth(_request_with_bearer("secret", "GET", "/api/research/overview")) == 7


@pytest.mark.parametrize(
    "method,path,scope",
    [
        ("GET", "/api/emby/latest", "read:publications"),
        ("GET", "/api/emby/latest/config", "read:publications"),
        ("POST", "/api/emby/latest/preview", "read:publications"),
        ("POST", "/api/emby/latest/presets", "write:publications"),
        ("POST", "/api/emby/latest/refresh", "run:operations"),
        ("POST", "/api/emby/latest/notify", "run:operations"),
    ],
)
def test_publications_api_tokens_use_dedicated_scopes(monkeypatch, method, path, scope):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": [scope]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, [scope], scope)
    assert entries[0][1] == {"allowed": True}


def test_publications_write_scope_can_read_publications(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["write:publications"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: None)

    assert require_auth(_request_with_bearer("secret", "GET", "/api/emby/latest/config")) == 7


def test_publications_read_scope_cannot_start_latest_refresh(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:publications"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/latest/refresh"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:publications"], "run:operations")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "path",
    [
        "/api/research/search-rules",
        "/api/research/request-rules",
        "/api/research/results/cleanup",
        "/api/research/manual/history/12",
    ],
)
def test_research_mutation_api_tokens_require_research_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:research"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "DELETE" if "history/" in path else "POST", path))

    assert error.value.status_code == 403
    assert "write:research" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:research"], "write:research")
    assert entries[0][1] == {"allowed": False}


@pytest.mark.parametrize(
    "path",
    [
        "/api/research/stream",
        "/api/research/manual",
        "/api/research/requests/refresh",
        "/api/research/requests/create",
        "/api/research/scan/start",
        "/api/research/scan/stop",
        "/api/research/torrents/send",
        "/api/research/torrents/send-batch",
    ],
)
def test_research_operational_api_tokens_require_run_operations(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:research"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", path))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:research"], "run:operations")
    assert entries[0][1] == {"allowed": False}


def test_research_operational_api_tokens_accept_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", "/api/research/stream")) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/configuration/settings"),
        ("POST", "/api/test-connections"),
    ],
)
def test_configuration_read_api_tokens_accept_configuration_read_scope(monkeypatch, method, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:configuration"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", method, path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:configuration"], "read:configuration")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize(
    "path",
    [
        "/api/configuration/automations",
        "/api/configuration/services",
        "/api/telegram/action",
        "/api/trakt/device/start",
        "/api/trakt/device/poll",
        "/api/trakt/clear",
    ],
)
def test_configuration_mutation_api_tokens_require_configuration_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:configuration"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", path))

    assert error.value.status_code == 403
    assert "write:configuration" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["read:configuration"], "write:configuration")
    assert entries[0][1] == {"allowed": False}


def test_configuration_write_scope_can_read_configuration_data(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["write:configuration"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: None)

    assert require_auth(_request_with_bearer("secret", "GET", "/api/configuration/settings")) == 7


@pytest.mark.parametrize(
    "path",
    [
        "/api/configuration/automations",
        "/api/configuration/services",
        "/api/telegram/action",
        "/api/trakt/device/start",
        "/api/trakt/device/poll",
        "/api/trakt/clear",
    ],
)
def test_configuration_mutation_api_tokens_accept_configuration_write_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:configuration"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", path)) == 7
    assert entries[0][0][:4] == (user, token, ["write:configuration"], "write:configuration")
    assert entries[0][1] == {"allowed": True}


@pytest.mark.parametrize("path", ["/api/emby/transcode-guard/status", "/api/emby/transcode-guard/stats", "/api/emby/transcode-guard/streams/stream-1"])
def test_transcode_guard_read_api_token_accepts_stream_scope(monkeypatch, path):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["read:streams"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "GET", path)) == 7
    assert entries[0][0][:4] == (user, token, ["read:streams"], "read:streams")
    assert entries[0][1] == {"allowed": True}


def test_transcode_guard_settings_mutation_api_token_accepts_write_scope(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:transcode_guard"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", "/api/emby/transcode-guard/settings")) == 7
    assert entries[0][0][:4] == (user, token, ["write:transcode_guard"], "write:transcode_guard")
    assert entries[0][1] == {"allowed": True}


def test_transcode_guard_manual_check_api_token_requires_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["write:transcode_guard"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    with pytest.raises(HTTPException) as error:
        require_auth(_request_with_bearer("secret", "POST", "/api/emby/transcode-guard/check-now"))

    assert error.value.status_code == 403
    assert "run:operations" in str(error.value.detail)
    assert entries[0][0][:4] == (user, token, ["write:transcode_guard"], "run:operations")
    assert entries[0][1] == {"allowed": False}


def test_transcode_guard_manual_check_api_token_accepts_run_operations(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    token = SimpleNamespace(id=3, name="External AI", token_prefix="ohs_visible")
    entries = []
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": token, "scopes": ["run:operations"]},
    )
    monkeypatch.setattr("core.auth.log_api_token_usage", lambda *args, **kwargs: entries.append((args, kwargs)))

    assert require_auth(_request_with_bearer("secret", "POST", "/api/emby/transcode-guard/check-now")) == 7
    assert entries[0][0][:4] == (user, token, ["run:operations"], "run:operations")
    assert entries[0][1] == {"allowed": True}


def test_admin_api_token_can_reach_unclassified_api_paths(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True, role="admin")
    monkeypatch.setattr(
        "core.auth.verify_api_token",
        lambda _token: {"user": user, "token": SimpleNamespace(id=3), "scopes": ["admin:all"]},
    )

    assert require_auth(_request_with_bearer("secret", "GET", "/api/unclassified")) == 7
