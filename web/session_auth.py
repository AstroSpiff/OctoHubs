"""Session-based authentication helpers for FastAPI routes."""

from __future__ import annotations

from typing import Optional, Any, Mapping
from urllib.parse import parse_qs

from fastapi import HTTPException, Request


_SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_READ_ONLY_ROLE = "viewer"


def _request_path(request: Request) -> str:
    scope = getattr(request, "scope", {}) or {}
    if isinstance(scope, dict) and scope.get("path"):
        return str(scope.get("path") or "")
    return str(getattr(getattr(request, "url", None), "path", "") or "")


def _request_query_values(request: Request) -> dict[str, list[str]]:
    scope = getattr(request, "scope", {}) or {}
    raw_query: bytes | str = b""
    if isinstance(scope, dict):
        raw_query = scope.get("query_string") or b""
    if isinstance(raw_query, bytes):
        query = raw_query.decode("utf-8", errors="ignore")
    else:
        query = str(raw_query or "")
    if not query:
        query = str(getattr(getattr(request, "url", None), "query", "") or "")
    return parse_qs(query, keep_blank_values=True)


def _truthy_query_param(request: Request, name: str) -> bool:
    values = _request_query_values(request).get(name, [])
    return any(str(value).strip().lower() in {"1", "true", "yes", "on"} for value in values)


def _bearer_token(request: Request) -> str:
    headers = getattr(request, "headers", {}) or {}
    authorization = str(headers.get("Authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return token.strip()


def bearer_credentials_present(request: Request) -> bool:
    """Return whether the caller explicitly selected Bearer authentication."""
    headers = getattr(request, "headers", {}) or {}
    authorization = str(headers.get("Authorization") or "").strip()
    scheme, _, _token = authorization.partition(" ")
    return scheme.lower() == "bearer"


def _mark_api_token_auth(request: Request, result: dict[str, Any]) -> None:
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(state, "auth_method", "api_token")
    setattr(state, "api_token_scopes", list(result.get("scopes") or []))
    setattr(state, "api_token_id", int(getattr(result.get("token"), "id", 0) or 0))


def _api_token_result(request: Request) -> dict[str, Any] | None:
    state = getattr(request, "state", None)
    if state is not None and bool(getattr(state, "api_token_checked", False)):
        cached = getattr(state, "api_token_result", None)
        return cached if isinstance(cached, dict) else None
    token = _bearer_token(request)
    if not token:
        if state is not None:
            setattr(state, "api_token_checked", True)
            setattr(state, "api_token_result", None)
        return None
    from core.client_address import resolve_client_address
    from web.api_token_rate_limit import api_token_pre_auth_rate_limiter

    client_address = resolve_client_address(
        request,
        trust_proxy_env="API_TOKEN_TRUST_PROXY_HEADERS",
    )
    # A real ASGI peer always has an address. Keep direct internal/test calls
    # from sharing one artificial global bucket named ``unknown``.
    if client_address != "unknown":
        allowed, retry_after = api_token_pre_auth_rate_limiter.consume(client_address)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Troppi tentativi di autenticazione API token",
                headers={"Retry-After": str(retry_after)},
            )
    from core.auth import AuthStorageError, verify_api_token

    try:
        result = verify_api_token(token)
    except AuthStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database autenticazione temporaneamente non disponibile",
        ) from exc
    if state is not None:
        setattr(state, "api_token_checked", True)
        setattr(state, "api_token_result", result)
    if result is not None:
        from web.api_token_rate_limit import api_token_rate_limiter

        token_id = int(getattr(result.get("token"), "id", 0) or 0)
        allowed, retry_after = api_token_rate_limiter.consume(token_id)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Limite richieste API token superato",
                headers={"Retry-After": str(retry_after)},
            )
        _mark_api_token_auth(request, result)
    return result


def authenticate_bearer_request(request: Request) -> bool:
    """Authenticate an explicit Bearer header without falling back to cookies."""
    if not bearer_credentials_present(request):
        return False
    if _api_token_result(request) is None:
        raise HTTPException(status_code=401, detail="API token non valido")
    return True


