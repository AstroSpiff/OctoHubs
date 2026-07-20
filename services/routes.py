"""FastAPI routes for service configuration and integrations."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import read_raw_config, _merge_database_settings, _merge_trakt_settings, _merge_justwatch_settings
from core.storage import DatabaseStorage, StorageError
from core.utils import _coerce_request_int

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[[Request, str, str], None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[[], Any]] = None


def init_service_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[[Request, str, str], None],
    resolve_next_url: Callable[[Optional[str], str], str],
    ensure_db_backend: Callable[[], Any],
    load_config: Callable[[], Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Service routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Service routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(request: Request, message: str, category: str = "message") -> None:
    if _flash is None:
        raise RuntimeError("Service routes not initialized: flash missing")
    _flash(request, message, category)


def _resolve_next_url_dep(next_url: Optional[str], fallback_endpoint: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Service routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_url, fallback_endpoint)


def _ensure_db_backend_dep() -> None:
    if _ensure_db_backend is None:
        raise RuntimeError("Service routes not initialized: ensure_db_backend missing")
    _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Service routes not initialized: load_config missing")
    return _load_config()


def _build_trakt_settings_payload(
    existing_trakt: Any,
    *,
    client_id: str,
    client_secret: str,
    access_token: str,
    enabled: str,
) -> dict[str, Any]:
    existing = existing_trakt if isinstance(existing_trakt, dict) else {}
    payload: dict[str, Any] = {
        "CLIENT_ID": client_id or existing.get("CLIENT_ID") or "",
        "CLIENT_SECRET": client_secret or existing.get("CLIENT_SECRET") or "",
    }

    for token_key in ("REFRESH_TOKEN", "EXPIRES_AT", "ACCESS_TOKEN"):
        if existing.get(token_key):
            payload[token_key] = existing[token_key]

    if access_token:
        payload["ACCESS_TOKEN"] = access_token

    if payload.get("REFRESH_TOKEN") and payload.get("ACCESS_TOKEN"):
        payload["ENABLED"] = True
    else:
        payload["ENABLED"] = bool(enabled)

    return payload


@router.post("/test-connections")
async def test_connections(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_test_connections_snapshot

    payload, status_code = _build_test_connections_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/test-connections")
async def test_connections_api(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_test_connections_snapshot

    payload, status_code = _build_test_connections_snapshot()
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/update-request-rules")
async def update_request_rules(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    from services.manager import _build_update_request_rules_snapshot

    data, status_code = _build_update_request_rules_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/refresh-requests")
async def refresh_requests(request: Request):
    _require_auth_dep(request)
    if str(request.query_params.get("background") or "").lower() in {"1", "true", "yes"}:
        from services.manager import _build_refresh_requests_background_snapshot

        data, status_code = _build_refresh_requests_background_snapshot()
        return JSONResponse(data, status_code=status_code)

    from services.manager import _build_refresh_requests_snapshot

    data, status_code = await run_in_threadpool(_build_refresh_requests_snapshot)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/refresh-requests/status")
async def refresh_requests_status(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_refresh_requests_status_snapshot

    data = _build_refresh_requests_status_snapshot()
    return JSONResponse(data, status_code=200)


@router.post("/trakt/device/start")
async def trakt_device_start(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    from services.manager import _build_trakt_device_start_snapshot

    data, status_code = _build_trakt_device_start_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/trakt/device/start")
async def trakt_device_start_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    from services.manager import _build_trakt_device_start_snapshot

    data, status_code = _build_trakt_device_start_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/trakt/device/poll")
async def trakt_device_poll(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    from services.manager import _build_trakt_device_poll_snapshot

    data, status_code = _build_trakt_device_poll_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/trakt/device/poll")
async def trakt_device_poll_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    from services.manager import _build_trakt_device_poll_snapshot

    data, status_code = _build_trakt_device_poll_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/trakt/clear")
async def trakt_clear(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_trakt_clear_snapshot

    data, status_code = _build_trakt_clear_snapshot()
    return JSONResponse(data, status_code=status_code)


@router.post("/api/trakt/clear")
async def trakt_clear_api(request: Request):
    _require_auth_dep(request)
    from services.manager import _build_trakt_clear_snapshot

    data, status_code = _build_trakt_clear_snapshot()
    return JSONResponse(data, status_code=status_code)


@router.post("/update-config")
async def update_config_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
    db_host: str = Form(""),
    db_port: str = Form(""),
    db_name: str = Form(""),
    db_user: str = Form(""),
    db_password: str = Form(""),
    db_driver: str = Form(""),
    db_url: str = Form(""),
    db_params: str = Form(""),
    jellyseerr_url: str = Form(""),
    jellyseerr_api_key: str = Form(""),
    prowlarr_url: str = Form(""),
    prowlarr_api_key: str = Form(""),
    jackett_url: str = Form(""),
    jackett_api_key: str = Form(""),
    qbittorrent_url: str = Form(""),
    qbittorrent_username: str = Form(""),
    qbittorrent_password: str = Form(""),
    tmdb_api_key: str = Form(""),
    tmdb_language: str = Form("it-IT"),
    mdblist_api_keys: str = Form(""),
    omdb_api_keys: str = Form(""),
    trakt_client_id: str = Form(""),
    trakt_client_secret: str = Form(""),
    trakt_access_token: str = Form(""),
    trakt_enabled: str = Form(""),
    justwatch_enabled: str = Form(""),
    justwatch_locale: str = Form("it_IT"),
):
    """Update general configuration (database, API connections, Trakt, JustWatch)."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from services.manager import (
        _apply_db_env_overrides,
        _seed_db_from_legacy_config,
        _write_database_config,
        _load_app_settings_snapshot,
        _save_app_settings_snapshot,
    )

    legacy_config = read_raw_config() or {}
    next_url = _resolve_next_url_dep(next_page, "dashboard")

    db_defaults = legacy_config.get("DATABASE", {})
    db_payload = {
        "ENABLED": True,
        "HOST": db_host or db_defaults.get("HOST") or "",
        "PORT": _coerce_request_int(db_port or db_defaults.get("PORT"), 5432)
        if (db_port or db_defaults.get("PORT"))
        else "",
        "NAME": db_name or db_defaults.get("NAME") or "",
        "USER": db_user or db_defaults.get("USER") or "",
        "PASSWORD": db_password or db_defaults.get("PASSWORD") or "",
        "DRIVER": db_driver or db_defaults.get("DRIVER") or "postgresql+psycopg2",
        "URL": db_url or db_defaults.get("URL") or "",
        "PARAMS": db_params or db_defaults.get("PARAMS") or "",
    }
    db_settings_base = _merge_database_settings(db_payload)
    db_settings_effective = _apply_db_env_overrides(db_settings_base)

    if not db_settings_effective.get("URL") and (
        not db_settings_effective.get("HOST")
        or not db_settings_effective.get("NAME")
        or not db_settings_effective.get("USER")
    ):
        _flash_dep(request, "Compila host, database e username.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        backend = DatabaseStorage(db_settings_effective)
        backend.ensure_ready()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    _seed_db_from_legacy_config(legacy_config, backend)
    _write_database_config(db_settings_base)

    config, is_valid = _load_config_dep()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida. Controlla le impostazioni del database.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    app_settings = _load_app_settings_snapshot()
    connection_mappings = [
        ("JELLYSEERR_URL", jellyseerr_url),
        ("JELLYSEERR_API_KEY", jellyseerr_api_key),
        ("PROWLARR_URL", prowlarr_url),
        ("PROWLARR_API_KEY", prowlarr_api_key),
        ("JACKETT_URL", jackett_url),
        ("JACKETT_API_KEY", jackett_api_key),
        ("QBITTORRENT_URL", qbittorrent_url),
        ("QBITTORRENT_USERNAME", qbittorrent_username),
        ("QBITTORRENT_PASSWORD", qbittorrent_password),
        ("TMDB_API_KEY", tmdb_api_key),
        ("TMDB_LANGUAGE", tmdb_language),
    ]

    for config_key, form_value in connection_mappings:
        app_settings[config_key] = form_value or ""

    mdblist_keys = []
    if mdblist_api_keys:
        for line in mdblist_api_keys.split("\n"):
            for key in line.split(","):
                key = key.strip()
                if key:
                    mdblist_keys.append(key)
    app_settings["MDBLIST_API_KEYS"] = mdblist_keys

    omdb_keys = []
    if omdb_api_keys:
        for line in omdb_api_keys.split("\n"):
            for key in line.split(","):
                key = key.strip()
                if key:
                    omdb_keys.append(key)
    app_settings["OMDB_API_KEYS"] = omdb_keys
    if omdb_keys:
        app_settings["OMDB_API_KEY"] = omdb_keys[0]
    else:
        app_settings["OMDB_API_KEY"] = ""

    trakt_payload = _build_trakt_settings_payload(
        app_settings.get("TRAKT", {}),
        client_id=trakt_client_id,
        client_secret=trakt_client_secret,
        access_token=trakt_access_token,
        enabled=trakt_enabled,
    )
    app_settings["TRAKT"] = _merge_trakt_settings(trakt_payload)

    justwatch_payload = {
        "ENABLED": bool(justwatch_enabled),
        "LOCALE": justwatch_locale or "it_IT",
    }
    app_settings["JUSTWATCH"] = _merge_justwatch_settings(justwatch_payload)

    _save_app_settings_snapshot(app_settings)
    _load_config_dep()

    _flash_dep(request, "Configurazione aggiornata", "success")
    return RedirectResponse(url=next_url, status_code=303)
