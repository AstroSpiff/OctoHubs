"""FastAPI routes for configuration pages and updates."""

from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app_helpers import _get_total_blacklist_counts
from app_state import _JELLYSEERR_REFRESH_STATE
from core import config_manager as _config_manager
from core.config import _default_auto_tasks, _default_emby_settings, _clean_sort_mode
from core.config_manager import load_config, _db_enabled
from core.storage import StorageError
from core.utils import _split_csv_field, _coerce_request_int
from emby_actions import _prepare_emby_servers_for_view
from services.app_settings import _update_app_settings_overrides, _parse_auto_task_payload
from telegram import _default_telegram_settings, _load_telegram_settings, _build_telegram_alerts

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_get_flash_messages: Optional[Callable[[Request], list]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_templates: Optional[Jinja2Templates] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None


def init_config_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    get_flash_messages: Callable[[Request], list],
    get_csrf_token: Callable[[Request], str],
    templates: Jinja2Templates,
    resolve_next_url: Callable[[Optional[str], str], str],
) -> None:
    global _require_auth, _validate_csrf, _flash, _get_flash_messages, _get_csrf_token
    global _templates, _resolve_next_url
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _get_flash_messages = get_flash_messages
    _get_csrf_token = get_csrf_token
    _templates = templates
    _resolve_next_url = resolve_next_url


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Config routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Config routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Config routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _get_flash_messages_dep(request: Request) -> list:
    if _get_flash_messages is None:
        raise RuntimeError("Config routes not initialized: get_flash_messages missing")
    return _get_flash_messages(request)


def _get_csrf_token_dep(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Config routes not initialized: get_csrf_token missing")
    return _get_csrf_token(request)


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Config routes not initialized: templates missing")
    return _templates


def _resolve_next_url_dep(next_param: Optional[str], default_page: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Config routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_param, default_page)


@router.get("/configuration", response_class=HTMLResponse)
async def configuration_page(request: Request):
    """Configuration page."""
    _require_auth_dep(request)

    config, is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    auto_tasks = (config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks())
    collection_config = (config or {}).get("COLLECTIONS", {})
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    telegram_settings = _default_telegram_settings()
    telegram_ready = False
    telegram_alerts = {"groups": {}, "channels": {}}

    if config and _db_enabled(config.get("DATABASE", {})):
        telegram_ready = True
        telegram_settings = _load_telegram_settings()
        telegram_alerts = _build_telegram_alerts(telegram_settings)

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
        "configuration.html",
        {
            "request": request,
            "has_config": is_valid,
            "config": config,
            "emby_config": emby_config,
            "emby_servers": emby_servers,
            "auto_tasks": auto_tasks,
            "collection_config": collection_config,
            "telegram_settings": telegram_settings,
            "telegram_bots": telegram_settings.get("BOTS", []),
            "telegram_groups": telegram_settings.get("GROUPS", []),
            "telegram_channels": telegram_settings.get("CHANNELS", []),
            "telegram_presets": telegram_settings.get("PRESETS", []),
            "telegram_alerts": telegram_alerts,
            "telegram_ready": telegram_ready,
            "active_page": "config",
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "requests_refresh_warning": requests_refresh_warning,
            "requests_refresh_warning_at": requests_refresh_warning_at,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
        },
    )


