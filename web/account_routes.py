"""Account and access-management endpoints for the OctoHubs workspace."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from web.account_api_models import (
    AccountActionResponse,
    AccountCreateRequest,
    AccountListResponse,
    AccountMutationResponse,
    AccountUpdateRequest,
    ApiTokenAuditExportResponse,
    ApiTokenAuditListResponse,
    ApiTokenCreateRequest,
    ApiTokenListResponse,
    ApiTokenSecretResponse,
    CurrentAccountResponse,
    PasswordUpdateRequest,
)
from web.openapi_requests import json_request_body, no_request_body, query_parameters
from web.request_validation import validated_json_payload


router = APIRouter()

_get_current_user_optional: Optional[Callable[[Request], Optional[Any]]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_require_auth: Optional[Callable[[Request], Any]] = None

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,80}$")
_MINIMUM_PASSWORD_LENGTH = 8


def init_account_routes(
    get_current_user_optional: Callable[[Request], Optional[Any]],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    require_auth: Callable[[Request], Any] | None = None,
) -> None:
    """Inject the session helpers owned by the FastAPI application factory."""
    global _get_current_user_optional, _validate_csrf, _require_auth
    _get_current_user_optional = get_current_user_optional
    _validate_csrf = validate_csrf
    _require_auth = require_auth


def _current_user(request: Request) -> Any:
    if _get_current_user_optional is None:
        raise RuntimeError("Account routes not initialized: current user helper missing")
    if _require_auth is not None:
        _require_auth(request)
    user = _get_current_user_optional(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    return user


def _is_admin(user: Any) -> bool:
    get_role = getattr(user, "get_role", None)
    role = get_role() if callable(get_role) else getattr(user, "role", "user")
    return str(role or "").strip().lower() == "admin"


def _require_admin(request: Request) -> Any:
    user = _current_user(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Questa azione richiede un account amministratore")
    return user


def _validate_csrf_request(request: Request) -> None:
    if getattr(getattr(request, "state", None), "auth_method", "") == "api_token":
        return
    if _validate_csrf is None:
        raise RuntimeError("Account routes not initialized: CSRF validator missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _validate_child_token_scopes(request: Request, scopes: Any) -> None:
    """Prevent a token from minting a replacement with broader permissions."""
    if getattr(getattr(request, "state", None), "auth_method", "") != "api_token":
        return
    from core.auth import normalize_api_token_scopes
    from web.session_auth import has_api_scope

    requested = normalize_api_token_scopes(scopes)
    granted = list(getattr(getattr(request, "state", None), "api_token_scopes", []) or [])
    if requested and not all(has_api_scope(granted, scope) for scope in requested):
        raise HTTPException(
            status_code=403,
            detail="Un API token puo creare solo token con permessi gia posseduti",
        )


def _role(user: Any) -> str:
    get_role = getattr(user, "get_role", None)
    value = get_role() if callable(get_role) else getattr(user, "role", "user")
    return str(value or "user")


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _account_payload(user: Any, *, include_preferences: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "")),
        "email": str(getattr(user, "email", "") or ""),
        "role": _role(user),
        "is_active": bool(getattr(user, "is_active", False)),
        "created_at": _timestamp(getattr(user, "created_at", None)),
        "last_login": _timestamp(getattr(user, "last_login", None)),
    }
    if include_preferences:
        from core.auth import get_user_interface_preferences

        payload["preferences"] = get_user_interface_preferences(payload["id"])
    return payload


def _api_token_payload(token: Any, audit_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.auth import _api_token_is_expired, api_token_permission_profile_id, normalize_api_token_scopes

    is_expired = _api_token_is_expired(token)
    is_active = bool(getattr(token, "is_active", False)) and not is_expired
    scopes = normalize_api_token_scopes(json_loads(getattr(token, "scopes", "[]")))

    return {
        "id": int(getattr(token, "id", 0) or 0),
        "name": str(getattr(token, "name", "")),
        "prefix": str(getattr(token, "token_prefix", "")),
        "scopes": scopes,
        "permission_profile": api_token_permission_profile_id(scopes),
        "is_active": is_active,
        "is_expired": is_expired,
        "status": "expired" if is_expired else "active" if is_active else "revoked",
        "created_at": _timestamp(getattr(token, "created_at", None)),
        "last_used_at": _timestamp(getattr(token, "last_used_at", None)),
        "revoked_at": _timestamp(getattr(token, "revoked_at", None)),
        "expires_at": _timestamp(getattr(token, "expires_at", None)),
        "last_action": audit_summary,
    }


def json_loads(value: Any) -> Any:
    import json

    try:
        return json.loads(value or "[]")
    except (TypeError, ValueError):
        return []


async def _payload(request: Request, model) -> dict[str, Any]:
    body = await validated_json_payload(request, model)
    return body if isinstance(body, dict) else {}


def _text(payload: dict[str, Any], key: str, *, required: bool = False) -> str | None:
    value = payload.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{key} non valido")
    normalized = value.strip()
    if required and not normalized:
        raise HTTPException(status_code=422, detail=f"{key} obbligatorio")
    return normalized


def _password(payload: dict[str, Any], key: str) -> str:
    value = _text(payload, key, required=True)
    assert value is not None
    if len(value) < _MINIMUM_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"La password deve avere almeno {_MINIMUM_PASSWORD_LENGTH} caratteri")
    return value


def _email(payload: dict[str, Any]) -> str | None:
    value = _text(payload, "email")
    if value is None:
        return None
    if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
        raise HTTPException(status_code=422, detail="Email non valida")
    return value


def _requested_role(payload: dict[str, Any]) -> str | None:
    value = _text(payload, "role")
    if value is None:
        return None
    from core.auth import ROLE_VALUES

    normalized = value.lower()
    if normalized not in ROLE_VALUES:
        raise HTTPException(status_code=422, detail="Ruolo account non valido")
    return normalized


def _requested_active(payload: dict[str, Any]) -> bool | None:
    if "is_active" not in payload:
        return None
    value = payload["is_active"]
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail="Stato account non valido")
    return value


def _target_account(account_id: int) -> Any:
    from core.auth import get_user_by_id

    account = get_user_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account OctoHubs non trovato")
    return account


def _audit_query(request: Request) -> tuple[int | None, str | None, str | None, int]:
    query = getattr(request, "query_params", {}) or {}
    raw_token_id = str(query.get("token_id") or "").strip()
    try:
        token_id = int(raw_token_id) if raw_token_id else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Filtro token non valido") from exc
    if token_id is not None and token_id <= 0:
        raise HTTPException(status_code=422, detail="Filtro token non valido")
    result = str(query.get("result") or "").strip().lower()
    if result and result not in {"allowed", "denied"}:
        raise HTTPException(status_code=422, detail="Filtro esito non valido")
    api_version = str(query.get("api_version") or "").strip().lower()
    if api_version and api_version not in {"v1", "legacy"}:
        raise HTTPException(status_code=422, detail="Filtro versione API non valido")
    try:
        limit = int(str(query.get("limit") or "100"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Limite audit non valido") from exc
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="Limite audit non valido")
    return token_id, result or None, api_version or None, limit


@router.get("/api/account/me", response_model=CurrentAccountResponse)
async def account_profile_route(request: Request):
    """Return the authenticated account and its private presentation preferences."""
    return JSONResponse({"account": _account_payload(_current_user(request), include_preferences=True)})


@router.put(
    "/api/account/me/password",
    response_model=AccountActionResponse,
    openapi_extra=json_request_body(PasswordUpdateRequest),
)
async def update_own_password_route(request: Request):
    """Change the current account password after verifying the existing password."""
    user = _current_user(request)
    _validate_csrf_request(request)
    payload = await _payload(request, PasswordUpdateRequest)
    current_password = _text(payload, "current_password", required=True)
    next_password = _password(payload, "new_password")
    assert current_password is not None
    if not callable(getattr(user, "check_password", None)) or not user.check_password(current_password):
        raise HTTPException(status_code=422, detail="Password attuale non corretta")
    if current_password == next_password:
        raise HTTPException(status_code=422, detail="La nuova password deve essere diversa da quella attuale")

    from core.auth import log_audit_event, update_user_password

    if not update_user_password(user, next_password):
        raise HTTPException(status_code=500, detail="Impossibile aggiornare la password")
    log_audit_event(user, "account_password_updated", "Password account aggiornata", request)
    return JSONResponse({"success": True, "message": "Password aggiornata"})


@router.get("/api/account/tokens", response_model=ApiTokenListResponse)
async def list_api_tokens_route(request: Request):
    """List API tokens owned by the authenticated account without exposing secrets."""
    user = _current_user(request)
    user_id = int(getattr(user, "id", 0) or 0)
    from core.auth import get_api_token_audit_summaries, list_api_token_permission_profiles, list_api_tokens

    audit_summaries = get_api_token_audit_summaries(user_id)

    return JSONResponse(
        {
            "available_permission_profiles": list_api_token_permission_profiles(
                include_administrator=_is_admin(user),
            ),
            "tokens": [
                _api_token_payload(token, audit_summaries.get(int(getattr(token, "id", 0) or 0)))
                for token in list_api_tokens(user_id)
            ],
        }
    )


@router.get(
    "/api/account/tokens/audit",
    response_model=ApiTokenAuditListResponse,
    openapi_extra=query_parameters(
        ("token_id", False, "integer"),
        ("result", False, "string"),
        ("api_version", False, "string"),
        ("limit", False, "integer"),
    ),
)
async def api_token_audit_route(request: Request):
    """List the current account's API-token activity without exposing secrets."""
    user = _current_user(request)
    token_id, result, api_version, limit = _audit_query(request)
    from core.api_token_audit import list_api_token_audit_events

    events = list_api_token_audit_events(
        int(getattr(user, "id", 0) or 0),
        token_id=token_id,
        result=result,
        api_version=api_version,
        limit=limit,
    )
    return JSONResponse(
        {
            "events": events,
            "filters": {
                "token_id": token_id,
                "result": result,
                "api_version": api_version,
                "limit": limit,
            },
        }
    )


