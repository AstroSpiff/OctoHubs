"""FastAPI routes for the main dashboard."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app_helpers import _get_total_blacklist_counts
from app_state import _JELLYSEERR_REFRESH_STATE
from core.config import DEFAULT_CONFIG, TV_SORT_OPTIONS, MOVIE_SORT_OPTIONS, _default_auto_tasks
from core.config_manager import load_config
from search.availability import is_request_available, normalize_request_availability
from services.scheduler_manager import scan_manager
from services.scan_results import load_results_file
from services.requests_cache import _load_cached_requests_overview
from services.requests_summary import _estimate_variant_summary

router = APIRouter()

_templates: Optional[Jinja2Templates] = None
_get_flash_messages: Optional[Callable[[Request], list]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_get_current_user_id: Optional[Callable[[Request], Optional[int]]] = None
_has_users: Optional[Callable[[], bool]] = None


def init_dashboard_routes(
    templates: Jinja2Templates,
    get_flash_messages: Callable[[Request], list],
    get_csrf_token: Callable[[Request], str],
    get_current_user_id: Callable[[Request], Optional[int]],
    has_users: Callable[[], bool],
) -> None:
    global _templates, _get_flash_messages, _get_csrf_token, _get_current_user_id, _has_users
    _templates = templates
    _get_flash_messages = get_flash_messages
    _get_csrf_token = get_csrf_token
    _get_current_user_id = get_current_user_id
    _has_users = has_users


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Dashboard routes not initialized: templates missing")
    return _templates


def _get_flash_messages_dep(request: Request) -> list:
    if _get_flash_messages is None:
        raise RuntimeError("Dashboard routes not initialized: get_flash_messages missing")
    return _get_flash_messages(request)


def _get_csrf_token_dep(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Dashboard routes not initialized: get_csrf_token missing")
    return _get_csrf_token(request)


def _get_current_user_id_dep(request: Request) -> Optional[int]:
    if _get_current_user_id is None:
        raise RuntimeError("Dashboard routes not initialized: get_current_user_id missing")
    return _get_current_user_id(request)


def _has_users_dep() -> bool:
    if _has_users is None:
        raise RuntimeError("Dashboard routes not initialized: has_users missing")
    return _has_users()


@router.get("/", response_class=HTMLResponse)
async def dashboard_root(request: Request):
    """Main dashboard page - redirect to login if not authenticated."""
    user_id = _get_current_user_id_dep(request)
    if not user_id:
        if not _has_users_dep():
            return RedirectResponse(url="/setup", status_code=303)
        return RedirectResponse(url="/login", status_code=303)

    config, is_valid = load_config()
    status = scan_manager.get_status()
    results = status.get("last_summary") or load_results_file()
    message = request.query_params.get("msg")
    qb_available = bool(
        config
        and config.get("QBITTORRENT_URL")
        and config.get("QBITTORRENT_USERNAME")
        and config.get("QBITTORRENT_PASSWORD")
    )

    if is_valid:
        requests_overview_data, overview_stamp = _load_cached_requests_overview()
        requests_overview: list = requests_overview_data if isinstance(requests_overview_data, list) else []
        requests_overview = normalize_request_availability(requests_overview)
    else:
        requests_overview = []
        overview_stamp = None

    # Filter results to remove fully available content.
    available_ids = {
        str(req.get("request_id") or req.get("id"))
        for req in requests_overview
        if is_request_available(req)
    }

    # Filter requests overview to remove content that is available after normalization.
    requests_overview = [req for req in requests_overview if not is_request_available(req)]

    # Filter results items to remove available content.
    if results and results.get("items"):
        results["items"] = [
            item for item in results["items"] if str(item.get("request_id")) not in available_ids
        ]

    tv_requests = [
        req
        for req in requests_overview
        if (req.get("media_type") or "").lower() == "tv"
    ]
    movie_requests = [
        req
        for req in requests_overview
        if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")
    ]
    variant_estimate = _estimate_variant_summary((config or {}).get("SEARCH_RULES"))
    auto_tasks = config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks()
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    # Get flash messages (store once to avoid double pop).
    messages = _get_flash_messages_dep(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return _get_csrf_token_dep(request)

    requests_refresh_warning = _JELLYSEERR_REFRESH_STATE.get("last_warning")
    requests_refresh_warning_at = _JELLYSEERR_REFRESH_STATE.get("last_warning_at")

    return _templates_dep().TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "has_config": is_valid,
            "config": config,
            "search_rules": (config or {}).get("SEARCH_RULES", DEFAULT_CONFIG["SEARCH_RULES"]),
            "tv_sort_options": TV_SORT_OPTIONS,
            "movie_sort_options": MOVIE_SORT_OPTIONS,
            "results": results,
            "status": status,
            "qb_available": qb_available,
            "message": message,
            "requests_overview": requests_overview,
            "tv_requests": tv_requests,
            "movie_requests": movie_requests,
            "variant_estimate": variant_estimate,
            "requests_updated_at": overview_stamp,
            "requests_refresh_warning": requests_refresh_warning,
            "requests_refresh_warning_at": requests_refresh_warning_at,
            "auto_tasks": auto_tasks,
            "active_page": "jellyseerr",
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_alias(request: Request):
    return await dashboard_root(request)
