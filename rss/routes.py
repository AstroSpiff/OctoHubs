"""FastAPI routes for RSS-related operations."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import _coerce_request_bool, _coerce_request_int
from core.storage import StorageError
from core.utils import _split_csv_field, json_error
from rss.manager import (
    _build_rss_inspect_snapshot,
    _build_rss_inspect_json_snapshot,
    _build_rss_import_snapshot,
    _build_rss_import_json_snapshot,
    _build_rss_deduplicate_snapshot,
    _build_rss_items_snapshot,
    _build_rss_search_snapshot,
    _build_rss_delete_snapshot,
    _build_categories_snapshot,
    _build_blacklist_snapshot,
    _build_blacklist_add_snapshot,
    _build_blacklist_remove_snapshot,
    _build_hidden_snapshot,
    _build_hidden_add_snapshot,
    _build_hidden_remove_snapshot,
    _build_hidden_add_batch_snapshot,
    _build_hidden_remove_batch_snapshot,
    _build_blacklist_add_batch_snapshot,
    _build_blacklist_remove_batch_snapshot,
    _build_delete_by_categories_snapshot,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[[Request, str, str], None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_load_config: Optional[Callable[[], Any]] = None
_update_app_settings_overrides: Optional[Callable[[dict], None]] = None


def init_rss_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[[Request, str, str], None],
    resolve_next_url: Callable[[Optional[str], str], str],
    load_config: Callable[[], Any],
    update_app_settings_overrides: Callable[[dict], None],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _load_config, _update_app_settings_overrides
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _load_config = load_config
    _update_app_settings_overrides = update_app_settings_overrides


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("RSS routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("RSS routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(request: Request, message: str, category: str = "message") -> None:
    if _flash is None:
        raise RuntimeError("RSS routes not initialized: flash missing")
    _flash(request, message, category)


def _resolve_next_url_dep(next_url: Optional[str], fallback_endpoint: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("RSS routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_url, fallback_endpoint)


def _load_rss_config_dep():
    if _load_config is None:
        raise RuntimeError("RSS routes not initialized: load_config missing")
    config, is_valid = _load_config()
    if not is_valid or not config:
        return None
    return config


def _update_app_settings_overrides_dep(payload: dict) -> None:
    if _update_app_settings_overrides is None:
        raise RuntimeError("RSS routes not initialized: update_app_settings_overrides missing")
    _update_app_settings_overrides(payload)


def _error_response(message: str, status_code: int = 400) -> JSONResponse:
    data, code = json_error(message, status_code)
    return JSONResponse(data, status_code=code)


@router.post("/rss/inspect")
async def rss_inspect(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_rss_inspect_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/inspect")
async def rss_inspect_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_rss_inspect_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/rss/inspect-json")
async def rss_inspect_json(request: Request):
    _require_auth_dep(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_inspect_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/inspect-json")
async def rss_inspect_json_api(request: Request):
    _require_auth_dep(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_inspect_json_snapshot(file_obj)
    return JSONResponse(data, status_code=status_code)


@router.post("/rss/import")
async def rss_import(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_rss_import_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/import")
async def rss_import_api(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_rss_import_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.post("/rss/import-json")
async def rss_import_json(request: Request):
    _require_auth_dep(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_import_json_snapshot(_load_rss_config_dep(), file_obj)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/import-json")
async def rss_import_json_api(request: Request):
    _require_auth_dep(request)
    try:
        form = await request.form()
    except Exception:
        form = {}
    file_obj = form.get("json_file")
    data, status_code = _build_rss_import_json_snapshot(_load_rss_config_dep(), file_obj)
    return JSONResponse(data, status_code=status_code)


@router.post("/rss/deduplicate")
async def rss_deduplicate(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_rss_deduplicate_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/deduplicate")
async def rss_deduplicate_api(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_rss_deduplicate_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.get("/rss/items")
async def rss_items(request: Request):
    _require_auth_dep(request)
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    data, status_code = _build_rss_items_snapshot(_load_rss_config_dep(), limit, offset)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/rss/items")
async def rss_items_api(request: Request):
    _require_auth_dep(request)
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    data, status_code = _build_rss_items_snapshot(_load_rss_config_dep(), limit, offset)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/rss/search")
async def rss_search_api(request: Request):
    _require_auth_dep(request)
    keywords = request.query_params.get("keywords")
    limit = request.query_params.get("limit")
    offset = request.query_params.get("offset")
    use_regex = _coerce_request_bool(request.query_params.get("use_regex"), False)
    search_in = request.query_params.get("search_in")
    data, status_code = _build_rss_search_snapshot(_load_rss_config_dep(), keywords, limit, offset, use_regex, search_in)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/items")
async def rss_delete_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload rss delete: {exc}")
        return _error_response("Payload JSON non valido", 400)

    item_ids = payload.get("item_ids", [])
    data, status_code = _build_rss_delete_snapshot(_load_rss_config_dep(), item_ids)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/rss/categories")
async def rss_categories_api(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_categories_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.get("/api/rss/blacklist")
async def rss_blacklist_get_api(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_blacklist_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/blacklist")
async def rss_blacklist_add_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload blacklist add: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_name = payload.get("category_name", "")
    data, status_code = _build_blacklist_add_snapshot(_load_rss_config_dep(), category_name)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/blacklist")
async def rss_blacklist_remove_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload blacklist remove: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_name = payload.get("category_name", "")
    data, status_code = _build_blacklist_remove_snapshot(_load_rss_config_dep(), category_name)
    return JSONResponse(data, status_code=status_code)


@router.get("/api/rss/hidden")
async def rss_hidden_get_api(request: Request):
    _require_auth_dep(request)
    data, status_code = _build_hidden_snapshot(_load_rss_config_dep())
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/hidden")
async def rss_hidden_add_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload hidden add: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_name = payload.get("category_name", "")
    data, status_code = _build_hidden_add_snapshot(_load_rss_config_dep(), category_name)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/hidden")
async def rss_hidden_remove_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload hidden remove: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_name = payload.get("category_name", "")
    data, status_code = _build_hidden_remove_snapshot(_load_rss_config_dep(), category_name)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/hidden/batch")
async def rss_hidden_add_batch_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload hidden add batch: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_names = payload.get("category_names", [])
    data, status_code = _build_hidden_add_batch_snapshot(_load_rss_config_dep(), category_names)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/hidden/batch")
async def rss_hidden_remove_batch_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload hidden remove batch: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_names = payload.get("category_names", [])
    data, status_code = _build_hidden_remove_batch_snapshot(_load_rss_config_dep(), category_names)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/rss/blacklist/batch")
async def rss_blacklist_add_batch_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload blacklist add batch: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_names = payload.get("category_names", [])
    data, status_code = _build_blacklist_add_batch_snapshot(_load_rss_config_dep(), category_names)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/blacklist/batch")
async def rss_blacklist_remove_batch_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload blacklist remove batch: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_names = payload.get("category_names", [])
    data, status_code = _build_blacklist_remove_batch_snapshot(_load_rss_config_dep(), category_names)
    return JSONResponse(data, status_code=status_code)


@router.delete("/api/rss/items/by-categories")
async def rss_delete_by_categories_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload delete by categories: {exc}")
        return _error_response("Payload JSON non valido", 400)

    category_names = payload.get("category_names", [])
    data, status_code = _build_delete_by_categories_snapshot(_load_rss_config_dep(), category_names)
    return JSONResponse(data, status_code=status_code)


@router.post("/update-rss-import")
async def update_rss_import_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update RSS import settings."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    form_data = await request.form()
    if _load_config is None:
        raise RuntimeError("RSS routes not initialized: load_config missing")
    config, is_valid = _load_config()
    next_url = _resolve_next_url_dep(next_page, "dashboard")
    if not is_valid or not config:
        _flash_dep(request, "Config non valida. Completa la configurazione.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    enabled = bool(form_data.get("rss_enabled"))
    poll_interval = _coerce_request_int(form_data.get("rss_poll_interval") or 30, 30)
    poll_interval = max(5, min(1440, poll_interval))
    dedup_keep = form_data.get("rss_dedup_keep") or "oldest"
    dedup_keep = "newest" if dedup_keep == "newest" else "oldest"

    sources = []
    sources_value = form_data.get("rss_sources")
    sources_text = sources_value if isinstance(sources_value, str) else ""
    for line in sources_text.splitlines():
        entry = line.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        name = ""
        url = ""
        tags = []
        if len(parts) == 1:
            url = parts[0]
        else:
            name = parts[0]
            url = parts[1]
            if len(parts) > 2:
                tags = _split_csv_field(parts[2])
        if not url:
            continue
        sources.append({
            "name": name,
            "url": url,
            "tags": tags,
            "enabled": True,
        })

    payload = {
        "ENABLED": enabled,
        "POLL_INTERVAL_MINUTES": poll_interval,
        "DEDUP_KEEP": dedup_keep,
        "SOURCES": sources,
    }
    try:
        _update_app_settings_overrides_dep({"RSS_IMPORT": payload})
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio RSS: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    _flash_dep(request, "Configurazione RSS aggiornata", "success")
    return RedirectResponse(url=next_url, status_code=303)