@router.get(
    "/api/account/tokens/audit/export",
    response_model=ApiTokenAuditExportResponse,
    openapi_extra=query_parameters(
        ("token_id", False, "integer"),
        ("result", False, "string"),
        ("api_version", False, "string"),
    ),
)
async def api_token_audit_export_route(request: Request):
    """Export the current account's filtered API-token activity as safe JSON."""
    user = _current_user(request)
    token_id, result, api_version, _limit = _audit_query(request)
    from core.api_token_audit import api_token_audit_export

    return JSONResponse(
        api_token_audit_export(
            int(getattr(user, "id", 0) or 0),
            token_id=token_id,
            result=result,
            api_version=api_version,
        ),
        headers={"Content-Disposition": 'attachment; filename="octohubs-api-token-audit.json"'},
    )


@router.post(
    "/api/account/tokens",
    status_code=201,
    response_model=ApiTokenSecretResponse,
    openapi_extra=json_request_body(ApiTokenCreateRequest),
)
async def create_api_token_route(request: Request):
    """Create a one-time visible API token for external clients."""
    user = _current_user(request)
    _validate_csrf_request(request)
    payload = await _payload(request, ApiTokenCreateRequest)
    name = _text(payload, "name", required=True)
    permission_profile = _text(payload, "permission_profile", required=True)
    expires_in_days = payload.get("expires_in_days")

    from core.auth import api_token_permission_profile_scopes, create_api_token, log_audit_event

    scopes = api_token_permission_profile_scopes(permission_profile)
    if scopes is None:
        raise HTTPException(status_code=422, detail="Profilo permessi API token non valido")
    if permission_profile == "administrator" and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Il profilo amministratore richiede un account amministratore")
    _validate_child_token_scopes(request, scopes)
    result = create_api_token(user, name or "", scopes, expires_in_days=expires_in_days)
    if result is None:
        raise HTTPException(status_code=422, detail="Nome o permessi API token non validi")
    token, secret = result
    log_audit_event(user, "api_token_created", f"Creato API token {token.name}", request)
    return JSONResponse(
        {
            "success": True,
            "token": _api_token_payload(token),
            "secret": secret,
            "message": "API token creato. Copialo ora: non sara mostrato di nuovo.",
        },
        status_code=201,
    )