def required_api_scope(
    method: str,
    path: str,
    query_values: Mapping[str, list[str]] | None = None,
) -> str:
    """Resolve the least-privilege API scope for one canonical HTTP operation."""
    method = str(method or "").upper()
    is_safe = method in _SAFE_HTTP_METHODS
    path = str(path or "")
    # The v1 gateway normally rewrites the ASGI scope before this function is
    # reached. Normalizing here also keeps direct dependency use deterministic.
    from web.api_versioning import canonical_v1_external_api_path

    path = canonical_v1_external_api_path(path) or path

    if path == "/api/account/me":
        return "read:account"
    if path == "/api/account/me/password":
        return "write:account"
    if path.startswith("/api/account/tokens/audit"):
        return "read:account"
    if path == "/api/account/tokens":
        return "read:account" if is_safe else "manage:tokens"
    if path.startswith("/api/account/tokens/"):
        return "manage:tokens"
    if path.startswith("/api/admin/accounts"):
        return "admin:accounts"
    if path.startswith("/api/ui/"):
        return "read:account" if is_safe else "write:account"
    if path == "/api/external/openapi.json":
        return "read:status"
    if path.startswith("/api/realtime/"):
        return "read:status"
    if path.startswith("/api/event-bridge/"):
        return "read:event_bridge" if is_safe else "write:event_bridge"
    if path.startswith("/api/system/status"):
        values = query_values or {}
        live_check = any(
            str(value).strip().lower() in {"1", "true", "yes", "on"}
            for value in values.get("check_services", [])
        )
        return "run:operations" if live_check else "read:status"
    if path in {
        "/api/research/overview",
        "/api/research/requests/refresh-status",
        "/api/research/tmdb/check-availability",
    }:
        return "read:research"
    if path in {
        "/api/research/torrents/proxy",
        "/api/research/torrents/archive",
        "/api/research/torrents/magnets",
    }:
        return "write:research"
    if (
        path.startswith("/api/research/tmdb/")
        or path.startswith("/api/research/media/details")
        or path.startswith("/api/research/manual/history")
    ):
        return "read:research" if is_safe else "write:research"
    if path in {
        "/api/research/search-rules",
        "/api/research/request-rules",
        "/api/research/results/cleanup",
    }:
        return "read:research" if is_safe else "write:research"
    if path in {
        "/api/research/stream",
        "/api/research/manual",
        "/api/research/requests/refresh",
        "/api/research/requests/create",
        "/api/research/scan/start",
        "/api/research/scan/stop",
        "/api/research/torrents/send",
        "/api/research/torrents/send-batch",
    }:
        return "run:operations"
    if path == "/api/emby/actions/targets":
        return "read:libraries"
    if path.startswith("/api/emby/actions"):
        return "read:servers" if is_safe else "run:operations"
    if path.startswith("/api/emby/stop-task"):
        return "run:operations"
    if (
        path.startswith("/api/emby/scan-library")
        or path.startswith("/api/emby/scan-group")
    ):
        return "run:operations"
    if path == "/api/emby/scan-jobs/reset":
        return "run:operations"
    if (
        path.startswith("/api/emby/active-library-scans")
        or path.startswith("/api/emby/active-scan-jobs")
        or path.startswith("/api/emby/active-scans")
        or path.startswith("/api/emby/grouped-libraries")
        or path.startswith("/api/emby/scan-job")
        or path.startswith("/api/emby/scan-jobs")
        or path.startswith("/api/emby/associations")
        or path.startswith("/api/emby/group-order")
        or path.startswith("/api/emby/server-order")
        or path.startswith("/api/emby/availability")
        or path.startswith("/api/emby/debug-vf-query")
        or path.startswith("/api/emby/movie-versions")
        or path.startswith("/api/emby/series-seasons")
        or path.startswith("/api/emby/season-episodes")
        or path.startswith("/api/emby/lookup")
        or path.startswith("/api/emby/item-details")
        or path.startswith("/api/emby/image")
        or path == "/api/emby/probe/libraries"
        or path.startswith("/api/scan-status")
    ):
        if path.startswith("/api/emby/availability"):
            return "read:libraries"
        return "read:libraries" if is_safe else "write:libraries"
    if path.startswith("/api/emby/servers"):
        return "read:servers" if is_safe else "write:configuration"
    if path.startswith("/api/emby/server-status"):
        return "read:streams" if is_safe else "run:operations"
    if path.startswith("/api/emby/status"):
        return "read:streams"
    if path.startswith("/api/emby/streams"):
        return "read:streams"
    if path.startswith("/api/emby/users/check"):
        return "read:users"
    if path.startswith("/api/emby/users/operations"):
        return "read:users" if is_safe else "run:operations"
    if (
        path.startswith("/api/emby/users/group/sync-now")
        or path.startswith("/api/emby/users/settings-apply")
        or path.startswith("/api/emby/users/create")
        or path.startswith("/api/emby/users/clone")
    ):
        return "run:operations"
    if path.startswith("/api/emby/users") or path.startswith("/api/emby/icons"):
        return "read:users" if is_safe else "write:users"
    if path.startswith("/api/emby/collections"):
        if path.endswith("/sync") or path == "/api/emby/collections/sync-all":
            return "run:operations"
        if path in {
            "/api/emby/collections/trakt-lists",
            "/api/emby/collections/mdblist-lists",
        } and not is_safe:
            return "run:operations"
        return "read:collections" if is_safe else "write:collections"
    if path == "/api/emby/latest/preview":
        return "read:publications"
    if path == "/api/emby/latest/refresh" or path == "/api/emby/latest/notify":
        return "run:operations"
    if path == "/api/emby/latest" or path.startswith("/api/emby/latest/"):
        return "read:publications" if is_safe else "write:publications"
    if path.startswith("/api/emby/probe/"):
        if (
            path.startswith("/api/emby/probe/queue")
            or path.startswith("/api/emby/probe/history")
            or path.startswith("/api/emby/probe/blacklist")
        ):
            return "read:libraries" if is_safe else "write:libraries"
        if path.startswith("/api/emby/probe/config"):
            return "read:libraries" if is_safe else "write:libraries"
        if path.startswith("/api/emby/probe/debug-recent-items"):
            return "run:operations"
        if path.startswith("/api/emby/probe/export-csv"):
            return "read:libraries"
        return "run:operations"
    if path.startswith("/api/emby/transcode-guard/check-now"):
        return "run:operations"
    if path.startswith("/api/emby/transcode-guard/"):
        return "read:streams" if is_safe else "write:transcode_guard"
    if path.startswith("/api/operations"):
        return "read:status" if is_safe else "run:operations"
    if (
        path.startswith("/api/workflow/")
        or path.startswith("/api/emby/active-")
    ):
        return "read:status" if is_safe else "run:operations"
    if path.startswith("/api/test-connections"):
        return "read:configuration" if is_safe else "run:operations"
    if path.startswith("/api/trakt/"):
        return "read:configuration" if is_safe else "write:configuration"
    if path.startswith("/api/configuration/") or path.startswith("/api/telegram/"):
        return "read:configuration" if is_safe else "write:configuration"
    return "admin:all"