@router.post("/update-scheduler")
async def update_scheduler_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update scheduler automation settings (scan, refresh, workflow, collections)."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from services.scheduler_manager import sync_auto_scheduler
    from core.config import DEFAULT_CONFIG as CONFIG_DEFAULTS, _normalize_time_list

    config, is_valid = load_config()
    next_url = _resolve_next_url_dep(next_page, "dashboard")

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    form_data = await request.form()

    defaults = _default_auto_tasks()
    current = config.get("AUTO_TASKS") or defaults
    updated = copy.deepcopy(current)

    def _parse_auto_section(section_key: str, fallback: dict) -> dict:
        if form_data.get(section_key) is not None:
            parsed = _parse_auto_task_payload(form_data, section_key, fallback)
            return parsed if isinstance(parsed, dict) else fallback
        enabled = bool(form_data.get(f"{section_key}_enabled"))
        mode = form_data.get(f"{section_key}_mode") or fallback.get("mode", "interval")
        if mode not in ("interval", "fixed"):
            mode = "interval"
        interval_default = fallback.get("interval_minutes", 60)
        interval = _coerce_request_int(form_data.get(f"{section_key}_interval"), interval_default, 1)
        times_raw = form_data.get(f"{section_key}_times")
        if times_raw is None:
            times = fallback.get("times") or []
        else:
            if not isinstance(times_raw, str):
                times_raw = str(times_raw)
            times = _normalize_time_list(times_raw)
        return {
            "enabled": enabled,
            "mode": mode,
            "interval_minutes": interval,
            "times": times,
        }

    updated["scan"] = _parse_auto_section("scan", current.get("scan", defaults["scan"]))
    updated["refresh"] = _parse_auto_section("refresh", current.get("refresh", defaults["refresh"]))
    updated["workflow"] = _parse_auto_section("workflow", current.get("workflow", defaults["workflow"]))
    updated["sync"] = _parse_auto_section(
        "sync",
        current.get("sync", defaults.get("sync", {"enabled": False, "mode": "interval", "interval_minutes": 60, "times": []})),
    )
    updated["rss"] = _parse_auto_section(
        "rss",
        current.get("rss", defaults.get("rss", {"enabled": False, "mode": "interval", "interval_minutes": 30, "times": []})),
    )

    rss_import_config = config.get("RSS_IMPORT") or {}
    if updated["rss"].get("enabled") != rss_import_config.get("ENABLED"):
        rss_import_config["ENABLED"] = updated["rss"].get("enabled", False)
        config["RSS_IMPORT"] = rss_import_config

    collections_enabled = form_data.get("collections_auto_refresh_enabled")
    collections_mode = form_data.get("collections_auto_refresh_mode") or "interval"
    collections_interval_raw = form_data.get("collections_auto_refresh_interval")
    collections_times_raw = form_data.get("collections_auto_refresh_times")
    if collections_times_raw is not None and not isinstance(collections_times_raw, str):
        collections_times_raw = str(collections_times_raw)
    interval_default = CONFIG_DEFAULTS["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"]
    collections_interval = _coerce_request_int(collections_interval_raw, interval_default, 5, 10080)
    collections_times = _split_csv_field(collections_times_raw)
    if collections_mode not in ("interval", "fixed"):
        collections_mode = "interval"
    collections_payload = {
        "AUTO_REFRESH_ENABLED": bool(collections_enabled),
        "AUTO_REFRESH_INTERVAL_MINUTES": collections_interval,
        "AUTO_REFRESH_MODE": collections_mode,
        "AUTO_REFRESH_TIMES": collections_times,
    }

    try:
        _update_app_settings_overrides({
            "AUTO_TASKS": updated,
            "COLLECTIONS": collections_payload,
            "RSS_IMPORT": rss_import_config,
        })
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio automazioni: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if _config_manager._ACTIVE_CONFIG is None:
        _config_manager._ACTIVE_CONFIG = copy.deepcopy(CONFIG_DEFAULTS)
    _config_manager._ACTIVE_CONFIG["AUTO_TASKS"] = updated
    _config_manager._ACTIVE_CONFIG["COLLECTIONS"] = collections_payload
    _config_manager._ACTIVE_CONFIG["RSS_IMPORT"] = rss_import_config
    config["AUTO_TASKS"] = updated
    config["COLLECTIONS"] = collections_payload
    config["RSS_IMPORT"] = rss_import_config

    sync_auto_scheduler(is_valid)

    _flash_dep(request, "Automazioni aggiornate.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/update-rules")