@router.delete(
    "/api/account/tokens/{token_id}",
    response_model=AccountActionResponse,
    openapi_extra=no_request_body(),
)
async def revoke_api_token_route(token_id: int, request: Request):
    """Revoke one API token owned by the authenticated account."""
    user = _current_user(request)
    _validate_csrf_request(request)

    from core.auth import log_audit_event, revoke_api_token

    if not revoke_api_token(int(getattr(user, "id", 0) or 0), token_id):
        raise HTTPException(status_code=404, detail="API token non trovato")
    log_audit_event(user, "api_token_revoked", f"Revocato API token {token_id}", request)
    return JSONResponse({"success": True})


@router.post(
    "/api/account/tokens/{token_id}/rotate",
    status_code=201,
    response_model=ApiTokenSecretResponse,
    openapi_extra=no_request_body(),
)
async def rotate_api_token_route(token_id: int, request: Request):
    """Create a replacement secret and immediately revoke the old token."""
    user = _current_user(request)
    _validate_csrf_request(request)
    from core.auth import log_audit_event, rotate_api_token

    result = rotate_api_token(int(getattr(user, "id", 0) or 0), token_id)
    if result is None:
        raise HTTPException(status_code=409, detail="API token non attivo o scaduto")
    token, secret = result
    log_audit_event(user, "api_token_rotated", f"Ruotato API token {token_id}", request)
    return JSONResponse(
        {
            "success": True,
            "token": _api_token_payload(token),
            "secret": secret,
            "message": "API token ruotato. Copialo ora: non sara mostrato di nuovo.",
        },
        status_code=201,
    )