def _required_api_scope(request: Request) -> str:
    """Compatibility wrapper for request-bound authentication dependencies."""
    return required_api_scope(
        str(getattr(request, "method", "") or ""),
        _request_path(request),
        _request_query_values(request),
    )


def has_api_scope(scopes: list[str], required_scope: str) -> bool:
    """Return whether a scope set authorizes a canonical API operation."""
    scope_set = {str(scope or "").strip().lower() for scope in scopes}
    if "admin:all" in scope_set or required_scope in scope_set:
        return True
    if required_scope == "read:event_bridge" and "write:event_bridge" in scope_set:
        return True
    if required_scope == "read:account" and ({"write:account", "manage:tokens"} & scope_set):
        return True
    if required_scope == "read:configuration" and "write:configuration" in scope_set:
        return True
    if required_scope == "read:servers" and "write:configuration" in scope_set:
        return True
    if required_scope == "read:users" and "write:users" in scope_set:
        return True
    if required_scope == "read:collections" and "write:collections" in scope_set:
        return True
    if required_scope == "read:libraries" and "write:libraries" in scope_set:
        return True
    if required_scope == "read:research" and "write:research" in scope_set:
        return True
    if required_scope == "read:publications" and "write:publications" in scope_set:
        return True
    return False


def _has_api_scope(scopes: list[str], required_scope: str) -> bool:
    """Keep the private helper stable for existing internal callers."""
    return has_api_scope(scopes, required_scope)