async def update_rules_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
    target_languages: str = Form(""),
    exclude_tags: str = Form(""),
    query_languages: str = Form(""),
    use_original_title: str = Form(None),
    use_alt_titles_original: str = Form(None),
    sanitize_titles: str = Form(None),
    ignore_year_for_tv: str = Form(None),
    require_audio_language: str = Form(None),
    include_target_lang_base: str = Form(None),
    search_episode_variants: str = Form(None),
    skip_available_content: str = Form(None),
    skip_unreleased_content: str = Form(None),
    skip_season_query_when_episode_search: str = Form(None),
    min_seeders: str = Form("0"),
    query_terms: str = Form(""),
    filter_terms: str = Form(""),
    season_templates: str = Form(""),
    use_alt_titles_language: str = Form(None),
    alt_titles_language: str = Form("all"),
    alt_titles_language_custom: str = Form(""),
    use_prowlarr: str = Form(None),
    use_jackett: str = Form(None),
    results_sort: str = Form(None),
    tv_sort_primary: str = Form(None),
    tv_sort_secondary: str = Form(None),
    movie_sort_primary: str = Form(None),
    movie_sort_secondary: str = Form(None),
):
    """Update search rules configuration (JustWatch, language, sort, etc.)."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from core.config import (
        _normalize_sort_settings,
        _default_search_rules,
        TV_SORT_KEYS,
        MOVIE_SORT_KEYS,
        DEFAULT_CONFIG,
    )

    config, is_valid = load_config()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida. Controlla le connessioni.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "dashboard")

    target_langs = _split_csv_field(target_languages)
    exclude_tags_list = _split_csv_field(exclude_tags)
    query_langs = _split_csv_field(query_languages)

    base_rules = config.get("SEARCH_RULES") or _default_search_rules()
    rules = copy.deepcopy(base_rules)

    bool_rules = [
        ("use_original_title", use_original_title),
        ("use_alt_titles_original", use_alt_titles_original),
        ("sanitize_titles", sanitize_titles),
        ("ignore_year_for_tv", ignore_year_for_tv),
        ("require_audio_language", require_audio_language),
        ("include_target_lang_base", include_target_lang_base),
        ("search_episode_variants", search_episode_variants),
        ("skip_available_content", skip_available_content),
        ("skip_unreleased_content", skip_unreleased_content),
    ]

    for rule_key, form_value in bool_rules:
        rules[rule_key] = bool(form_value)

    if rules["search_episode_variants"]:
        rules["skip_season_queries_when_episode_search"] = bool(skip_season_query_when_episode_search)
    else:
        rules["skip_season_queries_when_episode_search"] = False

    rules["min_seeders"] = max(0, _coerce_request_int(min_seeders or "0"))

    rules["query_terms"] = _split_csv_field(query_terms)
    rules["filter_terms"] = _split_csv_field(filter_terms)
    rules["season_templates"] = _split_csv_field(season_templates) or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    rules["query_languages"] = query_langs

    use_alt_language = bool(use_alt_titles_language)
    selected_language = alt_titles_language or "all"
    if selected_language == "custom":
        custom_value = (alt_titles_language_custom or "").strip().lower()
        selected_language = custom_value or "all"
    rules["use_alt_titles_language"] = use_alt_language
    rules["alt_titles_language"] = selected_language if use_alt_language else "disabled"

    rules["use_prowlarr"] = bool(use_prowlarr)
    rules["use_jackett"] = bool(use_jackett)

    if results_sort:
        rules["results_sort"] = results_sort

    rules["tv_sort_primary"] = _clean_sort_mode(
        tv_sort_primary if tv_sort_primary is not None else rules.get("tv_sort_primary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"],
    )
    rules["tv_sort_secondary"] = _clean_sort_mode(
        tv_sort_secondary if tv_sort_secondary is not None else rules.get("tv_sort_secondary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
        allow_empty=True,
    )
    rules["movie_sort_primary"] = _clean_sort_mode(
        movie_sort_primary if movie_sort_primary is not None else rules.get("movie_sort_primary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"],
    )
    rules["movie_sort_secondary"] = _clean_sort_mode(
        movie_sort_secondary if movie_sort_secondary is not None else rules.get("movie_sort_secondary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
        allow_empty=True,
    )

    rules = _normalize_sort_settings(rules)

    try:
        _update_app_settings_overrides({
            "TARGET_LANGUAGES": target_langs,
            "EXCLUDE_TAGS": exclude_tags_list,
            "SEARCH_RULES": rules,
        })
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio regole: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if _config_manager._ACTIVE_CONFIG is None:
        _config_manager._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    _config_manager._ACTIVE_CONFIG["TARGET_LANGUAGES"] = target_langs
    _config_manager._ACTIVE_CONFIG["EXCLUDE_TAGS"] = exclude_tags_list
    _config_manager._ACTIVE_CONFIG["SEARCH_RULES"] = rules

    _flash_dep(request, "Regole aggiornate con successo", "success")
    return RedirectResponse(url=next_url, status_code=303)