@router.get("/api/admin/accounts", response_model=AccountListResponse)
async def list_accounts_route(request: Request):
    """List OctoHubs access accounts for administrators only."""
    _require_admin(request)
    from core.auth import get_all_users

    return JSONResponse({"accounts": [_account_payload(user) for user in get_all_users()]})


@router.post(
    "/api/admin/accounts",
    status_code=201,
    response_model=AccountMutationResponse,
    openapi_extra=json_request_body(AccountCreateRequest),
)
async def create_account_route(request: Request):
    """Create an access account without touching any shared OctoHubs data."""
    actor = _require_admin(request)
    _validate_csrf_request(request)
    payload = await _payload(request, AccountCreateRequest)
    username = _text(payload, "username", required=True)
    password = _password(payload, "password")
    email = _email(payload)
    role = _requested_role(payload) or "user"
    assert username is not None
    if not _USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=422, detail="Lo username deve contenere da 3 a 80 caratteri: lettere, numeri, punto, trattino o underscore")

    from core.auth import create_user, get_user_by_username, log_audit_event

    if get_user_by_username(username) is not None:
        raise HTTPException(status_code=409, detail="Username gia in uso")
    account = create_user(username, password, email=email or None, role=role)
    if account is None:
        raise HTTPException(status_code=409, detail="Impossibile creare l'account: verifica username ed email")
    log_audit_event(actor, "account_created", f"Creato account {account.username} ({account.get_role()})", request)
    return JSONResponse({"success": True, "account": _account_payload(account)}, status_code=201)


@router.patch(
    "/api/admin/accounts/{account_id}",
    response_model=AccountMutationResponse,
    openapi_extra=json_request_body(AccountUpdateRequest),
)
async def update_account_route(account_id: int, request: Request):
    """Update role, active state, contact email, or reset another account password."""
    actor = _require_admin(request)
    _validate_csrf_request(request)
    payload = await _payload(request, AccountUpdateRequest)
    account = _target_account(account_id)
    email = _email(payload)
    role = _requested_role(payload)
    is_active = _requested_active(payload)
    password = _text(payload, "password")
    if password is not None and len(password) < _MINIMUM_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"La password deve avere almeno {_MINIMUM_PASSWORD_LENGTH} caratteri")
    if not any(("email" in payload, role is not None, is_active is not None, password is not None)):
        raise HTTPException(status_code=422, detail="Nessuna modifica account richiesta")
    if int(getattr(account, "id", 0) or 0) == int(getattr(actor, "id", 0) or 0) and password is not None:
        raise HTTPException(status_code=422, detail="Usa Il mio account per modificare la tua password")

    from core.auth import log_audit_event, update_user_details, update_user_password

    if "email" in payload or role is not None or is_active is not None:
        details: dict[str, Any] = {"role": role, "is_active": is_active}
        if "email" in payload:
            details["email"] = email
        if not update_user_details(account, **details):
            raise HTTPException(status_code=409, detail="Impossibile aggiornare l'account: controlla email e amministratori attivi")
    if password is not None and not update_user_password(account, password):
        raise HTTPException(status_code=500, detail="Impossibile reimpostare la password")

    log_audit_event(actor, "account_updated", f"Aggiornato account {account.username}", request)
    return JSONResponse({"success": True, "account": _account_payload(account)})


@router.delete(
    "/api/admin/accounts/{account_id}",
    response_model=AccountActionResponse,
    openapi_extra=no_request_body(),
)
async def delete_account_route(account_id: int, request: Request):
    """Delete another access account while preserving an active administrator."""
    actor = _require_admin(request)
    _validate_csrf_request(request)
    account = _target_account(account_id)
    if int(getattr(account, "id", 0) or 0) == int(getattr(actor, "id", 0) or 0):
        raise HTTPException(status_code=422, detail="Non puoi eliminare l'account con cui sei connesso")

    from core.auth import delete_user, log_audit_event

    account_name = str(getattr(account, "username", ""))
    if not delete_user(account):
        raise HTTPException(status_code=409, detail="Impossibile eliminare l'ultimo amministratore attivo")
    log_audit_event(actor, "account_deleted", f"Eliminato account {account_name}", request)
    return JSONResponse({"success": True})