def _require_api_scope(request: Request, result: dict[str, Any]) -> None:
    required_scope = _required_api_scope(request)
    if not _has_api_scope(list(result.get("scopes") or []), required_scope):
        from core.auth import log_api_token_usage

        log_api_token_usage(
            result.get("user"),
            result.get("token"),
            list(result.get("scopes") or []),
            required_scope,
            request,
            allowed=False,
        )
        raise HTTPException(
            status_code=403,
            detail=f"API token senza permesso richiesto: {required_scope}",
        )
    state = getattr(request, "state", None)
    if state is not None:
        setattr(state, "api_token_required_scope", required_scope)


def _log_allowed_api_token_usage(request: Request, result: dict[str, Any]) -> None:
    state = getattr(request, "state", None)
    if state is not None and getattr(state, "api_token_usage_logged", False):
        return
    required_scope = (
        str(getattr(state, "api_token_required_scope", "") or "")
        if state is not None
        else ""
    ) or _required_api_scope(request)
    from core.auth import log_api_token_usage

    log_api_token_usage(
        result.get("user"),
        result.get("token"),
        list(result.get("scopes") or []),
        required_scope,
        request,
        allowed=True,
    )
    if state is not None:
        setattr(state, "api_token_usage_logged", True)


def get_current_user_id(request: Request) -> Optional[int]:
    """
    Get current authenticated user ID from Starlette session.
    Returns user_id if authenticated, None otherwise.
    """
    return request.session.get("user_id")


def set_current_user(request: Request, user_id: int) -> None:
    """Set current user ID in Starlette session."""
    request.session["user_id"] = user_id
    state = getattr(request, "state", None)
    if state is not None and hasattr(state, "authenticated_user"):
        delattr(state, "authenticated_user")


def clear_current_user(request: Request) -> None:
    """Clear current user from Starlette session (logout)."""
    request.session.pop("user_id", None)
    request.session.pop("auth_epoch", None)
    state = getattr(request, "state", None)
    if state is not None and hasattr(state, "authenticated_user"):
        delattr(state, "authenticated_user")


def _active_bearer_user(request: Request, state: Any) -> Optional[Any]:
    token_result = _api_token_result(request)
    if token_result is None:
        raise HTTPException(status_code=401, detail="API token non valido")
    user = token_result.get("user")
    if not user or not bool(getattr(user, "is_active", False)):
        return None
    _require_api_scope(request, token_result)
    _require_write_access(request, user)
    _log_allowed_api_token_usage(request, token_result)
    if state is not None:
        setattr(state, "authenticated_user", user)
    return user


def _active_session_user(request: Request, state: Any) -> Optional[Any]:
    from core.auth import AuthStorageError, get_user_by_id

    user_id = get_current_user_id(request)
    if not user_id:
        return None
    try:
        user = get_user_by_id(user_id)
    except AuthStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database autenticazione temporaneamente non disponibile",
        ) from exc
    if not user or not bool(getattr(user, "is_active", False)):
        return None
    session_epoch = int(request.session.get("auth_epoch") or 0)
    if session_epoch != int(getattr(user, "auth_epoch", 0) or 0):
        clear_current_user(request)
        return None
    if state is not None:
        setattr(state, "authenticated_user", user)
    return user


def get_current_user(request: Request) -> Optional[Any]:
    """
    Get current authenticated User object from session.
    Returns User object if authenticated, None otherwise.
    """
    state = getattr(request, "state", None)
    cached_user = getattr(state, "authenticated_user", None)
    if cached_user is not None:
        return cached_user

    if bearer_credentials_present(request):
        return _active_bearer_user(request, state)
    return _active_session_user(request, state)


def _user_role(user: Any) -> str:
    """Return the normalized role from the current user model or a test double."""
    get_role = getattr(user, "get_role", None)
    role = get_role() if callable(get_role) else getattr(user, "role", "user")
    return str(role or "user").strip().lower() or "user"


def has_mutation_capability(request: Request, user: Any, required_scope: str) -> bool:
    """Return whether the caller may access data reserved for resource editors."""
    if _user_role(user) == _READ_ONLY_ROLE:
        return False
    state = getattr(request, "state", None)
    if getattr(state, "auth_method", None) != "api_token":
        return True
    scopes = list(getattr(state, "api_token_scopes", []) or [])
    return has_api_scope(scopes, required_scope)


def _require_write_access(request: Request, user: Any) -> None:
    """Keep viewer sessions read-only for mutation routes and interactive sockets."""
    method = str(getattr(request, "method", "")).upper()
    scope = getattr(request, "scope", {}) or {}
    scope_type = str(scope.get("type", "")) if isinstance(scope, dict) else ""
    path = str(scope.get("path", "")) if isinstance(scope, dict) else ""
    is_interactive_socket = scope_type == "websocket" and path.startswith(
        ("/ws/search/", "/ws/scan/")
    )
    is_http_mutation = bool(method and method not in _SAFE_HTTP_METHODS)
    required_scope = _required_api_scope(request)
    privileged_safe_request = bool(path) and method in _SAFE_HTTP_METHODS and required_scope.startswith(
        ("run:", "write:", "manage:", "admin:")
    )
    if (is_http_mutation or is_interactive_socket or privileged_safe_request) and _user_role(user) == _READ_ONLY_ROLE:
        raise HTTPException(
            status_code=403,
            detail="Questo account e in sola lettura e non puo modificare dati.",
        )


def require_auth(request: Request) -> int:
    """
    FastAPI dependency to require authentication.
    Raises 401 if the session is missing, stale, or belongs to an inactive user.
    Raises 403 when a viewer attempts an HTTP mutation.
    Returns user_id if authenticated.
    """
    if bearer_credentials_present(request):
        token_result = _api_token_result(request)
        if token_result is None:
            raise HTTPException(status_code=401, detail="API token non valido")
        user = token_result.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        _require_api_scope(request, token_result)
        _require_write_access(request, user)
        _log_allowed_api_token_usage(request, token_result)
        state = getattr(request, "state", None)
        if state is not None:
            setattr(state, "authenticated_user", user)
        return int(user.id)

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    _require_write_access(request, user)
    return int(user.id)


def _revalidate_bearer_subject(request: Request, expected_id: int, bearer: str) -> bool:
    from core.auth import AuthStorageError, verify_api_token
    try:
        result = verify_api_token(bearer)
    except AuthStorageError:
        return False
    user = result.get("user") if result else None
    token = result.get("token") if result else None
    expected_token_id = int(getattr(getattr(request, "state", None), "api_token_id", 0) or 0)
    if not (
        user
        and token
        and bool(getattr(user, "is_active", False))
        and int(getattr(user, "id", 0) or 0) == expected_id
        and int(getattr(token, "id", 0) or 0) == expected_token_id
    ):
        return False
    assert result is not None
    try:
        if _request_path(request):
            _require_api_scope(request, result)
        _require_write_access(request, user)
    except HTTPException:
        return False
    return True


def _revalidate_session_subject(request: Request, expected_id: int) -> bool:
    from core.auth import AuthStorageError, get_user_by_id
    session = getattr(request, "session", {}) or {}
    try:
        session_user_id = int(session.get("user_id") or 0)
        session_epoch = int(session.get("auth_epoch") or 0)
    except (TypeError, ValueError):
        return False
    if session_user_id != expected_id:
        return False
    try:
        user = get_user_by_id(session_user_id)
    except AuthStorageError:
        return False
    identity_is_current = bool(
        user
        and bool(getattr(user, "is_active", False))
        and int(getattr(user, "auth_epoch", 0) or 0) == session_epoch
    )
    if not identity_is_current:
        return False
    try:
        _require_write_access(request, user)
    except HTTPException:
        return False
    return True


def revalidate_authenticated_subject(request: Request, expected_user_id: int) -> bool:
    """Revalidate a long-lived channel against current account/token state."""
    try:
        expected_id = int(expected_user_id)
    except (TypeError, ValueError):
        return False
    bearer = _bearer_token(request)
    if bearer:
        return _revalidate_bearer_subject(request, expected_id, bearer)
    return _revalidate_session_subject(request, expected_id)


def get_current_user_optional(request: Request) -> Optional[Any]:
    """Dependency: Get current user or None."""
    return get_current_user(request)


def require_user(request: Request) -> Any:
    """Dependency: require an active user, enforcing viewer read-only access."""
    token_result = _api_token_result(request)
    if token_result is not None:
        user = token_result.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        _require_api_scope(request, token_result)
        _require_write_access(request, user)
        _log_allowed_api_token_usage(request, token_result)
        return user

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    _require_write_access(request, user)
    return user
