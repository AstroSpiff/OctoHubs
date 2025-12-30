# app.py
import argparse
import copy
import json
import os
import sys
import threading
import time
import re
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from datetime import datetime, date, timezone, time as dt_time, timedelta
from email.utils import parsedate_to_datetime
from functools import wraps

import requests
from typing import Dict, Any, cast

from storage import DatabaseStorage, StorageError
from config import (
    CONFIG_FILE,
    _merge_database_settings,
    _merge_trakt_settings,
    _merge_justwatch_settings,
    _merge_rss_import_settings,
    _normalize_sort_settings,
    _clean_sort_mode,
    _normalize_auto_settings,
    _normalize_emby_server,
    _merge_emby_settings,
    TV_SORT_KEYS,
    MOVIE_SORT_KEYS,
    read_raw_config,
    write_config_file as config_write_file,
    _default_search_rules,
    _default_auto_tasks,
    _default_emby_settings,
    _split_csv_field,
    _coerce_request_bool,
    _coerce_request_int,
    _normalize_alt_language
)
from api_clients import (
    _prepare_emby_servers_for_view,
    _execute_emby_action,
    _fetch_emby_libraries,
    _fetch_emby_active_sessions,
    _fetch_emby_status,
    _fetch_emby_scheduled_tasks,
    _stop_emby_task,
    _trigger_library_scan,
    _call_emby_api,
    EMBY_ACTIONS,
    get_jellyseerr_requests,
    send_to_qbittorrent,
    _ping_api_service,
    _ping_jellyseerr,
    _ping_prowlarr,
    _ping_qbittorrent,
    fetch_request_details,
    fetch_media_info,
    search_jellyseerr,
    submit_jellyseerr_request,
    search_prowlarr,
    search_jackett,
    search_tmdb,
    get_tmdb_tv_details,
    check_emby_availability,
    check_jellyseerr_availability,
    _extract_tmdb_id,
    _fetch_tmdb_payload
)
from library_grouper import group_libraries
from justwatch_manager import JustWatchManager, JustWatchError, is_justwatch_available
from utils import (
    _safe_get_dict_value,
    _normalize_form_input,
    _apply_form_mapping,
    _sanitize_terms_list,
    _form_input_value,
    _normalize_season_spec,
    _parse_date_value,
    _normalize_media_type
)
from scanner import (
    extract_title_and_year,
    gather_title_candidates,
    build_search_queries,
    filter_results,
    sanitize_title,
    _extract_episode_from_title,
    _detect_resolution_bucket,
    _contains_language_token,
    _has_audio_language,
    _contains_isolated_tag
)
from tasks import ScanManager, AutoScheduler
from emby_probe import get_probe_manager, _format_display_name_from_queue
from emby_streams import get_streams_manager
from auth import init_auth, get_user_by_username, log_audit_event

try:
    from flask import Flask, request, render_template, redirect, url_for, jsonify, flash, Response, stream_with_context, session, abort
    from flask_login import login_user, logout_user, login_required, current_user
    from flask_wtf import CSRFProtect
    from flask_wtf.csrf import CSRFError
except ImportError:
    print("ERRORE: Flask, Flask-Login o Flask-WTF non sono installati. Esegui 'pip install Flask Flask-Login Flask-WTF' nel tuo ambiente virtuale.")
    sys.exit(1)

# --- COSTANTI ---

# Shared CSRF protection
csrf = CSRFProtect()


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that serializes datetime/date as ISO strings."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

DEFAULT_SORT_MODE = "seeders_desc"

TV_SORT_OPTIONS = [
    {"value": "size_asc", "label": "Dimensione [cres.]", "group": "size"},
    {"value": "size_desc", "label": "Dimensione [decr.]", "group": "size"},
    {"value": "episode_asc", "label": "Episodio [cres.]", "group": "episode"},
    {"value": "episode_desc", "label": "Episodio [decr.]", "group": "episode"},
    {"value": "seeders_asc", "label": "Seeders [cres.]", "group": "seeders"},
    {"value": "seeders_desc", "label": "Seeders [decr.]", "group": "seeders"},
    {"value": "title_asc", "label": "Titolo [A-Z]", "group": "title"},
    {"value": "title_desc", "label": "Titolo [Z-A]", "group": "title"},
]
MOVIE_SORT_OPTIONS = [
    {"value": "size_asc", "label": "Dimensione [cres.]", "group": "size"},
    {"value": "size_desc", "label": "Dimensione [decr.]", "group": "size"},
    {"value": "seeders_asc", "label": "Seeders [cres.]", "group": "seeders"},
    {"value": "seeders_desc", "label": "Seeders [decr.]", "group": "seeders"},
    {"value": "title_asc", "label": "Titolo [A-Z]", "group": "title"},
    {"value": "title_desc", "label": "Titolo [Z-A]", "group": "title"},
]
TV_SORT_KEYS = [opt["value"] for opt in TV_SORT_OPTIONS]
MOVIE_SORT_KEYS = [opt["value"] for opt in MOVIE_SORT_OPTIONS]
EMBY_CATEGORY_OPTIONS = [
    {"value": "production", "label": "Produzione"},
    {"value": "test", "label": "Test"},
    {"value": "staging", "label": "Staging"},
    {"value": "development", "label": "Sviluppo"}
]

DEFAULT_CONFIG = {
    "JELLYSEERR_URL": "",
    "JELLYSEERR_API_KEY": "",
    "PROWLARR_URL": "",
    "PROWLARR_API_KEY": "",
    "JACKETT_URL": "",
    "JACKETT_API_KEY": "",
    "QBITTORRENT_URL": "",
    "QBITTORRENT_USERNAME": "",
    "QBITTORRENT_PASSWORD": "",
    "TMDB_API_KEY": "",
    "TMDB_LANGUAGE": "it-IT",
    "TARGET_LANGUAGES": ["ita", "italian"],
    "EXCLUDE_TAGS": ["md", "cam", "ts", "tc", "vmd", "sub", "subs", "forced", "screener"],
    "SEARCH_RULES": {
        "use_original_title": True,
        "use_alt_titles_original": True,
        "use_alt_titles_language": False,
        "alt_titles_language": "all",
        "sanitize_titles": True,
        "query_terms": [],
        "include_target_lang_base": False,
        "filter_terms": [],
        "min_seeders": 0,
        "ignore_year_for_tv": False,
        "require_audio_language": True,
        "skip_available_content": True,
        "skip_unreleased_content": False,
        "results_sort": "seeders_desc",
        "tv_sort_primary": "seeders_desc",
        "tv_sort_secondary": "size_desc",
        "movie_sort_primary": "seeders_desc",
        "movie_sort_secondary": "size_desc",
        "season_templates": [
            "S{season02}",
            "S{season}",
            "{season}x",
            "{season02}x",
            "Stagione {season}",
            "Season {season}",
            "S{season02}E",
            "{season}xE"
        ],
        "search_episode_variants": True,
        "skip_season_queries_when_episode_search": False,
        "use_prowlarr": True,
        "use_jackett": False
    },
    "REQUEST_RULES": {},
    "DATABASE": {
        "ENABLED": False,
        "HOST": "localhost",
        "PORT": 5432,
        "NAME": "jellychecker",
        "USER": "jellychecker",
        "PASSWORD": "",
        "DRIVER": "postgresql+psycopg2",
        "URL": "",
        "PARAMS": ""
    },
    "TRAKT": {
        "ENABLED": False,
        "CLIENT_ID": "",
        "ACCESS_TOKEN": ""
    },
    "JUSTWATCH": {
        "ENABLED": False,
        "LOCALE": "it_IT"
    },
    "AUTO_TASKS": {
        "scan": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 240,
            "times": []
        },
        "refresh": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 120,
            "times": []
        }
    },
    "EMBY": {
        "SERVERS": []
    }
}

CONNECTION_FIELDS = [
    "JELLYSEERR_URL",
    "JELLYSEERR_API_KEY",
    "PROWLARR_URL",
    "PROWLARR_API_KEY",
    "JACKETT_URL",
    "JACKETT_API_KEY",
    "QBITTORRENT_URL",
    "QBITTORRENT_USERNAME",
    "QBITTORRENT_PASSWORD",
    "TMDB_API_KEY",
    "TMDB_LANGUAGE"
]

_ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
_DB_BACKEND = None
_DB_BACKEND_SIGNATURE = None
_TRAKT_CLIENT = None
_TRAKT_SIGNATURE = None
_JUSTWATCH_MANAGER = None
_JUSTWATCH_SIGNATURE = None
_JUSTWATCH_METADATA_CACHE = {}
_JUSTWATCH_MEDIA_CACHE = {}
_REQUESTS_CACHE = {
    "items": [],
    "generated_at": None
}
_AUTO_SCHEDULER = None
_EMBY_STRM_GUARD = None

EMBY_STRM_GUARD_KEY = "EMBY_STRM_GUARD"
EMBY_STRM_GUARD_COOLDOWN_SECONDS = 10
EMBY_STRM_GUARD_POLL_SECONDS = 5
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
TMDB_SEARCH_LIMIT = 15

# --- UTILS CONFIG ---
# Nota: _default_search_rules, _default_auto_tasks, _default_emby_settings sono ora importate da config.py
# Nota: tutte le funzioni Emby sono ora importate da api_clients.py

# Nota: _form_input_value, _safe_get_dict_value, _normalize_form_input, _apply_form_mapping sono ora importate da utils.py

def _merge_config_section(raw_config, new_data, section_key, merger_func):
    """Generic config section merge."""
    section_data = new_data.get(section_key) or raw_config.get(section_key)
    return merger_func(section_data)

# --- GESTIONE CONFIGURAZIONE ---

def load_config():
    """Carica la configurazione dal file JSON."""
    global _ACTIVE_CONFIG
    if not os.path.exists(CONFIG_FILE):
        return None, False # Config non esiste
    try:
        with open(CONFIG_FILE, 'r') as f:
            file_config = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None, False
    database_settings = _merge_database_settings((file_config or {}).get("DATABASE"))
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for key in CONNECTION_FIELDS:
        merged[key] = file_config.get(key, merged.get(key))
    merged["DATABASE"] = database_settings
    merged["TRAKT"] = _merge_trakt_settings(file_config.get("TRAKT"))
    merged["JUSTWATCH"] = _merge_justwatch_settings(file_config.get("JUSTWATCH"))
    merged["EMBY"] = _merge_emby_settings((file_config or {}).get("EMBY"))

    # Setta _ACTIVE_CONFIG subito in modo che _ensure_db_backend possa accedervi
    _ACTIVE_CONFIG = merged

    # Validazione: richiede Jellyseerr + almeno uno tra Prowlarr o Jackett
    jellyseerr_ok = bool(merged.get("JELLYSEERR_URL") and merged.get("JELLYSEERR_API_KEY"))
    prowlarr_ok = _prowlarr_configured(merged)
    jackett_ok = _jackett_configured(merged)
    connection_valid = jellyseerr_ok and (prowlarr_ok or jackett_ok)
    if not _db_enabled(database_settings):
        print("   -> Il database risulta disattivato nelle impostazioni: abilitalo per proseguire.")
        return merged, False

    try:
        backend = _get_db_backend(database_settings)
        if not backend:
            print("   -> Impossibile inizializzare la connessione al database.")
            return merged, False
    except StorageError as exc:
        print(f"   -> Database non disponibile: {exc}")
        merged["DATABASE"]["ENABLED"] = False
        return merged, False

    legacy_target = file_config.get("TARGET_LANGUAGES")
    legacy_exclude = file_config.get("EXCLUDE_TAGS")
    legacy_rules = (file_config or {}).get("SEARCH_RULES")
    legacy_request_rules = (file_config or {}).get("REQUEST_RULES")

    app_settings = backend.load_app_settings() or {}
    search_rules = _default_search_rules()
    need_save = False

    if legacy_rules and not app_settings.get("SEARCH_RULES"):
        app_settings["SEARCH_RULES"] = legacy_rules
        need_save = True
    if legacy_target and not app_settings.get("TARGET_LANGUAGES"):
        app_settings["TARGET_LANGUAGES"] = legacy_target
        need_save = True
    if legacy_exclude and not app_settings.get("EXCLUDE_TAGS"):
        app_settings["EXCLUDE_TAGS"] = legacy_exclude
        need_save = True

    target_langs = app_settings.get("TARGET_LANGUAGES") or merged["TARGET_LANGUAGES"]
    exclude_tags = app_settings.get("EXCLUDE_TAGS") or merged["EXCLUDE_TAGS"]
    search_rules.update(app_settings.get("SEARCH_RULES") or {})
    search_rules = _normalize_sort_settings(search_rules)
    auto_settings = _normalize_auto_settings(app_settings.get("AUTO_TASKS"))
    rss_import_settings = _merge_rss_import_settings(app_settings.get("RSS_IMPORT"))

    if need_save or not app_settings or "AUTO_TASKS" not in app_settings:
        persisted = dict(app_settings)
        persisted.update({
            "TARGET_LANGUAGES": target_langs,
            "EXCLUDE_TAGS": exclude_tags,
            "SEARCH_RULES": search_rules,
            "AUTO_TASKS": auto_settings
        })
        backend.save_app_settings(persisted)
        app_settings = persisted

    request_rules = backend.load_request_rules()
    if (not request_rules) and legacy_request_rules:
        backend.save_request_rules(legacy_request_rules)
        request_rules = legacy_request_rules

    merged["TARGET_LANGUAGES"] = target_langs
    merged["EXCLUDE_TAGS"] = exclude_tags
    merged["SEARCH_RULES"] = search_rules
    merged["REQUEST_RULES"] = request_rules or {}
    merged["AUTO_TASKS"] = auto_settings
    merged["RSS_IMPORT"] = rss_import_settings

    _ACTIVE_CONFIG = merged
    _sync_auto_scheduler(connection_valid)
    return merged, connection_valid

# Nota: read_raw_config e write_config_file sono ora importate da config.py (come config_write_file)
# Nota: _split_csv_field, _coerce_request_bool, _coerce_request_int, _normalize_alt_language sono ora importate da config.py
# Nota: _sanitize_terms_list è ora importata da utils.py

def _compose_request_search_rules(base_rules, request_rule):
    merged = copy.deepcopy(base_rules or _default_search_rules())
    if not request_rule:
        return merged
    merged["use_original_title"] = request_rule.get("use_original_title", merged.get("use_original_title"))
    merged["use_alt_titles_original"] = request_rule.get("use_alt_titles_original", merged.get("use_alt_titles_original"))
    merged["use_alt_titles_language"] = request_rule.get("use_alt_titles_language", merged.get("use_alt_titles_language"))
    alt_value = request_rule.get("alt_titles_language")
    if alt_value:
        merged["alt_titles_language"] = alt_value
    return merged

def _get_request_rule(config, request_id):
    if not config:
        return {}
    rules_map = config.get("REQUEST_RULES") or {}
    entry = rules_map.get(str(request_id)) or rules_map.get(request_id)
    base_rules = (config.get("SEARCH_RULES") or _default_search_rules()) if config else _default_search_rules()
    if not isinstance(entry, dict):
        return {
            "enabled": True,
            "query_terms": [],
            "filter_terms": [],
            "exclude_terms": [],
            "use_original_title": base_rules.get("use_original_title", True),
            "use_alt_titles_original": base_rules.get("use_alt_titles_original", True),
            "use_alt_titles_language": base_rules.get("use_alt_titles_language", False),
            "alt_titles_language": (base_rules.get("alt_titles_language") or "all").lower(),
            "year_variance": 0
        }
    enabled = entry.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.lower() not in ("false", "0", "no")
    if enabled is None:
        enabled = True
    alt_default = (base_rules.get("alt_titles_language") or "all").lower()
    return {
        "query_terms": _sanitize_terms_list(entry.get("query_terms")),
        "filter_terms": _sanitize_terms_list(entry.get("filter_terms")),
        "exclude_terms": _sanitize_terms_list(entry.get("exclude_terms")),
        "enabled": bool(enabled),
        "use_original_title": _coerce_request_bool(entry.get("use_original_title"), base_rules.get("use_original_title", True)),
        "use_alt_titles_original": _coerce_request_bool(entry.get("use_alt_titles_original"), base_rules.get("use_alt_titles_original", True)),
        "use_alt_titles_language": _coerce_request_bool(entry.get("use_alt_titles_language"), base_rules.get("use_alt_titles_language", False)),
        "alt_titles_language": _normalize_alt_language(entry.get("alt_titles_language"), alt_default),
        "year_variance": _coerce_request_int(entry.get("year_variance"), 0, 0, 10)
    }

def _estimate_variant_summary(rules):
    if not rules:
        rules = DEFAULT_CONFIG["SEARCH_RULES"]
    season_templates = rules.get("season_templates") or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    season_variants = max(1, len([tpl for tpl in season_templates if tpl]))
    query_terms_count = len(_sanitize_terms_list(rules.get("query_terms")))
    title_forms = 1
    if rules.get("use_original_title"):
        title_forms += 1
    if rules.get("use_alt_titles_original"):
        title_forms += 1
    if rules.get("use_alt_titles_language") and (rules.get("alt_titles_language") not in ("", "disabled")):
        title_forms += 1
    if rules.get("sanitize_titles"):
        title_forms += 1
    base_variants = title_forms * season_variants * (query_terms_count if query_terms_count > 0 else 1)
    episode_variants = 0
    if rules.get("search_episode_variants"):
        episode_variants = base_variants * 10
    return {
        "title_forms": title_forms,
        "season_variants": season_variants,
        "query_terms": query_terms_count,
        "base": base_variants,
        "episodes": episode_variants
    }

def _resolve_request_metadata_for_summary(req, config, details_cache, media_cache, force_details=False):
    base_data = req
    media_info = base_data.get("media") or {}
    media_type = req.get("type") or media_info.get("mediaType")
    extra_sources = []
    for key in ("media", "mediaInfo"):
        val = base_data.get(key)
        if isinstance(val, dict):
            extra_sources.append(val)
            nested = val.get("mediaInfo")
            if isinstance(nested, dict):
                extra_sources.append(nested)
    title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if force_details or not title or not media_type:
        detailed = fetch_request_details(req.get("id"), config, details_cache)
        if detailed:
            base_data = detailed
            media_info = base_data.get("media") or media_info
            media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
            extra_sources.extend([detailed, detailed.get("media"), detailed.get("mediaInfo")])
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if not title:
        media_details, resolved_type = fetch_media_info(media_info, config, media_cache, media_type)
        if media_details:
            extra_sources.append(media_details)
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources + [media_details])
            if resolved_type and not media_type:
                media_type = resolved_type
    if not title:
        candidates = gather_title_candidates(base_data, extra_sources=extra_sources, search_rules=config.get("SEARCH_RULES"))
        if candidates:
            title = candidates[0]
    if not title:
        fallback_sources = [base_data, base_data.get("media"), base_data.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    return base_data, title, year, media_type

def _summarize_requests_for_dashboard(config):
    if not config:
        return []
    try:
        requests_data = get_jellyseerr_requests(config, silent=True)
        print(f"   -> Dashboard: Jellyseerr ha restituito {len(requests_data)} richieste (pending+approved)")
        _log_justwatch_status()
    except Exception as exc:
        print(f"   -> Errore durante il recupero richieste Jellyseerr per dashboard: {exc}")
        return []
    summary = []
    details_cache = {}
    media_cache = {}
    now = datetime.now(timezone.utc)
    rules = config.get("SEARCH_RULES", {})
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    enriched_requests = []
    for req in requests_data:
        media_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        if media_type == "tv":
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                enriched_requests.append(detailed)
                continue
        enriched_requests.append(req)
    requests_data = enriched_requests
    for req in requests_data:
        req_id = req.get("id")
        type_hint = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        force_details = bool(type_hint == "tv")
        base_req, title, year, media_type = _resolve_request_metadata_for_summary(
            req,
            config,
            details_cache,
            media_cache,
            force_details=force_details
        )
        normalized_type = _normalize_media_type(media_type)
        season_status = describe_season_statuses(base_req) if normalized_type == "tv" else []
        seasons = [entry["season"] for entry in season_status]
        release_dt = _request_release_date(base_req)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        status_code = base_req.get("media", {}).get("status") or req.get("media", {}).get("status")
        request_rule = _get_request_rule(config, req_id)
        will_skip = False
        if skip_available and status_code == 5:
            will_skip = True
        if skip_unreleased and release_dt and release_dt > now:
            will_skip = True
        if normalized_type == "tv" and season_status:
            scan_candidates = select_scan_seasons(season_status, skip_available, skip_unreleased)
            if not scan_candidates:
                will_skip = True
        created_at = _parse_date_value(
            req.get("createdAt") or req.get("created_at") or req.get("addedAt") or req.get("added_at")
        )
        age_label = None
        if created_at:
            diff = now - created_at
            days = diff.days
            seconds = diff.seconds
            if days > 0:
                age_label = f"{days}g fa"
            elif seconds >= 3600:
                age_label = f"{seconds // 3600}h fa"
            elif seconds >= 60:
                age_label = f"{seconds // 60}m fa"
            else:
                age_label = "Pochi secondi fa"
        justwatch_checked = False
        justwatch_available = False
        justwatch_providers = []
        if normalized_type != "tv" and not (status_code == 5 or (release_dt and release_dt > now)):
            settings = _active_justwatch_settings()
            if _justwatch_enabled(settings):
                manager = _get_justwatch_manager(settings)
                if manager and title:
                    year_int = None
                    if isinstance(year, int):
                        year_int = year
                    elif isinstance(year, str):
                        try:
                            year_int = int(year)
                        except ValueError:
                            year_int = None
                    try:
                        justwatch_available, justwatch_providers = manager.check_movie_availability_details(
                            title,
                            year=year_int
                        )
                        justwatch_checked = bool(justwatch_available)
                    except JustWatchError as exc:
                        print(f"   -> JustWatch: errore verifica movie {title}: {exc}")
        summary.append({
            "id": req_id,
            "title": title or "N/D",
            "year": year,
            "media_type": media_type,
            "seasons": seasons,
            "status": status_code,
            "release_date": release_label,
            "is_available": status_code == 5,
            "is_unreleased": bool(release_dt and release_dt > now),
            "will_skip": will_skip,
            "age": age_label,
            "season_status": season_status,
            "justwatch_checked": justwatch_checked,
            "justwatch_available": justwatch_available,
            "justwatch_providers": justwatch_providers,
            "rules": {
                "query_terms": ",".join(request_rule.get("query_terms", [])),
                "filter_terms": ",".join(request_rule.get("filter_terms", [])),
                "exclude_terms": ",".join(request_rule.get("exclude_terms", [])),
                "enabled": request_rule.get("enabled", True)
            }
        })
    print(f"   -> Dashboard: Elaborazione completata, {len(summary)} richieste nel summary finale")
    return summary

def _log_justwatch_status():
    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    if not is_justwatch_available():
        print("   -> JustWatch: libreria non installata (pip install JustWatch)")
        return
    try:
        manager = _get_justwatch_manager(settings)
    except Exception as exc:
        print(f"   -> JustWatch: errore inizializzazione: {exc}")
        return
    if manager:
        print(f"   -> JustWatch: attivo (locale {locale})")
    else:
        print("   -> JustWatch: non disponibile (verifica database/config)")

def _ensure_db_backend():
    """Crea o restituisce l'istanza del backend database."""
    global _DB_BACKEND, _DB_BACKEND_SIGNATURE

    if _ACTIVE_CONFIG is None:
        raise StorageError("Configurazione non caricata")

    db_config = _ACTIVE_CONFIG.get("DATABASE", {})
    if not db_config.get("ENABLED"):
        raise StorageError("Database non abilitato nella configurazione")

    # Crea una signature per verificare se la configurazione è cambiata
    signature = (
        db_config.get("URL"),
        db_config.get("HOST"),
        db_config.get("PORT"),
        db_config.get("NAME"),
        db_config.get("USER")
    )

    # Se la configurazione è cambiata, ricrea il backend
    if _DB_BACKEND is None or _DB_BACKEND_SIGNATURE != signature:
        _DB_BACKEND = DatabaseStorage(db_config)
        _DB_BACKEND.ensure_ready()
        _DB_BACKEND_SIGNATURE = signature

    return _DB_BACKEND

def _db_enabled(settings):
    """Check if database is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _get_db_backend(settings):
    """Get or create database backend instance."""
    return _ensure_db_backend()

def _trakt_enabled(settings):
    """Check if Trakt is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _justwatch_enabled(settings):
    """Check if JustWatch is enabled in settings."""
    if not settings:
        return False
    return bool(settings.get("ENABLED"))

def _get_trakt_client(settings):
    """Get Trakt client instance from settings."""
    if not settings:
        return None
    return TraktClient(
        client_id=settings.get("CLIENT_ID", ""),
        access_token=settings.get("ACCESS_TOKEN", "")
    )

def _get_justwatch_manager(settings):
    """Get JustWatch manager instance from settings."""
    global _JUSTWATCH_MANAGER, _JUSTWATCH_SIGNATURE
    if not settings:
        return None
    if not _justwatch_enabled(settings):
        return None
    if not is_justwatch_available():
        return None
    db_settings = _ACTIVE_CONFIG.get("DATABASE") if _ACTIVE_CONFIG else None
    if not _db_enabled(db_settings):
        return None
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    signature = f"{locale}"
    if _JUSTWATCH_MANAGER is None or _JUSTWATCH_SIGNATURE != signature:
        try:
            _JUSTWATCH_MANAGER = JustWatchManager(_ensure_db_backend(), locale=locale)
            _JUSTWATCH_SIGNATURE = signature
        except JustWatchError:
            return None
    return _JUSTWATCH_MANAGER

def _active_trakt_settings():
    """Get active Trakt settings from global config."""
    if _ACTIVE_CONFIG is None:
        return {}
    return _ACTIVE_CONFIG.get("TRAKT", {})

def _active_justwatch_settings():
    """Get active JustWatch settings from global config."""
    if _ACTIVE_CONFIG is None:
        return {}
    return _ACTIVE_CONFIG.get("JUSTWATCH", {})

def _prowlarr_configured(config):
    """Check if Prowlarr is configured."""
    return bool(config.get("PROWLARR_URL") and config.get("PROWLARR_API_KEY"))

def _jackett_configured(config):
    """Check if Jackett is configured."""
    return bool(config.get("JACKETT_URL") and config.get("JACKETT_API_KEY"))

def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _strip_xml_tag(tag):
    if not tag:
        return ""
    return tag.split("}")[-1].lower()

def _extract_first_text(element, tag_names):
    for node in element.iter():
        if _strip_xml_tag(node.tag) in tag_names and node.text:
            text = node.text.strip()
            if text:
                return text
    return ""

def _extract_link_value(item):
    for node in item:
        if _strip_xml_tag(node.tag) != "link":
            continue
        href = node.attrib.get("href") if hasattr(node, "attrib") else None
        rel = node.attrib.get("rel") if hasattr(node, "attrib") else None
        if href and (not rel or rel == "alternate"):
            return href
        if node.text:
            return node.text.strip()
    return ""

def _inspect_rss_content(xml_bytes, sample_limit=5):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    items = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        items = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        items = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    results = []
    fields = set()
    for item in items[:sample_limit]:
        item_fields = {_strip_xml_tag(child.tag) for child in item}
        fields.update(item_fields)
        results.append({
            "title": _extract_first_text(item, {"title"}),
            "link": _extract_link_value(item) or _extract_first_text(item, {"link"}),
            "guid": _extract_first_text(item, {"guid", "id"}),
            "published": _extract_first_text(item, {"pubdate", "published", "updated", "date"}),
            "author": _extract_first_text(item, {"author", "creator"})
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "item_count": len(items),
        "fields": sorted(fields),
        "items": results
    }

def _parse_epoch_value(value):
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10**14:
        number = number / 1_000_000
    elif number > 10**11:
        number = number / 1_000
    return datetime.fromtimestamp(number, tz=timezone.utc)

def _parse_rss_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_epoch_value(text)
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        dt = None
    if dt is None:
        return _parse_date_value(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _extract_rss_categories(item):
    categories = []
    for node in item.iter():
        if _strip_xml_tag(node.tag) == "category" and node.text:
            value = node.text.strip()
            if value:
                categories.append(value)
    return categories

def _parse_rss_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    entries = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        entries = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        entries = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_link_value(channel) or _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    items = []
    for entry in entries:
        title = _extract_first_text(entry, {"title"})
        link = _extract_link_value(entry) or _extract_first_text(entry, {"link"})
        guid = _extract_first_text(entry, {"guid", "id"})
        if not link and guid:
            link = guid
        author = _extract_first_text(entry, {"author", "creator", "name"})
        summary = _extract_first_text(entry, {"summary", "description"})
        content = _extract_first_text(entry, {"content", "encoded"})
        if not summary and content:
            summary = content
        published_text = _extract_first_text(entry, {"pubdate", "published", "updated", "date"})
        updated_text = _extract_first_text(entry, {"updated", "modified"})
        published_at = _parse_rss_date(published_text)
        updated_at = _parse_rss_date(updated_text) or _parse_rss_date(published_text)
        categories = _extract_rss_categories(entry)
        raw_xml = ET.tostring(entry, encoding="unicode")
        items.append({
            "title": title or None,
            "link": link or None,
            "guid": guid or None,
            "author": author or None,
            "summary": summary or None,
            "content": content or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "feed_type": feed_type,
                "raw": raw_xml
            }
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "items": items
    }

def _extract_json_link(item):
    for key in ("canonical", "alternate"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("href"):
                    return entry["href"]
        elif isinstance(value, dict) and value.get("href"):
            return value["href"]
    origin = item.get("origin")
    if isinstance(origin, dict):
        if origin.get("htmlUrl"):
            return origin["htmlUrl"]
    return ""

def _extract_json_summary(item):
    summary = item.get("summary")
    if isinstance(summary, dict):
        return summary.get("content") or ""
    if isinstance(summary, str):
        return summary
    return ""

def _extract_json_source(origin):
    if not isinstance(origin, dict):
        return "", "", ""
    source_title = origin.get("title") or ""
    source_url = origin.get("htmlUrl") or ""
    stream_id = origin.get("streamId") or ""
    if not source_url and isinstance(stream_id, str) and stream_id.startswith("feed/"):
        source_url = stream_id[5:]
    return source_title, source_url, stream_id

def _parse_json_import(payload):
    items = []
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("items", "entries", "results", "data"):
            entry = payload.get(key)
            if isinstance(entry, list):
                candidates = entry
                break
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
        source_title, source_url, stream_id = _extract_json_source(origin)
        summary = _extract_json_summary(entry)
        link = _extract_json_link(entry)
        published_at = _parse_epoch_value(entry.get("published"))
        updated_at = _parse_epoch_value(entry.get("updated")) or _parse_epoch_value(entry.get("crawlTimeMsec"))
        if updated_at is None:
            updated_at = _parse_epoch_value(entry.get("timestampUsec"))
        categories = entry.get("categories")
        if not isinstance(categories, list):
            categories = []
        items.append({
            "source_name": source_title or None,
            "source_url": source_url or None,
            "source_tags": [],
            "title": entry.get("title") or None,
            "link": link or None,
            "guid": entry.get("id") or None,
            "author": entry.get("author") or None,
            "summary": summary or None,
            "content": summary or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "origin": origin,
                "stream_id": stream_id,
                "raw": entry
            }
        })
    return items

def _manual_result_key(result):
    return result.get("magnet") or result.get("torrent") or f"{result.get('title')}|{result.get('size_gb')}"

def _extract_year_from_title(title):
    if not title:
        return None
    match = re.search(r"(19|20)\d{2}", str(title))
    if not match:
        return None
    return match.group(0)

def _extract_season_hint_from_title(title):
    if not title:
        return None, None
    text = str(title)
    range_patterns = [
        r"[Ss](\d{1,2})\s*[-–]\s*[Ss]?(\d{1,2})",
        r"Season\s*(\d{1,2})\s*[-–]\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})\s*[-–]\s*(\d{1,2})"
    ]
    for pattern in range_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = _try_parse_int(match.group(1))
            end = _try_parse_int(match.group(2))
            if start is not None and end is not None:
                return None, f"S{start:02d}-S{end:02d}"
    single_patterns = [
        r"(?:^|\b)[Ss](\d{1,2})(?!\d)",
        r"Season\s*(\d{1,2})",
        r"Stagione\s*(\d{1,2})"
    ]
    for pattern in single_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            season = _try_parse_int(match.group(1))
            if season is not None:
                return season, f"S{season:02d}"
    return None, None

def _normalize_manual_result(raw):
    title = raw.get("title") or ""
    if not title:
        return None
    size_bytes = raw.get("size") or 0
    size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0
    seeders = _coerce_int(raw.get("seeders"), 0)
    leechers = _coerce_int(raw.get("leechers") or raw.get("Leechers"), 0)
    indexer = raw.get("indexer") or "N/A"
    magnet = raw.get("magnet") or raw.get("magnetUri") or raw.get("magnetUrl")
    guid = raw.get("guid")
    if not magnet and isinstance(guid, str) and guid.startswith("magnet:"):
        magnet = guid
    torrent = raw.get("downloadUrl")
    web = raw.get("infoUrl") or raw.get("indexerUrl") or raw.get("details")
    season_num, episode_num, episode_code, episode_sort = _extract_episode_from_title(title)
    season_label = None
    if season_num is None:
        season_num, season_label = _extract_season_hint_from_title(title)
    if season_num is not None and season_label is None:
        season_label = f"S{season_num:02d}"
    resolution_bucket = _detect_resolution_bucket(title.lower())
    year = _extract_year_from_title(title)
    return {
        "title": title,
        "size_gb": size_gb,
        "seeders": seeders,
        "leechers": leechers,
        "indexer": indexer,
        "magnet": magnet,
        "torrent": torrent,
        "web": web,
        "resolution": resolution_bucket,
        "resolution_bucket": resolution_bucket,
        "season_number": season_num,
        "season_label": season_label,
        "episode_code": episode_code,
        "episode_sort": episode_sort,
        "episode_number": episode_num,
        "normalized_title": sanitize_title(title.lower()),
        "year": year
    }

def _load_emby_library_title_index():
    try:
        backend = _ensure_db_backend()
    except Exception:
        return set()
    try:
        entries = backend.get_probe_queue()
    except Exception:
        entries = []
    try:
        history_entries = backend.get_probe_history(limit=5000)
    except Exception:
        history_entries = []
    titles = set()
    for entry in entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    for entry in history_entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    return titles

def _should_use_prowlarr(config):
    """Determine if Prowlarr should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_prowlarr_rule = rules.get("use_prowlarr", True)
    return _prowlarr_configured(config) and use_prowlarr_rule

def _should_use_jackett(config):
    """Determine if Jackett should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_jackett_rule = rules.get("use_jackett", False)
    return _jackett_configured(config) and use_jackett_rule

def _search_rules(config):
    """Get search rules from config."""
    return config.get("SEARCH_RULES", {})

def _load_cached_requests_overview():
    """Load cached requests overview from file or database."""
    try:
        backend = _ensure_db_backend()
        data, timestamp = backend.load_request_overview()
        return data or [], timestamp
    except:
        pass
    return [], None

def _save_cached_requests_overview(data):
    """Save cached requests overview to file or database."""
    try:
        backend = _ensure_db_backend()
        backend.save_request_overview(data)
    except:
        pass

def _update_app_settings_overrides(data):
    """Update application settings with overrides from data and save to database."""
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        return

    # Aggiorna la configurazione in memoria
    for key, value in data.items():
        if key in _ACTIVE_CONFIG:
            _ACTIVE_CONFIG[key] = value

    # Salva nel database
    try:
        backend = _ensure_db_backend()
        app_settings = backend.load_app_settings() or {}
        app_settings.update(data)
        backend.save_app_settings(app_settings)
    except StorageError:
        raise

def _refresh_request_overview_rules(config):
    """Refresh request overview rules from config."""
    return config.get("REQUEST_OVERVIEW_RULES", [])

def _parse_auto_task_payload(form, key, fallback):
    """Parse auto task payload from form data."""
    try:
        import json
        value = form.get(key, fallback)
        if isinstance(value, str):
            return json.loads(value)
        return value
    except:
        return fallback

def _build_emby_server_from_form(form, existing):
    """Build Emby server configuration from form data."""
    server = existing.copy() if existing else {}

    # Ensure new servers have an ID
    if not server.get("id"):
        server["id"] = str(uuid.uuid4())

    name = form.get("server_name") or form.get("emby_name")
    url = form.get("server_url") or form.get("emby_url")
    api_key = form.get("server_api_key") or form.get("emby_api_key")
    enabled = form.get("server_enabled") or form.get("emby_enabled")
    notes = form.get("server_notes")
    strm_task_id = form.get("server_strm_task_id")
    icon = form.get("server_icon")


    if name is not None:
        server["name"] = name
    if url is not None:
        server["url"] = url
    if api_key is not None:
        server["api_key"] = api_key
    if enabled is not None:
        server["enabled"] = str(enabled) not in ("0", "false", "False", "")
    if notes is not None:
        server["notes"] = notes
    if strm_task_id is not None:
        server["strm_task_id"] = strm_task_id
    if icon is not None:
        server["icon"] = icon if icon.strip() else "📺"
    else:
        # Set default icon if not provided
        if "icon" not in server:
            server["icon"] = "📺"

    return server

def save_results(summary):
    try:
        backend = _ensure_db_backend()
        backend.save_scan_result(summary)
    except StorageError as exc:
        print(f"   -> Non riesco a salvare i risultati nel database: {exc}")

def load_results_file():
    try:
        backend = _ensure_db_backend()
        return backend.load_last_result()
    except StorageError as exc:
        print(f"   -> Non riesco a leggere gli ultimi risultati dal database: {exc}")
        return None

def _merge_scan_summaries(previous, current):
    """Mantiene i risultati precedenti sostituendo soltanto quelli aggiornati dall'ultima ricerca."""
    if not current:
        return previous or {}
    merged = copy.deepcopy(current)
    new_items = []
    seen_keys = set()
    current_items = merged.get("items") or []
    current_generated = merged.get("generated_at")

    for item in current_items:
        normalized = copy.deepcopy(item)
        normalized["updated_at"] = current_generated
        normalized["is_stale"] = False
        key = (
            normalized.get("request_id"),
            normalized.get("season"),
            normalized.get("media_type")
        )
        seen_keys.add(key)
        new_items.append(normalized)

    stale_items = []
    if previous and isinstance(previous.get("items"), list):
        for item in previous["items"]:
            key = (
                item.get("request_id"),
                item.get("season"),
                item.get("media_type")
            )
            if key in seen_keys:
                continue
            stale = copy.deepcopy(item)
            stale["is_stale"] = True
            stale.setdefault("updated_at", previous.get("generated_at"))
            stale_items.append(stale)

    merged["items"] = new_items + stale_items
    merged["stale_count"] = len(stale_items)
    merged["previous_generated_at"] = previous.get("generated_at") if previous else None
    return merged

# Nota: _normalize_season_spec, _normalize_scan_targets, _serialize_target_map sono ora importate da utils.py


# Nota: ScanManager e AutoScheduler sono ora importate da tasks.py

# Crea l'istanza globale di ScanManager
scan_manager = ScanManager()

def _ensure_auto_scheduler():
    global _AUTO_SCHEDULER
    if _AUTO_SCHEDULER is None:
        _AUTO_SCHEDULER = AutoScheduler(scan_manager_instance=scan_manager)
        # Imposta i callback per evitare import circolari
        _AUTO_SCHEDULER.set_callbacks(
            summarize_func=_summarize_requests_for_dashboard,
            save_overview_func=_save_cached_requests_overview,
            process_requests_func=process_requests
        )
    return _AUTO_SCHEDULER

def _sync_auto_scheduler(config_ready):
    scheduler = _ensure_auto_scheduler()
    if not scheduler:
        return
    if config_ready and _ACTIVE_CONFIG:
        scheduler.update_config(_ACTIVE_CONFIG)
    else:
        scheduler.update_config(None)

def _load_app_settings_snapshot():
    try:
        backend = _ensure_db_backend()
        return backend.load_app_settings() or {}
    except StorageError:
        return {}


def _save_app_settings_snapshot(settings):
    try:
        backend = _ensure_db_backend()
        backend.save_app_settings(settings)
    except StorageError:
        return


def _load_emby_strm_guard_state():
    settings = _load_app_settings_snapshot()
    state = settings.get(EMBY_STRM_GUARD_KEY)
    return state if isinstance(state, dict) else {}


def _save_emby_strm_guard_state(state):
    settings = _load_app_settings_snapshot()
    settings[EMBY_STRM_GUARD_KEY] = state
    _save_app_settings_snapshot(settings)


def _get_emby_servers_from_config():
    config, _ = load_config()
    if not config:
        return []
    emby_config = config.get("EMBY") or {}
    return emby_config.get("SERVERS") or []


class EmbyStrmGuardManager:
    def __init__(self, cooldown_seconds=EMBY_STRM_GUARD_COOLDOWN_SECONDS, poll_seconds=EMBY_STRM_GUARD_POLL_SECONDS):
        self._cooldown = cooldown_seconds
        self._poll = poll_seconds
        self._lock = threading.Lock()
        self._state = {}
        self._stop_event = threading.Event()
        self._thread = None
        self._get_servers = None

    def configure(self, get_servers_func):
        self._get_servers = get_servers_func

    def load_state(self):
        self._state = _load_emby_strm_guard_state()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enable_for_servers(self, server_ids):
        now = self._iso(datetime.now(timezone.utc))
        changed = False
        with self._lock:
            for server_id in server_ids:
                if not server_id:
                    continue
                server_key = str(server_id)
                # Reset state for a fresh start when manually enabled
                entry = {
                    "enabled": True,
                    "status": "pending",
                    "last_enabled_at": now,
                    "last_progress": 0,
                    "last_execution_result": None,
                    "last_error": None,
                    "idle_since": None,
                    "last_stream_at": None,
                    "last_stop_at": None,
                    "last_start_attempt": None
                }
                self._state[server_key] = entry
                changed = True
        if changed:
            self._persist_state()
        return changed

    def _persist_state(self):
        with self._lock:
            snapshot = copy.deepcopy(self._state)
        _save_emby_strm_guard_state(snapshot)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                print(f"[EMBY_GUARD] Errore: {exc}")
            self._stop_event.wait(self._poll)

    def _tick(self):
        if not self._get_servers:
            return
        servers = self._get_servers() or []
        server_map = {
            str(server.get("id")): server
            for server in servers
            if server.get("id")
        }
        with self._lock:
            enabled_ids = [
                server_id
                for server_id, entry in self._state.items()
                if entry.get("enabled")
            ]
        if not enabled_ids:
            return
        changed = False
        for server_id in enabled_ids:
            server = server_map.get(server_id)
            with self._lock:
                entry = copy.deepcopy(self._state.get(server_id, {}))
            updated, entry_changed = self._evaluate_server(server_id, server, entry)
            if entry_changed:
                with self._lock:
                    self._state[server_id] = updated
                changed = True
        if changed:
            self._persist_state()

    def _evaluate_server(self, server_id, server, entry):
        now = datetime.now(timezone.utc)
        changed = False

        def set_value(key, value):
            nonlocal changed
            if entry.get(key) != value:
                entry[key] = value
                changed = True

        print(f"[STRM_GUARD DEBUG] Server {server_id}: evaluating...")

        if not server or not server.get("enabled", True):
            set_value("status", "disabled")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: server disabled")
            return entry, changed

        tasks, tasks_error = _fetch_emby_scheduled_tasks(server)
        if tasks_error:
            set_value("status", "tasks_error")
            set_value("last_error", str(tasks_error))
            print(f"[STRM_GUARD DEBUG] Server {server_id}: tasks_error={tasks_error}")
            return entry, changed

        task_id, task = self._select_strm_task(server, tasks)
        if not task_id:
            set_value("status", "task_missing")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: task_missing")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: task_id={task_id}, task={task}")

        streams, streams_error = _fetch_emby_active_sessions(server)
        if streams_error:
            set_value("status", "streams_error")
            set_value("last_error", str(streams_error))
            print(f"[STRM_GUARD DEBUG] Server {server_id}: streams_error={streams_error}")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: streams={len(streams) if streams else 0}")

        progress_value = 0.0
        if task:
            raw_progress = task.get("progress")
            try:
                progress_value = float(raw_progress)
            except (TypeError, ValueError):
                progress_value = 0.0
        is_running = bool(task and task.get("is_running"))
        set_value("last_progress", round(progress_value, 2))

        print(f"[STRM_GUARD DEBUG] Server {server_id}: is_running={is_running}, progress={progress_value}")

        # Check LastExecutionResult to determine if task completed successfully
        # Emby returns a dict: {'Status': 'Completed'|'Cancelled', 'EndTimeUtc': '...', ...}
        last_execution_result = task.get("last_execution_result") if task else None
        execution_status = None
        end_time = task.get("end_time") if task else None

        if isinstance(last_execution_result, dict):
            execution_status = last_execution_result.get("Status")
            if not end_time:
                end_time = last_execution_result.get("EndTimeUtc")

        is_cancelled = execution_status in ("Cancelled", "Canceled", "Aborted")
        is_completed = execution_status == "Completed"

        # Only consider completion if we have started the task at least once
        # This prevents detecting old executions as our completion
        has_started_task = bool(entry.get("last_start_attempt"))

        # Task completed successfully if:
        # 1. Not currently running
        # 2. Has completed status
        # 3. Was not cancelled
        # 4. We started the task (not from a previous manual run)
        task_completed = (
            not is_running
            and is_completed
            and not is_cancelled
            and has_started_task
        )

        if task_completed:
            set_value("status", "completed")
            set_value("enabled", False)
            set_value("completed_at", self._iso(now))
            set_value("last_execution_result", last_execution_result)
            print(f"[STRM_GUARD DEBUG] Server {server_id}: COMPLETED - disabling guard")
            return entry, changed

        print(f"[STRM_GUARD DEBUG] Server {server_id}: task_completed={task_completed}, has_started={has_started_task}")

        if streams:
            set_value("last_stream_at", self._iso(now))
            if entry.get("idle_since"):
                set_value("idle_since", None)
            if is_running:
                success, response = _stop_emby_task(server, task_id)
                if success:
                    set_value("status", "paused_streaming")
                    set_value("last_error", "")
                else:
                    set_value("status", "stop_failed")
                    set_value("last_error", str(response))
                set_value("last_stop_at", self._iso(now))
            else:
                set_value("status", "waiting_streams")
            return entry, changed

        idle_since = self._parse_ts(entry.get("idle_since"))
        if idle_since is None:
            set_value("idle_since", self._iso(now))
            idle_since = now
        idle_elapsed = (now - idle_since).total_seconds()
        had_streams = bool(entry.get("last_stream_at") or entry.get("last_stop_at"))

        if is_running:
            set_value("status", "running")
            return entry, changed

        if had_streams and idle_elapsed < self._cooldown:
            set_value("status", "cooldown")
            return entry, changed

        last_attempt = self._parse_ts(entry.get("last_start_attempt"))
        print(f"[STRM_GUARD DEBUG] Server {server_id}: last_attempt={last_attempt}, should_start={last_attempt is None or (now - last_attempt).total_seconds() >= 30}")

        if last_attempt is None or (now - last_attempt).total_seconds() >= 30:
            print(f"[STRM_GUARD DEBUG] Server {server_id}: Attempting to start STRM Extract task...")
            success, response = _execute_emby_action(server, "strm_extract")
            set_value("last_start_attempt", self._iso(now))
            if success:
                set_value("status", "running")
                set_value("last_error", "")
                print(f"[STRM_GUARD DEBUG] Server {server_id}: Task started successfully")
            else:
                set_value("status", "start_failed")
                set_value("last_error", str(response))
                print(f"[STRM_GUARD DEBUG] Server {server_id}: Task start FAILED: {response}")
        else:
            set_value("status", "starting")
            print(f"[STRM_GUARD DEBUG] Server {server_id}: Waiting 30s cooldown before retry")
        return entry, changed

    @staticmethod
    def _parse_ts(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _iso(value):
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return value

    @staticmethod
    def _select_strm_task(server, tasks):
        if not tasks:
            return None, None
        server_task_id = str(server.get("strm_task_id") or "").strip()
        if server_task_id:
            for task in tasks:
                if str(task.get("id")) == server_task_id:
                    return server_task_id, task
        for task in tasks:
            if task.get("key") == "StrmExtractTask" and task.get("id"):
                return str(task.get("id")), task
        for task in tasks:
            name = str(task.get("name") or "").lower()
            if "strm" in name and task.get("id"):
                return str(task.get("id")), task
        return None, None


def _ensure_strm_guard_manager():
    global _EMBY_STRM_GUARD
    if _EMBY_STRM_GUARD is None:
        _EMBY_STRM_GUARD = EmbyStrmGuardManager()
        _EMBY_STRM_GUARD.configure(_get_emby_servers_from_config)
        _EMBY_STRM_GUARD.load_state()
        _EMBY_STRM_GUARD.start()
    else:
        _EMBY_STRM_GUARD.configure(_get_emby_servers_from_config)
    return _EMBY_STRM_GUARD


def _configure_security(app: Flask):
    """Configure session and CSRF settings."""
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "octohub"
    try:
        timeout_minutes = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "60"))
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=timeout_minutes)
    except ValueError:
        pass
    try:
        csrf_time_limit = int(os.environ.get("CSRF_TIME_LIMIT_SECONDS", "3600"))
        app.config["WTF_CSRF_TIME_LIMIT"] = csrf_time_limit
    except ValueError:
        pass
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    secure_env = os.environ.get("SESSION_COOKIE_SECURE")
    if secure_env is not None:
        app.config["SESSION_COOKIE_SECURE"] = secure_env.lower() in {"1", "true", "yes"}
        app.config["SESSION_COOKIE_SECURE_AUTO"] = False
    else:
        # Auto mode: allow HTTP locally, force secure cookies on HTTPS.
        app.config["SESSION_COOKIE_SECURE"] = False
        app.config["SESSION_COOKIE_SECURE_AUTO"] = True
    csrf.init_app(app)


def _sanitize_audit_payload(req: Any) -> str:
    """Return a sanitized payload string for audit logging."""
    try:
        payload = req.get_json(silent=True)
        if payload is None:
            payload = req.form.to_dict(flat=True)
        if not isinstance(payload, dict):
            return ""
        redacted = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "secret", "token", "api_key", "apikey")):
                redacted[key] = "***"
            else:
                redacted[key] = value
        return json.dumps(redacted, ensure_ascii=True)[:1000]
    except Exception:
        return ""


def role_required(*roles):
    """Require one of the specified roles."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return abort(401)
            user_role = current_user.get_role() if hasattr(current_user, "get_role") else "user"
            if user_role not in roles:
                return abort(403)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def run_config_server():
    """Avvia un server Flask per la configurazione iniziale."""
    app = Flask(__name__)
    _configure_security(app)

    @app.route('/')
    def index():
        return render_template('config_page.html')

    @app.route('/save', methods=['POST'])
    def save_config_route():
        config_data = {
            "JELLYSEERR_URL": request.form.get('jellyseerr_url'),
            "JELLYSEERR_API_KEY": request.form.get('jellyseerr_api_key'),
            "PROWLARR_URL": request.form.get('prowlarr_url'),
            "PROWLARR_API_KEY": request.form.get('prowlarr_api_key'),
            "JACKETT_URL": request.form.get('jackett_url'),
            "JACKETT_API_KEY": request.form.get('jackett_api_key'),
            "QBITTORRENT_URL": request.form.get('qbittorrent_url'),
            "QBITTORRENT_USERNAME": request.form.get('qbittorrent_username'),
            "QBITTORRENT_PASSWORD": request.form.get('qbittorrent_password'),
        }
        db_settings = {
            "ENABLED": True,
            "HOST": request.form.get('db_host') or "localhost",
            "PORT": int(request.form.get('db_port') or 5432),
            "NAME": request.form.get('db_name') or "jellychecker",
            "USER": request.form.get('db_user') or "",
            "PASSWORD": request.form.get('db_password') or "",
            "DRIVER": request.form.get('db_driver') or "postgresql+psycopg2",
            "URL": request.form.get('db_url') or "",
            "PARAMS": request.form.get('db_params') or ""
        }
        config_data["DATABASE"] = cast(Any, _merge_database_settings(db_settings))
        trakt_settings = {
            "ENABLED": bool(request.form.get('trakt_enabled')),
            "CLIENT_ID": request.form.get('trakt_client_id') or "",
            "ACCESS_TOKEN": request.form.get('trakt_access_token') or ""
        }
        config_data["TRAKT"] = cast(Any, _merge_trakt_settings(trakt_settings))
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        
        # Questa funzione non è affidabile su tutti i server, la rimuoviamo
        # per un approccio di riavvio più robusto.
        # shutdown_hook = request.environ.get('werkzeug.server.shutdown')
        return "<h1>Configurazione salvata!</h1><p>Puoi chiudere questa finestra. Lo script si riavvierà nel terminale.</p>"

    print(f"File di configurazione '{CONFIG_FILE}' non trovato o non valido.")
    print("Avvio del server di configurazione su http://127.0.0.1:5000")
    print("Apri il browser a questo indirizzo per configurare lo script.")
    app.run(host='127.0.0.1', port=5000)

def create_dashboard_app():
    """Crea e configura l'applicazione Flask dashboard."""
    app = Flask(__name__)
    _configure_security(app)

    # Initialize authentication system
    init_auth(app)

    @app.errorhandler(CSRFError)
    def _handle_csrf_error(error):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "Token CSRF non valido o sessione scaduta."}), 400
        return error.description, 400

    _ensure_strm_guard_manager()

    # Configure Emby Probe Manager
    get_probe_manager().configure(_ensure_db_backend)

    @app.before_request
    def _ensure_cookie_security():
        if not app.config.get("SESSION_COOKIE_SECURE_AUTO"):
            return
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        app.config["SESSION_COOKIE_SECURE"] = proto == "https"

    @app.before_request
    def _refresh_session_cookie():
        if not app.config.get("SESSION_COOKIE_SECURE_AUTO"):
            return
        if current_user.is_authenticated or session:
            # Force cookie refresh so Secure flag matches current scheme.
            session.modified = True

    @app.before_request
    def _audit_state_changes():
        if request.method in ("POST", "PUT", "DELETE") and request.path not in ("/login", "/logout", "/webhook/emby"):
            if current_user.is_authenticated:
                detail = _sanitize_audit_payload(request)
                log_audit_event(current_user, f"{request.method} {request.path}", detail, request)

    admin_write_paths = {
        "/emby/save-server",
        "/api/emby/server-order",
        "/api/emby/associations",
        "/api/emby/group-order",
        "/api/ui/tab-order",
        "/api/emby/probe/queue",
        "/api/emby/probe/history",
        "/api/emby/probe/blacklist",
        "/update-config",
        "/update-rules",
        "/update-request-rules",
        "/update-scheduler",
        "/test-connections",
    }

    @app.before_request
    def _enforce_role_access():
        if request.path.startswith("/static/"):
            return
        if request.path in ("/login", "/logout", "/webhook/emby"):
            return
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        if not current_user.is_authenticated:
            return
        role = current_user.get_role() if hasattr(current_user, "get_role") else "user"
        if role == "viewer":
            return abort(403)
        if request.path in admin_write_paths and role != "admin":
            return abort(403)

    def _get_total_blacklist_count():
        """Calculate total number of items in probe blacklist (3+ errors) across all servers."""
        try:
            config, is_valid = load_config()
            if not is_valid or not config:
                return 0

            emby_config = config.get("EMBY") or {}
            servers = emby_config.get("SERVERS") or []
            total_count = 0

            db = _ensure_db_backend()
            for server in servers:
                if not server.get("enabled"):
                    continue
                server_id = server.get("id")
                if not server_id:
                    continue
                # Only count items with 3+ errors
                blacklist = db.get_probe_blacklist(server_id, min_retry_count=3)
                total_count += len(blacklist)

            return total_count
        except (StorageError, Exception):
            return 0

    # --- AUTHENTICATION ROUTES ---

    @app.route('/login', methods=['GET', 'POST'])
    def auth_login():
        """Login page and handler."""
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            if not username or not password:
                flash('Username e password sono obbligatori.', 'error')
                return render_template('login.html')

            user = get_user_by_username(username)

            if user is not None and user.is_active and user.check_password(password):
                session.permanent = True
                login_user(user)
                user.update_last_login()
                log_audit_event(user, "login", "success", request)
                flash(f'Benvenuto, {user.username}!', 'success')

                # Redirect to next page or dashboard
                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):
                    return redirect(next_page)
                return redirect(url_for('dashboard'))
            else:
                flash('Username o password non validi.', 'error')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def auth_logout():
        """Logout handler."""
        if current_user.is_authenticated:
            log_audit_event(current_user, "logout", "success", request)
        logout_user()
        flash('Disconnessione effettuata.', 'success')
        return redirect(url_for('auth_login'))

    # --- MAIN ROUTES ---

    @app.route('/')
    @login_required
    def dashboard():
        config, is_valid = load_config()
        status = scan_manager.get_status()
        results = status.get('last_summary') or load_results_file()
        message = request.args.get('msg')
        qb_available = bool(config and config.get('QBITTORRENT_URL') and config.get('QBITTORRENT_USERNAME') and config.get('QBITTORRENT_PASSWORD'))
        if is_valid:
            requests_overview, overview_stamp = _load_cached_requests_overview()
        else:
            requests_overview, overview_stamp = ([], None)

        # Filter results to remove fully available content (status 5 = available)
        available_ids = {req.get('request_id') for req in requests_overview if req.get("status") == 5}

        # Filter requests overview to remove available content
        requests_overview = [req for req in requests_overview if req.get("status") != 5]

        # Filter results items to remove available content
        if results and results.get('items'):
            results['items'] = [item for item in results['items'] if item.get('request_id') not in available_ids]
        tv_requests = [req for req in requests_overview if (req.get("media_type") or "").lower() == "tv"]
        movie_requests = [req for req in requests_overview if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")]
        variant_estimate = _estimate_variant_summary((config or {}).get('SEARCH_RULES'))
        auto_tasks = (config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks())
        total_blacklist_count = _get_total_blacklist_count()
        return render_template(
            'dashboard.html',
            has_config=is_valid,
            config=config,
            search_rules=(config or {}).get('SEARCH_RULES', DEFAULT_CONFIG['SEARCH_RULES']),
            tv_sort_options=TV_SORT_OPTIONS,
            movie_sort_options=MOVIE_SORT_OPTIONS,
            results=results,
            status=status,
            qb_available=qb_available,
            message=message,
            requests_overview=requests_overview,
            tv_requests=tv_requests,
            movie_requests=movie_requests,
            variant_estimate=variant_estimate,
            requests_updated_at=overview_stamp,
            auto_tasks=auto_tasks,
            active_page="jellyseerr",
            total_blacklist_count=total_blacklist_count
        )

    @app.route('/emby')
    @login_required
    def emby_dashboard():
        config, is_valid = load_config()
        emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
        raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
        emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
        total_blacklist_count = _get_total_blacklist_count()
        return render_template(
            'emby_dashboard.html',
            has_config=is_valid,
            active_page="emby",
            emby_config=emby_config,
            emby_servers=emby_servers,
            emby_categories=EMBY_CATEGORY_OPTIONS,
            message=None,
            total_blacklist_count=total_blacklist_count
        )

    @app.route('/emby/probe')
    @login_required
    def emby_probe():
        config, is_valid = load_config()
        if not is_valid or not config:
            flash("Configurazione non valida")
            return redirect(url_for('emby_dashboard'))
        emby_config = config.get("EMBY") or _default_emby_settings()
        raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
        emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
        total_blacklist_count = _get_total_blacklist_count()
        return render_template(
            'emby_probe.html',
            has_config=is_valid,
            active_page="emby_probe",
            emby_servers=emby_servers,
            message=None,
            total_blacklist_count=total_blacklist_count
        )

    @app.route('/emby/streams', methods=['GET'])
    @login_required
    def emby_streams():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        payload = {}
        for server in servers:
            server_id = server.get("id")
            if not server_id:
                continue
            if not server.get("enabled"):
                payload[server_id] = {"ok": False, "error": "Server disabilitato", "streams": []}
                continue
            streams, error = _fetch_emby_active_sessions(server)
            payload[server_id] = {
                "ok": error is None,
                "streams": streams,
                "error": error
            }
        return jsonify({"success": True, "servers": payload})

    @csrf.exempt
    @app.route('/webhook/emby', methods=['POST'])
    def emby_webhook():
        """
        Webhook endpoint for Emby playback events.
        Receives real-time notifications when streams start/stop/pause.

        Configure in Emby: Server Settings > Webhooks > Add Webhook
        URL: http://your-server:port/webhook/emby

        Optional security: Set environment variable WEBHOOK_SECRET
        and add custom header: X-Webhook-Secret: your-secret-value
        """
        try:
            # Optional security check
            webhook_secret = os.environ.get("WEBHOOK_SECRET")
            if webhook_secret:
                received_secret = request.headers.get("X-Webhook-Secret")
                if received_secret != webhook_secret:
                    print("[WEBHOOK] Secret non valido, rifiuto richiesta")
                    return jsonify({"success": False, "error": "Unauthorized"}), 401

            # Optional IP whitelist
            ip_whitelist = os.environ.get("WEBHOOK_IP_WHITELIST")
            if ip_whitelist:
                allowed_ips = {ip.strip() for ip in ip_whitelist.split(",") if ip.strip()}
                request_ip = (
                    request.headers.get("X-Real-IP")
                    or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or request.remote_addr
                )
                if request_ip not in allowed_ips:
                    print(f"[WEBHOOK] IP non autorizzato: {request_ip}")
                    return jsonify({"success": False, "error": "Forbidden"}), 403

            data = request.get_json(silent=True) or {}

            # Extract event info
            event = data.get("Event")
            server_name = data.get("Server", {}).get("Name", "")
            server_id = data.get("Server", {}).get("Id", "")
            session = data.get("Session", {})

            print(f"[WEBHOOK] Ricevuto evento: {event} da server: {server_name} ({server_id})")

            # Map Emby server ID to our config server ID
            # Try to find matching server in config
            config, is_valid = load_config()
            if not is_valid or not config:
                print("[WEBHOOK] Config non valida, ignoro webhook")
                return jsonify({"success": True, "message": "Config non valida"}), 200

            emby_config = config.get("EMBY") or {}
            servers = emby_config.get("SERVERS") or []

            # Find server by Emby ID or name
            matched_server_id = None
            for srv in servers:
                # Try matching by server ID first, then by name
                if srv.get("emby_server_id") == server_id or srv.get("name") == server_name:
                    matched_server_id = srv.get("id")
                    break

            if not matched_server_id:
                # Fallback: use first enabled server if only one exists
                enabled_servers = [s for s in servers if s.get("enabled")]
                if len(enabled_servers) == 1:
                    matched_server_id = enabled_servers[0].get("id")
                    print(f"[WEBHOOK] Usando server di default: {matched_server_id}")
                else:
                    print(f"[WEBHOOK] Server non trovato per ID={server_id} name={server_name}")
                    return jsonify({"success": True, "message": "Server non configurato"}), 200

            streams_mgr = get_streams_manager()
            session_id = session.get("Id")

            # Handle different events
            if event == "playback.start":
                print(f"[WEBHOOK] Stream iniziato: {session_id}")
                streams_mgr.add_stream(matched_server_id, session)

            elif event == "playback.stop":
                print(f"[WEBHOOK] Stream terminato: {session_id}")
                if session_id:
                    streams_mgr.remove_stream(matched_server_id, session_id)

            elif event == "playback.pause":
                print(f"[WEBHOOK] Stream in pausa: {session_id}")
                if session_id:
                    streams_mgr.update_stream(matched_server_id, session_id, {
                        "PlayState": session.get("PlayState", {})
                    })

            elif event == "playback.unpause":
                print(f"[WEBHOOK] Stream ripreso: {session_id}")
                if session_id:
                    streams_mgr.update_stream(matched_server_id, session_id, {
                        "PlayState": session.get("PlayState", {})
                    })

            return jsonify({"success": True}), 200

        except Exception as e:
            print(f"[WEBHOOK] Errore: {e}")
            import traceback
            traceback.print_exc()
            # Return 200 anyway to avoid Emby retrying
            return jsonify({"success": False, "error": str(e)}), 200

    @app.route('/emby/status-stream')
    def emby_status_stream():
        """
        SSE endpoint - no @login_required because EventSource doesn't always send session cookies.
        We check authentication at the start instead.
        """
        if not current_user.is_authenticated:
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        def event_stream():
            print("[SSE] Client connesso")
            try:
                while True:
                    try:
                        config, is_valid = load_config()
                        if not is_valid or not config:
                            payload = {"success": False, "message": "Config non valida"}
                        else:
                            emby_config = config.get("EMBY") or {}
                            servers = emby_config.get("SERVERS") or []
                            data = {}
                            for server in servers:
                                server_id = server.get("id")
                                if not server_id:
                                    continue
                                if not server.get("enabled"):
                                    data[server_id] = {
                                        "status": {"ok": False, "error": "Server disabilitato"},
                                        "running_tasks": [],
                                        "tasks_error": None,
                                        "streams": [],
                                        "streams_error": None,
                                        "probe_status": None
                                    }
                                    continue
                                status = _fetch_emby_status(server)
                                tasks, error = _fetch_emby_scheduled_tasks(server)
                                running = []
                                for task in tasks:
                                    if task.get("is_running"):
                                        running.append(task)

                                # Get streams from cache and refresh periodically when webhooks are missing.
                                streams_mgr = get_streams_manager()
                                streams_error = None
                                try:
                                    refresh_age = int(os.environ.get("STREAMS_REFRESH_SECONDS", "5"))
                                except ValueError:
                                    refresh_age = 5
                                if streams_mgr.is_stale(server_id, refresh_age):
                                    streams_api, streams_error = _fetch_emby_active_sessions(server)
                                    if streams_error is None:
                                        streams_mgr.refresh_from_api(server_id, streams_api)
                                        streams = streams_api
                                    else:
                                        streams = streams_mgr.get_streams(server_id)
                                else:
                                    streams = streams_mgr.get_streams(server_id)

                                probe_status = get_probe_manager().get_status(server_id)
                                data[server_id] = {
                                    "status": status,
                                    "running_tasks": running,
                                    "tasks_error": error,
                                    "streams": streams,
                                    "streams_error": streams_error,
                                    "probe_status": probe_status
                                }
                            payload = {"success": True, "servers": data}
                        msg = f"data: {json.dumps(payload, cls=DateTimeEncoder)}\n\n"
                        yield msg
                        time.sleep(2)  # Reduced from 3s to 2s for faster UI updates
                    except Exception as e:
                        print(f"[SSE] Errore nel loop: {e}")
                        import traceback
                        traceback.print_exc()
                        time.sleep(5)
            except GeneratorExit:
                print("[SSE] Client disconnesso")
            except Exception as e:
                print(f"[SSE] Errore fatale: {e}")
                import traceback
                traceback.print_exc()

        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
        return Response(stream_with_context(event_stream()), mimetype='text/event-stream', headers=headers)

    @app.route('/emby/stop-task', methods=['POST'])
    @login_required
    def emby_stop_task():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        task_id = payload.get("task_id")
        print(f"[DEBUG] Stop task richiesto: server_id={server_id}, task_id={task_id}")
        if not server_id or not task_id:
            return jsonify({"success": False, "message": "server_id o task_id mancante"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target = next((s for s in servers if s.get("id") == server_id), None)
        if target is None:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        print(f"[DEBUG] Chiamata _stop_emby_task con task_id={task_id}")
        success, response = _stop_emby_task(target, str(task_id))
        print(f"[DEBUG] _stop_emby_task ritornato: success={success}, response={response}")
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "message": f"Errore stop task: {response}"}), 500

    @app.route('/emby/server-status/<server_id>', methods=['GET'])
    @login_required
    def emby_server_status(server_id):
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target = next((s for s in servers if s.get("id") == server_id), None)
        if target is None:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        status = _fetch_emby_status(target)
        tasks, error = _fetch_emby_scheduled_tasks(target)
        streams, streams_error = _fetch_emby_active_sessions(target)
        running = []
        for task in tasks:
            if task.get("is_running"):
                running.append(task)
        return jsonify({
            "success": True,
            "status": status,
            "running_tasks": running,
            "tasks_error": error,
            "streams": streams,
            "streams_error": streams_error
        })

    @app.route('/emby/save-server', methods=['POST'])
    @login_required
    def emby_save_server():
        raw_config = read_raw_config() or {}
        emby_section = raw_config.get("EMBY") or {}
        servers = copy.deepcopy(emby_section.get("SERVERS") or [])
        server_id = request.form.get('server_id')
        existing_index = None
        existing_server = None
        for idx, server in enumerate(servers):
            if server.get("id") == server_id:
                existing_index = idx
                existing_server = server
                break
        updated_server = _build_emby_server_from_form(request.form, existing_server)
        if existing_index is not None:
            servers[existing_index] = updated_server
        else:
            servers.append(updated_server)
        raw_config["EMBY"] = {"SERVERS": servers}
        config_write_file(raw_config)
        load_config()
        flash(f"Server {updated_server.get('name')} salvato.")
        return redirect(url_for('emby_dashboard'))

    @app.route('/emby/action', methods=['POST'])
    @login_required
    def emby_action():
        raw_config = read_raw_config() or {}
        emby_section = raw_config.get("EMBY") or {}
        servers = copy.deepcopy(emby_section.get("SERVERS") or [])
        server_id = request.form.get('server_id')
        action = request.form.get('action')
        if not server_id or not action:
            flash("Azione non valida per Emby.")
            return redirect(url_for('emby_dashboard'))
        server_index = None
        server_entry = None
        for idx, server in enumerate(servers):
            if server.get("id") == server_id:
                server_index = idx
                server_entry = server
                break
        if server_entry is None:
            flash("Server Emby non trovato.")
            return redirect(url_for('emby_dashboard'))
        if server_index is None:
            flash("Indice server Emby non valido.")
            return redirect(url_for('emby_dashboard'))
        server_index_int = cast(int, server_index)
        success, response = _execute_emby_action(server_entry, action)
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        action_label = EMBY_ACTIONS.get(action, {}).get("label") or action
        server_entry["last_action"] = {
            "name": action_label,
            "timestamp": timestamp,
            "result": "OK" if success else str(response)
        }
        servers[server_index_int] = _normalize_emby_server(server_entry)
        raw_config["EMBY"] = {"SERVERS": servers}
        config_write_file(raw_config)
        load_config()
        if success:
            flash(f"{action_label} inviata a {server_entry.get('name')}.")
        else:
            flash(f"{action_label} non riuscita su {server_entry.get('name')}: {response}")
        return redirect(url_for('emby_dashboard'))

    @app.route('/emby/action-all', methods=['POST'])
    @login_required
    def emby_action_all():
        raw_config = read_raw_config() or {}
        emby_section = raw_config.get("EMBY") or {}
        servers = copy.deepcopy(emby_section.get("SERVERS") or [])
        action = request.form.get('action')
        if not action:
            flash("Azione non valida per Emby.")
            return redirect(url_for('emby_dashboard'))
        action_label = EMBY_ACTIONS.get(action, {}).get("label") or action
        success_count = 0
        failure_count = 0
        for idx, server_entry in enumerate(servers):
            if not server_entry.get("enabled"):
                continue
            success, response = _execute_emby_action(server_entry, action)
            timestamp = datetime.now(timezone.utc).astimezone().isoformat()
            server_entry["last_action"] = {
                "name": action_label,
                "timestamp": timestamp,
                "result": "OK" if success else str(response)
            }
            servers[idx] = _normalize_emby_server(server_entry)
            if success:
                success_count += 1
            else:
                failure_count += 1
        raw_config["EMBY"] = {"SERVERS": servers}
        config_write_file(raw_config)
        load_config()
        if failure_count == 0 and success_count > 0:
            flash(f"{action_label} inviata a {success_count} server.")
        elif success_count == 0:
            flash(f"{action_label} fallita su tutti i server.")
        else:
            flash(f"{action_label} inviata a {success_count} server, fallita su {failure_count}.")
        return redirect(url_for('emby_dashboard'))

    @app.route('/emby/strm-guard/start', methods=['POST'])
    @login_required
    def emby_strm_guard_start():
        server_id = request.form.get('server_id')
        if not server_id:
            flash('Server non valido per STRM Extract automatico.')
            return redirect(url_for('emby_dashboard'))
        guard = _ensure_strm_guard_manager()
        guard.enable_for_servers([server_id])
        flash('STRM Extract verrà avviato quando il server sarà libero e senza stream attivi.')
        return redirect(url_for('emby_dashboard'))

    @app.route('/emby/strm-guard/start-all', methods=['POST'])
    @login_required
    def emby_strm_guard_start_all():
        servers = _get_emby_servers_from_config()
        server_ids = [server.get('id') for server in servers if server.get('id') and server.get('enabled', True)]
        if not server_ids:
            flash('Nessun server Emby abilitato per STRM Extract automatico.')
            return redirect(url_for('emby_dashboard'))
        guard = _ensure_strm_guard_manager()
        guard.enable_for_servers(server_ids)
        flash('STRM Extract verrà avviato quando i server saranno liberi e senza stream attivi.')
        return redirect(url_for('emby_dashboard'))

    @app.route('/api/emby/strm-guard/status', methods=['GET'])
    @login_required
    def emby_strm_guard_status():
        """Return STRM Guard status for all servers."""
        guard = _ensure_strm_guard_manager()
        with guard._lock:
            status = copy.deepcopy(guard._state)
        return jsonify({"success": True, "status": status})

    @app.route('/api/emby/server-order', methods=['POST'])
    @login_required
    def emby_server_order():
        payload = request.get_json(silent=True)
        if not isinstance(payload, list):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        raw_config = read_raw_config() or {}
        emby_section = raw_config.get("EMBY") or {}
        servers = copy.deepcopy(emby_section.get("SERVERS") or [])
        server_map = {server.get("id"): server for server in servers if server.get("id")}
        ordered = []
        for entry in payload:
            if not isinstance(entry, str):
                continue
            server = server_map.get(entry)
            if server:
                ordered.append(server)
        remaining = [server for server in servers if server.get("id") not in payload]
        ordered.extend(remaining)
        raw_config["EMBY"] = {"SERVERS": ordered}
        config_write_file(raw_config)
        load_config()
        return jsonify({"success": True})

    @app.route('/emby/libraries', methods=['GET'])
    @login_required
    def emby_libraries():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        all_libraries = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            libraries, error = _fetch_emby_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error
            }
        return jsonify({"success": True, "servers": all_libraries})

    @app.route('/api/emby/associations', methods=['GET', 'POST'])
    @login_required
    def manage_associations():
        if request.method == 'GET':
            try:
                backend = _ensure_db_backend()
                associations = backend.load_library_associations()
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            payload = [
                {
                    "server_id": server_id,
                    "library_id": library_id,
                    "group_name": group_name
                }
                for (server_id, library_id), group_name in associations.items()
            ]
            return jsonify({"success": True, "associations": payload})

        payload = request.get_json(silent=True)
        if not isinstance(payload, list):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        associations = {}
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            server_id = entry.get("server_id")
            library_id = entry.get("library_id")
            group_name = entry.get("group_name")
            if not (server_id and library_id and group_name):
                continue
            associations[(str(server_id), str(library_id))] = str(group_name)
        try:
            backend = _ensure_db_backend()
            backend.save_library_associations(associations)
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
        payload = [
            {
                "server_id": server_id,
                "library_id": library_id,
                "group_name": group_name
            }
            for (server_id, library_id), group_name in associations.items()
        ]
        return jsonify({"success": True, "associations": payload})

    @app.route('/api/emby/grouped-libraries', methods=['GET'])
    @login_required
    def get_grouped_libraries():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        all_libraries = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            libraries, error = _fetch_emby_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error,
                "name": server.get("name")
            }
        try:
            backend = _ensure_db_backend()
            associations = backend.load_library_associations()
            order_map = backend.load_library_group_order()
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
        grouped = group_libraries(all_libraries, associations)
        def _group_key(entry):
            ctype = entry.get("collection_type") or ""
            gname = entry.get("group_name") or ""
            pos = order_map.get((ctype, gname))
            return (pos is None, pos or 0, gname)
        grouped.sort(key=_group_key)
        return jsonify({"success": True, "groups": grouped})

    def _resolve_emby_server(config, server_id):
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        for server in servers:
            if server.get("id") == server_id:
                return server
        return None

    def _resolution_label_from_dims(width, height):
        if not height:
            return ""
        try:
            height_value = int(height)
        except (TypeError, ValueError):
            return ""
        if height_value >= 2160:
            return "2160p"
        if height_value >= 1440:
            return "1440p"
        if height_value >= 1080:
            return "1080p"
        if height_value >= 720:
            return "720p"
        return f"{height_value}p"

    def _extract_emby_media_sources(item):
        sources = []
        if not isinstance(item, dict):
            return sources
        media_sources = item.get("MediaSources")
        if not isinstance(media_sources, list) or not media_sources:
            media_sources = [{
                "MediaStreams": item.get("MediaStreams") or [],
                "Path": item.get("Path"),
                "Bitrate": item.get("Bitrate")
            }]

        for source in media_sources:
            if not isinstance(source, dict):
                continue
            media_streams = source.get("MediaStreams") or []
            if not isinstance(media_streams, list):
                media_streams = []
            video_stream = None
            audio_streams = []
            stream_entries = []
            for idx, stream in enumerate(media_streams):
                if not isinstance(stream, dict):
                    continue
                stream_type = stream.get("Type")
                if stream_type == "Video" and video_stream is None:
                    video_stream = stream
                elif stream_type == "Audio":
                    audio_streams.append(stream)
                stream_entries.append({
                    "type": (stream.get("Type") or "").lower(),
                    "index": idx,
                    "codec": stream.get("Codec"),
                    "profile": stream.get("Profile"),
                    "bitrate": stream.get("BitRate") or stream.get("Bitrate"),
                    "bit_depth": stream.get("BitDepth"),
                    "width": stream.get("Width"),
                    "height": stream.get("Height"),
                    "frame_rate": stream.get("AverageFrameRate") or stream.get("RealFrameRate"),
                    "language": stream.get("DisplayLanguage") or stream.get("Language"),
                    "channels": stream.get("Channels"),
                    "channel_layout": stream.get("ChannelLayout"),
                    "sample_rate": stream.get("SampleRate"),
                    "title": stream.get("DisplayTitle") or stream.get("Title"),
                    "is_default": stream.get("IsDefault"),
                    "is_forced": stream.get("IsForced"),
                    "is_external": stream.get("IsExternal"),
                    "hdr_type": stream.get("HdrType"),
                    "color_space": stream.get("ColorSpace"),
                    "color_transfer": stream.get("ColorTransfer"),
                    "color_primaries": stream.get("ColorPrimaries"),
                    "video_range": stream.get("VideoRange") or stream.get("VideoRangeType")
                })

            width = video_stream.get("Width") if isinstance(video_stream, dict) else None
            height = video_stream.get("Height") if isinstance(video_stream, dict) else None
            resolution = f"{width}x{height}" if width and height else ""
            resolution_label = _resolution_label_from_dims(width, height) or resolution
            video_codec = video_stream.get("Codec") if isinstance(video_stream, dict) else ""
            audio_codec = audio_streams[0].get("Codec") if audio_streams else ""
            bitrate = source.get("Bitrate") or (video_stream.get("BitRate") if isinstance(video_stream, dict) else None)
            bitrate_mbps = round(int(bitrate) / 1_000_000, 2) if bitrate else None
            path = source.get("Path") or item.get("Path") or ""

            audio_tracks = []
            for stream in audio_streams:
                codec = stream.get("Codec") or ""
                language = stream.get("DisplayLanguage") or stream.get("Language") or ""
                channels = stream.get("Channels")
                title_label = stream.get("DisplayTitle") or stream.get("Title") or ""
                parts = [part for part in [codec, language, f"{channels}ch" if channels else ""] if part]
                label = title_label or " · ".join(parts) or "Traccia audio"
                audio_tracks.append(label)

            sources.append({
                "resolution": resolution,
                "resolution_label": resolution_label,
                "width": width,
                "height": height,
                "video_codec": video_codec,
                "audio_codec": audio_codec,
                "bitrate": bitrate,
                "bitrate_mbps": bitrate_mbps,
                "path": path,
                "audio_tracks": audio_tracks,
                "streams": stream_entries
            })

        return sources

    def _build_emby_item_details(item, server):
        sources = _extract_emby_media_sources(item)
        primary = sources[0] if sources else {}
        return {
            "title": item.get("Name") if isinstance(item, dict) else None,
            "year": item.get("ProductionYear") if isinstance(item, dict) else None,
            "server": server.get("name") if server else None,
            "server_icon": server.get("icon") if server else None,
            "resolution": primary.get("resolution", ""),
            "video_codec": primary.get("video_codec", ""),
            "audio_codec": primary.get("audio_codec", ""),
            "bitrate": primary.get("bitrate"),
            "bitrate_mbps": primary.get("bitrate_mbps"),
            "path": primary.get("path", ""),
            "audio_tracks": primary.get("audio_tracks", []),
            "sources": sources,
            "series_name": item.get("SeriesName") if isinstance(item, dict) else None,
            "season_name": item.get("SeasonName") if isinstance(item, dict) else None,
            "season_number": item.get("ParentIndexNumber") if isinstance(item, dict) else None,
            "episode_number": item.get("IndexNumber") if isinstance(item, dict) else None,
            "episode_name": item.get("Name") if isinstance(item, dict) else None,
            "item_type": item.get("Type") if isinstance(item, dict) else None,
            "item_id": item.get("Id") if isinstance(item, dict) else None
        }

    def _runtime_minutes_from_ticks(value):
        if not value:
            return None
        try:
            ticks = int(value)
        except (TypeError, ValueError):
            return None
        if ticks <= 0:
            return None
        return max(1, int(round(ticks / 600_000_000)))

    def _build_emby_latest_item(item, server):
        if not isinstance(item, dict):
            return None
        image_tags = item.get("ImageTags") if isinstance(item.get("ImageTags"), dict) else {}
        item_id = item.get("Id")
        image_url = None
        if server and item_id:
            query = {
                "server_id": server.get("id"),
                "item_id": item_id,
                "type": "Primary",
                "max_width": 240
            }
            if image_tags.get("Primary"):
                query["tag"] = image_tags.get("Primary")
            image_url = f"/api/emby/image?{urlencode(query)}"
        return {
            "item_id": item_id,
            "title": item.get("Name"),
            "year": item.get("ProductionYear"),
            "overview": item.get("Overview"),
            "genres": item.get("Genres") if isinstance(item.get("Genres"), list) else [],
            "community_rating": item.get("CommunityRating"),
            "official_rating": item.get("OfficialRating"),
            "runtime_minutes": _runtime_minutes_from_ticks(item.get("RunTimeTicks")),
            "added_at": item.get("DateCreated"),
            "premiere_date": item.get("PremiereDate"),
            "child_count": item.get("ChildCount"),
            "image_tag": image_tags.get("Primary"),
            "image_url": image_url,
            "server_id": server.get("id") if server else None,
            "server_name": server.get("name") if server else None,
            "server_icon": server.get("icon") if server else None,
            "item_type": item.get("Type")
        }

    def _fetch_emby_latest_items(server, item_type, limit):
        params = {
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Limit": limit,
            "Fields": "DateCreated,Overview,Genres,ProductionYear,RunTimeTicks,CommunityRating,OfficialRating,PremiereDate,ChildCount"
        }
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            return [], payload
        items = payload.get("Items")
        if not isinstance(items, list):
            return [], "Risposta Items inattesa"
        return items, None

    @app.route('/api/emby/availability', methods=['POST'])
    @login_required
    def emby_availability():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        tmdb_id = _try_parse_int(payload.get("tmdb_id") or payload.get("tmdbId"))
        media_type = _normalize_media_type(payload.get("media_type") or payload.get("mediaType"))
        if not tmdb_id:
            return jsonify({"success": False, "message": "TMDB ID mancante"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = [server for server in (emby_config.get("SERVERS") or []) if server.get("enabled")]
        if not servers:
            return jsonify({"success": True, "available_on": []})
        found = check_emby_availability(servers, tmdb_id, media_type=media_type)
        return jsonify({"success": True, "available_on": found})

    @app.route('/api/emby/lookup', methods=['GET'])
    @login_required
    def emby_lookup():
        title = (request.args.get("title") or "").strip()
        if not title:
            return jsonify({"success": False, "message": "Titolo mancante"}), 400
        year = _try_parse_int(request.args.get("year"))
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        if not servers:
            return jsonify({"success": False, "message": "Server Emby non configurati"}), 400

        target_title = sanitize_title(title.lower())
        best_match = None
        best_server = None
        best_score = -1
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "SearchTerm": title,
            "Limit": 10,
            "Fields": "MediaSources,MediaStreams,Path,ProductionYear"
        }

        for server in servers:
            if not server.get("enabled"):
                continue
            success, payload = _call_emby_api(server, "Items", params=params)
            if not success or not isinstance(payload, dict):
                continue
            items = payload.get("Items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("Name") or item.get("OriginalTitle") or ""
                if not name:
                    continue
                normalized = sanitize_title(name.lower())
                score = 0
                if normalized == target_title:
                    score += 3
                elif target_title in normalized or normalized in target_title:
                    score += 1
                item_year = item.get("ProductionYear")
                if year and item_year and int(item_year) == year:
                    score += 2
                if score > best_score:
                    best_score = score
                    best_match = item
                    best_server = server

        if not best_match or best_score <= 0:
            return jsonify({"success": True, "found": False, "message": "Nessun elemento trovato in Emby"})

        details = _build_emby_item_details(best_match, best_server)
        if not details.get("title"):
            details["title"] = title
        return jsonify({"success": True, "found": True, "details": details})

    @app.route('/api/emby/item-details', methods=['GET'])
    @login_required
    def emby_item_details():
        server_id = request.args.get("server_id")
        item_id = request.args.get("item_id")
        if not server_id or not item_id:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        server = _resolve_emby_server(config, server_id)
        if not server:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        params = {
            "Fields": "MediaSources,MediaStreams,Path,ProductionYear,IndexNumber,ParentIndexNumber,SeriesName,SeasonName"
        }
        success, payload = _call_emby_api(server, f"Items/{item_id}", params=params)
        item_payload = payload if isinstance(payload, dict) else None
        if not success or item_payload is None:
            fallback_params = {
                "Ids": item_id,
                "Fields": params.get("Fields")
            }
            fallback_success, fallback_payload = _call_emby_api(server, "Items", params=fallback_params)
            if fallback_success and isinstance(fallback_payload, dict):
                items = fallback_payload.get("Items")
                if isinstance(items, list) and items:
                    item_payload = items[0]
                    success = True
        if not success or not isinstance(item_payload, dict):
            return jsonify({"success": False, "message": "Errore recupero dettagli Emby"}), 502
        details = _build_emby_item_details(item_payload, server)
        return jsonify({"success": True, "details": details})

    @app.route('/api/emby/latest', methods=['GET'])
    @login_required
    def emby_latest():
        limit = _coerce_request_int(request.args.get("limit"), 12, 1, 50)
        per_server_limit = _coerce_request_int(request.args.get("per_server_limit"), limit, 1, 50)
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = [server for server in (emby_config.get("SERVERS") or []) if server.get("enabled")]
        if not servers:
            return jsonify({"success": True, "movies": [], "series": [], "errors": []})

        movies = []
        series = []
        errors = []

        for server in servers:
            movie_items, movie_error = _fetch_emby_latest_items(server, "Movie", per_server_limit)
            if movie_error:
                errors.append({"server_id": server.get("id"), "message": str(movie_error)})
            for item in movie_items:
                entry = _build_emby_latest_item(item, server)
                if entry:
                    movies.append(entry)

            series_items, series_error = _fetch_emby_latest_items(server, "Series", per_server_limit)
            if series_error:
                errors.append({"server_id": server.get("id"), "message": str(series_error)})
            for item in series_items:
                entry = _build_emby_latest_item(item, server)
                if entry:
                    series.append(entry)

        def _sort_key(entry):
            if not isinstance(entry, dict):
                return datetime.min.replace(tzinfo=timezone.utc)
            dt_value = _parse_date_value(entry.get("added_at")) or _parse_date_value(entry.get("premiere_date"))
            return dt_value or datetime.min.replace(tzinfo=timezone.utc)

        movies.sort(key=_sort_key, reverse=True)
        series.sort(key=_sort_key, reverse=True)

        return jsonify({
            "success": True,
            "movies": movies[:limit],
            "series": series[:limit],
            "errors": errors
        })

    @app.route('/api/emby/image', methods=['GET'])
    @login_required
    def emby_image():
        server_id = request.args.get("server_id")
        item_id = request.args.get("item_id")
        image_type = request.args.get("type", "Primary")
        max_width = request.args.get("max_width")
        max_height = request.args.get("max_height")
        tag = request.args.get("tag")

        if not server_id or not item_id:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400

        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        server = _resolve_emby_server(config, server_id)
        if not server:
            return jsonify({"success": False, "message": "Server non trovato"}), 404

        base_url = (server.get("url") or "").strip().rstrip("/")
        token = (server.get("api_key") or "").strip()
        if not base_url or not token:
            return jsonify({"success": False, "message": "Credenziali Emby mancanti"}), 400

        params = {"api_key": token}
        if max_width:
            params["maxWidth"] = max_width
        if max_height:
            params["maxHeight"] = max_height
        if tag:
            params["tag"] = tag

        url = f"{base_url}/Items/{item_id}/Images/{image_type}"
        try:
            response = requests.get(
                url,
                headers={"X-Emby-Token": token, "Accept": "image/*"},
                params=params,
                stream=True,
                timeout=15
            )
            response.raise_for_status()
        except requests.RequestException:
            return jsonify({"success": False, "message": "Errore caricamento immagine"}), 502

        content_type = response.headers.get("Content-Type") or "image/jpeg"
        return Response(stream_with_context(response.iter_content(chunk_size=8192)), content_type=content_type)

    @app.route('/api/emby/movie-versions', methods=['GET'])
    @login_required
    def emby_movie_versions():
        server_id = request.args.get("server_id")
        tmdb_id = request.args.get("tmdb_id")
        if not server_id or not tmdb_id:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400
        tmdb_value = _try_parse_int(tmdb_id)
        if not tmdb_value:
            return jsonify({"success": False, "message": "TMDB ID non valido"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        server = _resolve_emby_server(config, server_id)
        if not server:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        params = {
            "AnyProviderIdEquals": f"Tmdb.{tmdb_value}",
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "MediaSources,MediaStreams,Path,Bitrate"
        }
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Errore recupero versioni Emby"}), 502
        items_payload = payload.get("Items")
        items = items_payload if isinstance(items_payload, list) else []
        versions = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sources = _extract_emby_media_sources(item)
            labels = []
            for source in sources:
                label = source.get("resolution_label") or source.get("resolution") or ""
                if label:
                    labels.append(label)
            unique_labels = []
            for label in labels:
                if label not in unique_labels:
                    unique_labels.append(label)
            versions.append({
                "item_id": item.get("Id"),
                "name": item.get("Name"),
                "resolutions": unique_labels
            })
        return jsonify({"success": True, "versions": versions})

    @app.route('/api/emby/series-seasons', methods=['GET'])
    @login_required
    def emby_series_seasons():
        server_id = request.args.get("server_id")
        series_id = request.args.get("series_id")
        if not server_id or not series_id:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        server = _resolve_emby_server(config, server_id)
        if not server:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        params = {
            "ParentId": series_id,
            "IncludeItemTypes": "Season",
            "Recursive": "false",
            "Fields": "IndexNumber,Name,ChildCount"
        }
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Errore recupero stagioni Emby"}), 502
        items_payload = payload.get("Items")
        items = items_payload if isinstance(items_payload, list) else []
        seasons = []
        for item in items:
            if not isinstance(item, dict):
                continue
            seasons.append({
                "season_id": item.get("Id"),
                "season_number": item.get("IndexNumber"),
                "name": item.get("Name"),
                "episode_count": item.get("ChildCount", 0)
            })
        seasons.sort(key=lambda entry: entry.get("season_number") if entry.get("season_number") is not None else 999)
        return jsonify({"success": True, "seasons": seasons})

    @app.route('/api/emby/season-episodes', methods=['GET'])
    @login_required
    def emby_season_episodes():
        server_id = request.args.get("server_id")
        season_id = request.args.get("season_id")
        if not server_id or not season_id:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        server = _resolve_emby_server(config, server_id)
        if not server:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        params = {
            "ParentId": season_id,
            "IncludeItemTypes": "Episode",
            "Recursive": "false",
            "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams"
        }
        success, payload = _call_emby_api(server, "Items", params=params)
        if not success or not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Errore recupero episodi Emby"}), 502
        items_payload = payload.get("Items")
        items = items_payload if isinstance(items_payload, list) else []
        details_map = {}
        episode_ids = [item.get("Id") for item in items if isinstance(item, dict) and item.get("Id")]
        if episode_ids:
            detail_params = {
                "Ids": ",".join(str(entry) for entry in episode_ids),
                "Fields": "IndexNumber,Name,ProductionYear,PremiereDate,MediaSources,MediaStreams,Path,Bitrate"
            }
            detail_success, detail_payload = _call_emby_api(server, "Items", params=detail_params)
            if detail_success and isinstance(detail_payload, dict):
                detail_items_payload = detail_payload.get("Items")
                if isinstance(detail_items_payload, list):
                    for detail in detail_items_payload:
                        if isinstance(detail, dict) and detail.get("Id"):
                            details_map[str(detail.get("Id"))] = detail

        grouped = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("Id")
            detail = details_map.get(str(item_id), item)
            episode_number = detail.get("IndexNumber") if isinstance(detail, dict) else item.get("IndexNumber")
            group_key = episode_number if episode_number is not None else item_id
            if group_key not in grouped:
                grouped[group_key] = {
                    "episode_id": item_id,
                    "episode_number": episode_number,
                    "name": detail.get("Name") if isinstance(detail, dict) else item.get("Name"),
                    "year": detail.get("ProductionYear") if isinstance(detail, dict) else item.get("ProductionYear"),
                    "resolutions": []
                }
            if not grouped[group_key].get("episode_id") and item_id:
                grouped[group_key]["episode_id"] = item_id
            sources = _extract_emby_media_sources(detail)
            for source_index, source in enumerate(sources):
                label = source.get("resolution_label") or source.get("resolution") or ""
                if label:
                    grouped[group_key]["resolutions"].append({
                        "label": label,
                        "item_id": item_id,
                        "source_index": source_index
                    })

        def _resolution_sort_key(value):
            if isinstance(value, str) and value.endswith("p") and value[:-1].isdigit():
                return int(value[:-1])
            return 0

        episodes = []
        for group in grouped.values():
            resolutions = [entry for entry in group["resolutions"] if entry.get("label")]
            resolutions.sort(key=lambda entry: _resolution_sort_key(entry.get("label")), reverse=True)
            episodes.append({
                "episode_id": group.get("episode_id"),
                "episode_number": group.get("episode_number"),
                "name": group.get("name"),
                "year": group.get("year"),
                "resolutions": resolutions
            })
        episodes.sort(key=lambda entry: entry.get("episode_number") if entry.get("episode_number") is not None else 999)
        return jsonify({"success": True, "episodes": episodes})

    @app.route('/api/emby/scan-library', methods=['POST'])
    @login_required
    def scan_library():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        library_id = payload.get("library_id")
        if not server_id or not library_id:
            return jsonify({"success": False, "message": "server_id o library_id mancante"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target_server = None
        for server in servers:
            if server.get("id") == server_id:
                target_server = server
                break
        if target_server is None:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not target_server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        success, response = _trigger_library_scan(target_server, str(library_id))
        if success:
            return jsonify({"success": True, "message": "Scansione avviata."})
        return jsonify({"success": False, "message": f"Errore scansione: {response}"}), 500

    # --- Probe Discovery Routes ---

    @app.route('/api/emby/probe/discovery/start', methods=['POST'])
    @login_required
    def probe_discovery_start():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target_server = None
        for server in servers:
            if server.get("id") == server_id:
                target_server = server
                break
        if target_server is None:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not target_server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        libraries = payload.get("libraries")  # Optional list of library IDs
        started = get_probe_manager().start_discovery(target_server, server_id, target_libraries=libraries)
        if started:
            return jsonify({"success": True, "message": "Discovery avviato"})
        return jsonify({"success": False, "message": "Discovery già in esecuzione"}), 400

    @app.route('/api/emby/probe/discovery/stop', methods=['POST'])
    @login_required
    def probe_discovery_stop():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400
        stopped = get_probe_manager().stop_discovery(server_id)
        if stopped:
            return jsonify({"success": True, "message": "Discovery arrestato"})
        return jsonify({"success": False, "message": "Discovery non in esecuzione"}), 400

    # --- Probe Processing Routes ---

    @app.route('/api/emby/probe/processing/start', methods=['POST'])
    @login_required
    def probe_processing_start():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        mode = payload.get("mode", "smart")
        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400
        if mode not in ("smart", "forced"):
            return jsonify({"success": False, "message": "mode deve essere 'smart' o 'forced'"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target_server = None
        for server in servers:
            if server.get("id") == server_id:
                target_server = server
                break
        if target_server is None:
            return jsonify({"success": False, "message": "Server non trovato"}), 404
        if not target_server.get("enabled"):
            return jsonify({"success": False, "message": "Server disabilitato"}), 400
        libraries = payload.get("libraries")  # Optional list of library IDs
        started = get_probe_manager().start_processing(target_server, server_id, mode, target_libraries=libraries)
        if started:
            return jsonify({"success": True, "message": f"Processing avviato in modalità {mode}"})
        return jsonify({"success": False, "message": "Processing già in esecuzione"}), 400

    @app.route('/api/emby/probe/processing/stop', methods=['POST'])
    @login_required
    def probe_processing_stop():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        server_id = payload.get("server_id")
        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400
        stopped = get_probe_manager().stop_processing(server_id)
        if stopped:
            return jsonify({"success": True, "message": "Processing arrestato"})
        return jsonify({"success": False, "message": "Processing non in esecuzione"}), 400

    # --- Probe Queue Routes ---

    @app.route('/api/emby/probe/queue', methods=['GET', 'DELETE'])
    @login_required
    def probe_queue():
        if request.method == 'GET':
            server_id = request.args.get("server_id")
            try:
                backend = _ensure_db_backend()
                queue = backend.get_probe_queue(server_id)
                for item in queue:
                    item["display_name"] = _format_display_name_from_queue(item)
                library_totals = {}
                if server_id:
                    probe_status = get_probe_manager().get_status(server_id)
                    library_totals = (probe_status.get("discovery") or {}).get("library_totals") or {}
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            return jsonify({"success": True, "queue": queue, "library_totals": library_totals})

        # DELETE
        payload = request.get_json(silent=True) or {}
        server_id = payload.get("server_id") or request.args.get("server_id")
        item_id = payload.get("item_id")
        media_source_id = payload.get("media_source_id")

        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400

        try:
            backend = _ensure_db_backend()
            if item_id:
                # Remove specific item
                backend.remove_from_probe_queue(server_id, item_id, media_source_id)
                return jsonify({"success": True, "message": "Item rimosso dalla coda"})
            else:
                # Clear entire queue for server
                backend.clear_probe_queue(server_id)
                return jsonify({"success": True, "message": "Coda svuotata"})
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500

    # --- Probe History Routes ---

    @app.route('/api/emby/probe/history', methods=['GET', 'DELETE'])
    @login_required
    def probe_history():
        if request.method == 'GET':
            server_id = request.args.get("server_id")
            limit = request.args.get("limit", "100")
            try:
                limit_int = int(limit)
            except ValueError:
                limit_int = 100

            try:
                backend = _ensure_db_backend()
                history = backend.get_probe_history(server_id, limit_int)
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            return jsonify({"success": True, "history": history})

        # DELETE
        payload = request.get_json(silent=True) or {}
        server_id = payload.get("server_id") or request.args.get("server_id")

        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400

        try:
            backend = _ensure_db_backend()
            backend.clear_probe_history(server_id)
            return jsonify({"success": True, "message": "Storico svuotato"})
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500

    @app.route('/api/emby/probe/retry', methods=['POST'])
    @login_required
    def probe_retry():
        payload = request.get_json(silent=True) or {}
        server_id = payload.get("server_id")
        item_id = payload.get("item_id")
        media_source_id = payload.get("media_source_id")

        if not server_id or not item_id:
            return jsonify({"success": False, "message": "server_id o item_id mancante"}), 400

        # Get server configuration
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400

        emby_config = config.get("EMBY") or {}
        servers = emby_config.get("SERVERS") or []
        target_server = next((s for s in servers if s.get("id") == server_id), None)

        if not target_server:
            return jsonify({"success": False, "message": f"Server {server_id} non trovato"}), 404

        # Call retry_item on probe manager
        success, message = get_probe_manager().retry_item(target_server, server_id, item_id, media_source_id)

        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 500

    # --- Probe Blacklist Routes ---

    @app.route('/api/emby/probe/blacklist', methods=['GET', 'DELETE'])
    @login_required
    def probe_blacklist():
        if request.method == 'GET':
            server_id = request.args.get("server_id")
            min_retry = request.args.get("min_retry", "3")
            error_type = request.args.get("type") or request.args.get("error_type")
            try:
                min_retry_int = int(min_retry)
            except ValueError:
                min_retry_int = 3

            try:
                backend = _ensure_db_backend()
                blacklist = backend.get_probe_blacklist(
                    server_id,
                    min_retry_count=min_retry_int,
                    error_type=error_type
                )
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            return jsonify({"success": True, "blacklist": blacklist})

        # DELETE - remove specific item or clear all
        payload = request.get_json(silent=True) or {}
        server_id = payload.get("server_id") or request.args.get("server_id")
        item_id = payload.get("item_id")
        media_source_id = payload.get("media_source_id")
        error_type = payload.get("type") or request.args.get("type")

        if not server_id:
            return jsonify({"success": False, "message": "server_id mancante"}), 400

        try:
            backend = _ensure_db_backend()
            if item_id:
                # Remove specific item from blacklist
                backend.remove_from_probe_blacklist(server_id, item_id, media_source_id)
                return jsonify({"success": True, "message": "Item rimosso dalla blacklist"})
            else:
                # Clear entire blacklist for server
                backend.clear_probe_blacklist(server_id, error_type=error_type)
                return jsonify({"success": True, "message": "Blacklist svuotata"})
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500

    @app.route('/api/emby/group-order', methods=['GET', 'POST'])
    @login_required
    def manage_group_order():
        if request.method == 'GET':
            try:
                backend = _ensure_db_backend()
                order_map = backend.load_library_group_order()
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            payload = [
                {
                    "collection_type": collection_type,
                    "group_name": group_name,
                    "position": position
                }
                for (collection_type, group_name), position in order_map.items()
            ]
            return jsonify({"success": True, "order": payload})

        payload = request.get_json(silent=True)
        if not isinstance(payload, list):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        positions = {}
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            collection_type = entry.get("collection_type")
            group_name = entry.get("group_name")
            position = entry.get("position")
            if collection_type is None or group_name is None or position is None:
                continue
            positions[(str(collection_type), str(group_name))] = int(position)
        try:
            backend = _ensure_db_backend()
            backend.save_library_group_order(positions)
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
        return jsonify({"success": True, "order": payload})

    @app.route('/api/ui/tab-order', methods=['GET', 'POST'])
    @login_required
    def manage_tab_order():
        if request.method == 'GET':
            page = request.args.get('page') or ''
            if not page:
                return jsonify({"success": False, "message": "Pagina mancante"}), 400
            try:
                backend = _ensure_db_backend()
                order_map = backend.load_tab_order(page)
            except StorageError as exc:
                return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
            payload = [
                {"tab_key": tab_key, "position": position}
                for tab_key, position in order_map.items()
            ]
            return jsonify({"success": True, "order": payload})

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        page = payload.get("page")
        order = payload.get("order")
        if not page or not isinstance(order, list):
            return jsonify({"success": False, "message": "Dati mancanti"}), 400
        positions = {}
        for entry in order:
            if not isinstance(entry, dict):
                continue
            tab_key = entry.get("tab_key")
            position = entry.get("position")
            if tab_key is None or position is None:
                continue
            positions[str(tab_key)] = int(position)
        try:
            backend = _ensure_db_backend()
            backend.save_tab_order(str(page), positions)
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
        return jsonify({"success": True, "order": order})

    @app.route('/api/media/details', methods=['GET'])
    @login_required
    def media_details():
        tmdb_id = _try_parse_int(request.args.get("tmdb_id"))
        media_type = _normalize_media_type(request.args.get("media_type"))
        if not tmdb_id or not media_type:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400

        config, _ = load_config()
        if not config:
            return jsonify({"success": False, "message": "Config mancante"}), 400
        if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
            return jsonify({"success": False, "message": "Jellyseerr non configurato"}), 400

        cache = {}
        tmdb_payload, resolved_type = fetch_media_info(
            {"tmdbId": tmdb_id, "mediaType": media_type},
            config,
            cache,
            fallback_media_type=media_type
        )
        if not tmdb_payload:
            return jsonify({"success": False, "message": "Dettagli non disponibili"}), 404

        normalized_type = resolved_type or media_type
        if normalized_type == "movie":
            original_title = tmdb_payload.get("original_title") or tmdb_payload.get("originalTitle") or ""
            title = tmdb_payload.get("title") or tmdb_payload.get("name") or ""
            date_value = tmdb_payload.get("release_date") or tmdb_payload.get("releaseDate") or ""
        else:
            original_title = tmdb_payload.get("original_name") or tmdb_payload.get("originalName") or ""
            title = tmdb_payload.get("name") or tmdb_payload.get("title") or ""
            date_value = tmdb_payload.get("first_air_date") or tmdb_payload.get("firstAirDate") or ""

        year = ""
        if isinstance(date_value, str) and date_value:
            year = date_value.split("-", 1)[0]
        elif isinstance(date_value, int):
            year = str(date_value)

        seasons = []
        if normalized_type == "tv":
            raw_seasons = tmdb_payload.get("seasons") if isinstance(tmdb_payload, dict) else []
            if isinstance(raw_seasons, list):
                for entry in raw_seasons:
                    if not isinstance(entry, dict):
                        continue
                    number = entry.get("season_number") or entry.get("seasonNumber") or entry.get("number") or entry.get("season")
                    parsed_number = _try_parse_int(number)
                    if parsed_number is None:
                        continue
                    episode_count = entry.get("episode_count") or entry.get("episodeCount") or entry.get("episodes")
                    parsed_count = None
                    if isinstance(episode_count, list):
                        parsed_count = len(episode_count)
                    else:
                        parsed_count = _try_parse_int(episode_count)
                    seasons.append({
                        "season_number": parsed_number,
                        "episode_count": parsed_count
                    })
            seasons.sort(key=lambda item: item.get("season_number", 0))

        return jsonify({
            "success": True,
            "media_type": normalized_type,
            "title": title or original_title,
            "original_title": original_title or title,
            "year": year,
            "seasons": seasons
        })

    @app.route('/api/jellyseerr/request', methods=['POST'])
    @login_required
    def jellyseerr_request():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "Formato non valido"}), 400

        media_id = _try_parse_int(
            payload.get("mediaId") or payload.get("media_id") or payload.get("tmdb_id")
        )
        media_type = _normalize_media_type(payload.get("mediaType") or payload.get("media_type"))
        if not media_id or not media_type:
            return jsonify({"success": False, "message": "Parametri mancanti"}), 400

        raw_seasons = payload.get("seasons")
        if not isinstance(raw_seasons, list):
            raw_seasons = []
        seasons = []
        for entry in raw_seasons:
            parsed = _try_parse_int(entry)
            if parsed is not None:
                seasons.append(parsed)

        request_payload = {"mediaId": media_id, "mediaType": media_type}
        if seasons and media_type == "tv":
            request_payload["seasons"] = seasons

        config, _ = load_config()
        if not config:
            return jsonify({"success": False, "message": "Config mancante"}), 400
        if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
            return jsonify({"success": False, "message": "Jellyseerr non configurato"}), 400

        success, message, data = submit_jellyseerr_request(request_payload, config)
        if not success:
            return jsonify({"success": False, "message": message}), 502

        return jsonify({"success": True, "message": message, "data": data})

    @app.route('/api/tmdb/search', methods=['GET'])
    @login_required
    def tmdb_search():
        """Search TMDB for movies and TV shows (autocomplete)."""
        query = request.args.get('query', '').strip()

        if not query:
            return jsonify({"success": False, "message": "Query mancante"}), 400

        config, is_valid = load_config()
        if not config:
            return jsonify({"success": False, "message": "Configurazione mancante"}), 400

        api_key = config.get('TMDB_API_KEY')
        if not api_key:
            return jsonify({
                "success": False,
                "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
            }), 400

        language = config.get('TMDB_LANGUAGE', 'it-IT')

        results = search_tmdb(api_key, query, language)

        return jsonify({
            "success": True,
            "results": results
        })

    @app.route('/api/tmdb/tv/<int:tv_id>', methods=['GET'])
    @login_required
    def tmdb_tv_details(tv_id):
        """Get TV show details including seasons from TMDB."""
        config, is_valid = load_config()
        if not config:
            return jsonify({"success": False, "message": "Configurazione mancante"}), 400

        api_key = config.get('TMDB_API_KEY')
        if not api_key:
            return jsonify({
                "success": False,
                "message": "API Key TMDB non configurata. Vai in Configurazione Servizi."
            }), 400

        language = config.get('TMDB_LANGUAGE', 'it-IT')

        details = get_tmdb_tv_details(api_key, tv_id, language)

        if not details:
            return jsonify({
                "success": False,
                "message": "Impossibile ottenere i dettagli della serie TV"
            }), 404

        return jsonify({
            "success": True,
            "details": details
        })

    @app.route('/api/tmdb/check-availability', methods=['POST'])
    @login_required
    def check_tmdb_availability():
        """Check if TMDB content is present on Jellyseerr."""
        data = request.get_json(silent=True) or {}
        tmdb_id = data.get('tmdb_id')
        media_type = data.get('media_type')

        if not tmdb_id:
            return jsonify({
                "success": False,
                "message": "TMDB ID mancante"
            }), 400

        config, is_valid = load_config()
        if not config:
            return jsonify({"success": False, "message": "Configurazione mancante"}), 400

        if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
            return jsonify({
                "success": True,
                "available_on": []
            })

        found = check_jellyseerr_availability(tmdb_id, media_type, config)
        found_servers = [found] if found else []

        return jsonify({
            "success": True,
            "available_on": found_servers
        })

    @app.route('/api/search/manual', methods=['POST'])
    @login_required
    def manual_search():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        form_payload = {}
        if request.form:
            form_payload["query"] = (request.form.get("query") or "").strip()
            form_payload["media_type"] = request.form.get("media_type") or request.form.get("tmdb_type")
            form_payload["indexers"] = request.form.getlist("indexer")
            form_payload["use_jellyseerr_logic"] = bool(request.form.get("use_jellyseerr_directives"))
            form_payload["use_custom_rules"] = bool(request.form.get("use_custom_rules"))
            form_payload["tmdb_id"] = request.form.get("tmdb_id") or ""
            seasons = []
            for entry in request.form.getlist("seasons"):
                try:
                    seasons.append(int(entry))
                except (TypeError, ValueError):
                    continue
            if seasons:
                form_payload["seasons"] = seasons
            if form_payload.get("use_custom_rules"):
                custom_rules = {}
                include_filter = (request.form.get("include_filter") or "").strip()
                exclude_filter = (request.form.get("exclude_filter") or "").strip()
                if include_filter:
                    custom_rules["include_filter"] = include_filter
                if exclude_filter:
                    custom_rules["exclude_filter"] = exclude_filter
                min_size = request.form.get("min_size_gb")
                max_size = request.form.get("max_size_gb")
                if min_size not in (None, ""):
                    try:
                        custom_rules["min_size_gb"] = float(min_size)
                    except ValueError:
                        pass
                if max_size not in (None, ""):
                    try:
                        custom_rules["max_size_gb"] = float(max_size)
                    except ValueError:
                        pass
                quality = request.form.get("quality")
                audio_language = request.form.get("audio_language")
                edition = request.form.get("edition")
                season_value = request.form.get("season")
                episode_value = request.form.get("episode")
                if quality:
                    custom_rules["quality"] = quality
                if audio_language:
                    custom_rules["audio_language"] = audio_language
                if edition:
                    custom_rules["edition"] = edition
                if season_value not in (None, ""):
                    try:
                        custom_rules["season"] = int(season_value)
                    except ValueError:
                        pass
                if episode_value not in (None, ""):
                    try:
                        custom_rules["episode"] = int(episode_value)
                    except ValueError:
                        pass
                if custom_rules:
                    form_payload["custom_rules"] = custom_rules
        if form_payload:
            for key, value in form_payload.items():
                if key not in payload or payload.get(key) in (None, "", [], {}):
                    payload[key] = value
        if not isinstance(payload, dict) or not payload:
            return jsonify({"success": False, "message": "Formato non valido"}), 400

        query = (payload.get("query") or "").strip()
        if not query:
            return jsonify({"success": False, "message": "Query mancante"}), 400

        media_type = _normalize_media_type(payload.get("media_type"))
        indexers_value = payload.get("indexers")
        indexers = indexers_value if isinstance(indexers_value, list) else []
        selected_indexers = {entry for entry in indexers if entry in {"prowlarr", "jackett"}}
        if not selected_indexers:
            return jsonify({"success": False, "message": "Indexer mancanti"}), 400

        tmdb_id = _try_parse_int(payload.get("tmdb_id"))
        print(f"[manual_search] query={query!r} indexers={sorted(selected_indexers)} tmdb_id={tmdb_id}")

        use_jellyseerr_logic = bool(payload.get("use_jellyseerr_logic"))
        use_custom_rules = bool(payload.get("use_custom_rules"))
        custom_rules = payload.get("custom_rules") if isinstance(payload.get("custom_rules"), dict) else None
        if not use_custom_rules:
            custom_rules = None
        if use_jellyseerr_logic:
            custom_rules = None

        config, is_valid = load_config()
        if not config or not is_valid:
            return jsonify({"success": False, "message": "Config non valida"}), 400

        effective_config = copy.deepcopy(config)
        effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
        if use_jellyseerr_logic and custom_rules:
            overrides = {}
            if isinstance(custom_rules.get("SEARCH_RULES"), dict):
                overrides.update(custom_rules.get("SEARCH_RULES") or {})
            if isinstance(custom_rules.get("search_rules"), dict):
                overrides.update(custom_rules.get("search_rules") or {})
            for key, value in custom_rules.items():
                if key in {"SEARCH_RULES", "search_rules", "TARGET_LANGUAGES", "target_languages", "EXCLUDE_TAGS", "exclude_tags"}:
                    continue
                if key in effective_rules or key in DEFAULT_CONFIG.get("SEARCH_RULES", {}):
                    overrides[key] = value
            if overrides:
                effective_rules.update(overrides)
            effective_config["SEARCH_RULES"] = effective_rules
            if "TARGET_LANGUAGES" in custom_rules or "target_languages" in custom_rules:
                target_langs = custom_rules.get("TARGET_LANGUAGES")
                if target_langs is None:
                    target_langs = custom_rules.get("target_languages")
                if target_langs is not None:
                    effective_config["TARGET_LANGUAGES"] = target_langs
            if "EXCLUDE_TAGS" in custom_rules or "exclude_tags" in custom_rules:
                exclude_tags = custom_rules.get("EXCLUDE_TAGS")
                if exclude_tags is None:
                    exclude_tags = custom_rules.get("exclude_tags")
                if exclude_tags is not None:
                    effective_config["EXCLUDE_TAGS"] = exclude_tags

        warnings = []
        warnings_set = set()
        raw_results = []
        debug_queries = []
        debug_query_set = set()

        query_variants = []
        search_media_type = media_type

        if use_jellyseerr_logic and tmdb_id and media_type:
            cache = {}
            tmdb_payload, resolved_type = fetch_media_info(
                {"tmdbId": tmdb_id, "mediaType": media_type},
                effective_config,
                cache,
                fallback_media_type=media_type
            )
            if tmdb_payload:
                title_candidates = gather_title_candidates(tmdb_payload, search_rules=effective_rules)
                _, year_value = extract_title_and_year(tmdb_payload)
                if not year_value:
                    year_value = _extract_year_from_title(query)
                if title_candidates:
                    search_media_type = resolved_type or media_type
                    query_variants = build_search_queries(
                        title_candidates,
                        year_value,
                        effective_config,
                        media_type=search_media_type,
                        search_rules_override=effective_rules
                    )

        if not query_variants:
            query_variants = [query]

        search_types = [search_media_type] if search_media_type else ["movie", "tv"]

        def _add_warning(message):
            if message in warnings_set:
                return
            warnings_set.add(message)
            warnings.append(message)

        for query_variant in query_variants:
            normalized_query = (query_variant or "").strip()
            if not normalized_query:
                continue
            if normalized_query not in debug_query_set:
                debug_queries.append(normalized_query)
                debug_query_set.add(normalized_query)
            for entry in search_types:
                if "prowlarr" in selected_indexers:
                    if _prowlarr_configured(config):
                        raw_results.extend(search_prowlarr(normalized_query, entry, config))
                    else:
                        _add_warning("Prowlarr non configurato")
                if "jackett" in selected_indexers:
                    if _jackett_configured(config):
                        raw_results.extend(search_jackett(normalized_query, entry, config))
                    else:
                        _add_warning("Jackett non configurato")

        prepared = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            magnet_uri = item.get("magnetUri") or item.get("magnetUrl") or item.get("magnet")
            guid_value = item.get("guid")
            if magnet_uri and (not isinstance(guid_value, str) or not guid_value.startswith("magnet:")):
                cloned = dict(item)
                cloned["guid"] = magnet_uri
                prepared.append(cloned)
            else:
                prepared.append(item)

        library_index = _load_emby_library_title_index()
        results = []

        if use_jellyseerr_logic:
            filtered = filter_results(prepared, effective_config, media_type=search_media_type)
            raw_map = {}
            for entry in prepared:
                title = entry.get("title") or ""
                if not title:
                    continue
                size_bytes = entry.get("size") or 0
                size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0
                key = (sanitize_title(title.lower()), size_gb)
                raw_map.setdefault(key, entry)
            seen = set()
            for item in filtered:
                normalized_title = item.get("normalized_title") or sanitize_title((item.get("title") or "").lower())
                key = (normalized_title, item.get("size_gb"))
                raw_item = raw_map.get(key, {})
                leechers = _coerce_int(raw_item.get("leechers") or raw_item.get("Leechers"), 0)
                normalized = {
                    "title": item.get("title"),
                    "size_gb": item.get("size_gb"),
                    "seeders": item.get("seeders", 0),
                    "leechers": leechers,
                    "indexer": item.get("indexer"),
                    "magnet": item.get("magnet"),
                    "torrent": item.get("torrent"),
                    "web": item.get("web"),
                    "resolution": item.get("resolution_bucket"),
                    "resolution_bucket": item.get("resolution_bucket"),
                    "season_number": item.get("season_number"),
                    "season_label": item.get("season_label"),
                    "episode_code": item.get("episode_code"),
                    "episode_sort": item.get("episode_sort"),
                    "episode_number": item.get("episode_number"),
                    "normalized_title": normalized_title,
                    "year": _extract_year_from_title(item.get("title") or "")
                }
                if normalized.get("season_number") is None and not normalized.get("season_label"):
                    fallback_season, fallback_label = _extract_season_hint_from_title(item.get("title") or "")
                    if fallback_season is not None:
                        normalized["season_number"] = fallback_season
                    if fallback_label:
                        normalized["season_label"] = fallback_label
                dedupe_key = _manual_result_key(normalized)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                normalized["in_library"] = bool(library_index and normalized.get("normalized_title") in library_index)
                results.append(normalized)
        else:
            seen = set()
            for entry in prepared:
                normalized = _normalize_manual_result(entry)
                if not normalized:
                    continue
                dedupe_key = _manual_result_key(normalized)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                normalized["in_library"] = bool(library_index and normalized.get("normalized_title") in library_index)
                results.append(normalized)

        # Apply custom filters if provided
        if custom_rules:
            include_filter = custom_rules.get("include_filter")
            exclude_filter = custom_rules.get("exclude_filter")
            min_size_gb = custom_rules.get("min_size_gb")
            max_size_gb = custom_rules.get("max_size_gb")

            if include_filter or exclude_filter or min_size_gb is not None or max_size_gb is not None:
                filtered_results = []
                for result in results:
                    title_lower = (result.get("title") or "").lower()
                    size_gb = result.get("size_gb", 0)

                    # Include filter: title must contain at least one of the words
                    if include_filter:
                        include_words = [w.strip().lower() for w in include_filter.split(",") if w.strip()]
                        if include_words and not any(word in title_lower for word in include_words):
                            continue

                    # Exclude filter: title must not contain any of the words
                    if exclude_filter:
                        exclude_words = [w.strip().lower() for w in exclude_filter.split(",") if w.strip()]
                        if exclude_words and any(word in title_lower for word in exclude_words):
                            continue

                    # Size filters
                    if min_size_gb is not None and size_gb < min_size_gb:
                        continue
                    if max_size_gb is not None and size_gb > max_size_gb:
                        continue

                    filtered_results.append(result)

                results = filtered_results

        return jsonify({
            "success": True,
            "results": results,
            "warnings": warnings,
            "debug_queries": debug_queries
        })

    @app.route('/update-config', methods=['POST'])
    @login_required
    def update_config_route():
        raw_config = read_raw_config() or {}
        
        # Connection fields mapping
        connection_mappings = [
            ('jellyseerr_url', 'JELLYSEERR_URL'),
            ('jellyseerr_api_key', 'JELLYSEERR_API_KEY'),
            ('prowlarr_url', 'PROWLARR_URL'),
            ('prowlarr_api_key', 'PROWLARR_API_KEY'),
            ('jackett_url', 'JACKETT_URL'),
            ('jackett_api_key', 'JACKETT_API_KEY'),
            ('qbittorrent_url', 'QBITTORRENT_URL'),
            ('qbittorrent_username', 'QBITTORRENT_USERNAME'),
            ('qbittorrent_password', 'QBITTORRENT_PASSWORD'),
            ('tmdb_api_key', 'TMDB_API_KEY'),
            ('tmdb_language', 'TMDB_LANGUAGE'),
        ]

        for form_key, config_key in connection_mappings:
            raw_config[config_key] = request.form.get(form_key)
        
        # Database config
        db_defaults = raw_config.get('DATABASE', {})
        db_payload = {
            "ENABLED": True,
            "HOST": _normalize_form_input(request.form, 'db_host') or db_defaults.get('HOST') or "localhost",
            "PORT": _coerce_request_int(_normalize_form_input(request.form, 'db_port') or db_defaults.get('PORT'), 5432),
            "NAME": _normalize_form_input(request.form, 'db_name') or db_defaults.get('NAME') or "jellychecker",
            "USER": _normalize_form_input(request.form, 'db_user') or db_defaults.get('USER') or "",
            "PASSWORD": _normalize_form_input(request.form, 'db_password') or db_defaults.get('PASSWORD') or "",
            "DRIVER": _normalize_form_input(request.form, 'db_driver') or db_defaults.get('DRIVER') or "postgresql+psycopg2",
            "URL": _normalize_form_input(request.form, 'db_url') or db_defaults.get('URL') or "",
            "PARAMS": _normalize_form_input(request.form, 'db_params') or db_defaults.get('PARAMS') or ""
        }
        raw_config["DATABASE"] = _merge_database_settings(db_payload)
        
        # Trakt config
        trakt_defaults = raw_config.get('TRAKT', {})
        trakt_payload = {
            "ENABLED": bool(request.form.get('trakt_enabled')),
            "CLIENT_ID": _normalize_form_input(request.form, 'trakt_client_id') or trakt_defaults.get('CLIENT_ID') or "",
            "ACCESS_TOKEN": _normalize_form_input(request.form, 'trakt_access_token') or trakt_defaults.get('ACCESS_TOKEN') or ""
        }
        raw_config["TRAKT"] = _merge_trakt_settings(trakt_payload)

        # JustWatch config
        justwatch_defaults = raw_config.get('JUSTWATCH', {})
        justwatch_payload = {
            "ENABLED": bool(request.form.get('justwatch_enabled')),
            "LOCALE": _normalize_form_input(request.form, 'justwatch_locale') or justwatch_defaults.get('LOCALE') or "it_IT"
        }
        raw_config["JUSTWATCH"] = _merge_justwatch_settings(justwatch_payload)

        config_write_file(raw_config)
        load_config()
        flash("Configurazione aggiornata")
        return redirect(url_for('dashboard'))

    @app.route('/update-rss-import', methods=['POST'])
    @login_required
    def update_rss_import_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            flash("Config non valida. Completa la configurazione.")
            return redirect(url_for('dashboard'))

        enabled = bool(request.form.get('rss_enabled'))
        poll_interval = _coerce_request_int(request.form.get('rss_poll_interval') or 30, 30)
        poll_interval = max(5, min(1440, poll_interval))
        dedup_keep = request.form.get('rss_dedup_keep') or "oldest"
        dedup_keep = "newest" if dedup_keep == "newest" else "oldest"

        sources = []
        sources_text = request.form.get('rss_sources') or ""
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
                "enabled": True
            })

        payload = {
            "ENABLED": enabled,
            "POLL_INTERVAL_MINUTES": poll_interval,
            "DEDUP_KEEP": dedup_keep,
            "SOURCES": sources
        }
        try:
            _update_app_settings_overrides({"RSS_IMPORT": payload})
        except StorageError as exc:
            flash(f"Errore salvataggio RSS: {exc}")
            return redirect(url_for('dashboard'))
        flash("Configurazione RSS aggiornata")
        return redirect(url_for('dashboard'))

    @app.route('/rss/inspect', methods=['POST'])
    @login_required
    def rss_inspect_route():
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"success": False, "message": "URL mancante"}), 400
        try:
            response = requests.get(url, timeout=12)
            response.raise_for_status()
        except requests.RequestException as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        try:
            inspect = _inspect_rss_content(response.content)
        except ET.ParseError as exc:
            return jsonify({"success": False, "message": f"XML non valido: {exc}"}), 400
        return jsonify({"success": True, "data": inspect})

    @app.route('/rss/inspect-json', methods=['POST'])
    @login_required
    def rss_inspect_json_route():
        if 'json_file' not in request.files:
            return jsonify({"success": False, "message": "File mancante"}), 400
        file = request.files['json_file']
        try:
            payload = json.load(file.stream)
        except (ValueError, json.JSONDecodeError) as exc:
            return jsonify({"success": False, "message": f"JSON non valido: {exc}"}), 400

        root_keys = list(payload.keys()) if isinstance(payload, dict) else []
        items: list[Any] = []
        if isinstance(payload, list):
            items = list(payload)
        elif isinstance(payload, dict):
            for key in ("items", "entries", "results", "data"):
                entry = payload.get(key)
                if isinstance(entry, list):
                    items = list(entry)
                    break

        sample = items[0] if items else {}
        item_keys = list(sample.keys()) if isinstance(sample, dict) else []
        return jsonify({
            "success": True,
            "data": {
                "root_type": type(payload).__name__,
                "root_keys": root_keys,
                "item_count": len(items),
                "item_keys": item_keys
            }
        })

    @app.route('/rss/import', methods=['POST'])
    @login_required
    def rss_import_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Configurazione non valida"}), 400
        db_settings = config.get("DATABASE", {})
        if not _db_enabled(db_settings):
            return jsonify({"success": False, "message": "Database non abilitato"}), 400

        rss_settings = config.get("RSS_IMPORT", {}) or {}
        sources = rss_settings.get("SOURCES") or []
        if not sources:
            return jsonify({"success": False, "message": "Nessuna sorgente RSS configurata"}), 400

        dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"
        try:
            backend = _get_db_backend(db_settings)
        except StorageError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400

        totals = {"items": 0, "inserted": 0, "updated": 0, "skipped": 0, "removed": 0}
        source_results = []
        for source in sources:
            if not source.get("enabled", True):
                continue
            url = (source.get("url") or "").strip()
            if not url:
                continue
            name = (source.get("name") or "").strip()
            tags = source.get("tags") or []
            result = {"name": name or url, "url": url, "items": 0}
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
            except requests.RequestException as exc:
                result["error"] = str(exc)
                source_results.append(result)
                continue
            try:
                parsed = _parse_rss_feed(response.content)
            except ET.ParseError as exc:
                result["error"] = f"XML non valido: {exc}"
                source_results.append(result)
                continue

            channel = parsed.get("channel", {})
            channel_title = (channel.get("title") or "").strip()
            if not name and channel_title:
                name = channel_title
            items = parsed.get("items") or []
            for item in items:
                item["source_name"] = name or channel_title or None
                item["source_url"] = url
                item["source_tags"] = tags
                item["ingested_at"] = datetime.now(timezone.utc)
            result["items"] = len(items)
            try:
                stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
            except StorageError as exc:
                result["error"] = str(exc)
                source_results.append(result)
                continue
            result.update(stats)
            totals["items"] += result["items"]
            totals["inserted"] += stats.get("inserted", 0)
            totals["updated"] += stats.get("updated", 0)
            totals["skipped"] += stats.get("skipped", 0)
            totals["removed"] += stats.get("removed", 0)
            source_results.append(result)

        return jsonify({"success": True, "data": {"summary": totals, "sources": source_results}})

    @app.route('/rss/import-json', methods=['POST'])
    @login_required
    def rss_import_json_route():
        if 'json_file' not in request.files:
            return jsonify({"success": False, "message": "File mancante"}), 400
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Configurazione non valida"}), 400
        db_settings = config.get("DATABASE", {})
        if not _db_enabled(db_settings):
            return jsonify({"success": False, "message": "Database non abilitato"}), 400
        rss_settings = config.get("RSS_IMPORT", {}) or {}
        dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

        file = request.files['json_file']
        try:
            payload = json.load(file.stream)
        except (ValueError, json.JSONDecodeError) as exc:
            return jsonify({"success": False, "message": f"JSON non valido: {exc}"}), 400

        items = _parse_json_import(payload)
        if not items:
            return jsonify({"success": False, "message": "Nessun item trovato"}), 400
        for item in items:
            item["ingested_at"] = datetime.now(timezone.utc)

        try:
            backend = _get_db_backend(db_settings)
        except StorageError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        try:
            stats = backend.save_rss_items(items, dedup_keep=dedup_keep)
        except StorageError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        stats["items"] = len(items)
        return jsonify({"success": True, "data": {"summary": stats}})

    @app.route('/rss/deduplicate', methods=['POST'])
    @login_required
    def rss_deduplicate_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Configurazione non valida"}), 400
        db_settings = config.get("DATABASE", {})
        if not _db_enabled(db_settings):
            return jsonify({"success": False, "message": "Database non abilitato"}), 400
        rss_settings = config.get("RSS_IMPORT", {}) or {}
        dedup_keep = rss_settings.get("DEDUP_KEEP") or "newest"

        try:
            backend = _get_db_backend(db_settings)
        except StorageError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        stats = backend.dedupe_rss_items(dedup_keep=dedup_keep)
        return jsonify({"success": True, "data": stats})

    @app.route('/rss/items', methods=['GET'])
    @login_required
    def rss_items_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Configurazione non valida"}), 400
        db_settings = config.get("DATABASE", {})
        if not _db_enabled(db_settings):
            return jsonify({"success": False, "message": "Database non abilitato"}), 400

        limit = _coerce_request_int(request.args.get("limit") or 50, 50)
        offset = _coerce_request_int(request.args.get("offset") or 0, 0)
        limit = max(1, min(200, limit))
        offset = max(0, offset)
        try:
            backend = _get_db_backend(db_settings)
        except StorageError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        payload = backend.list_rss_items(limit=limit, offset=offset)
        payload["limit"] = limit
        payload["offset"] = offset
        return jsonify({"success": True, "data": payload})

    @app.route('/update-rules', methods=['POST'])
    @login_required
    def update_rules_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            flash("Config non valida. Controlla le connessioni.")
            return redirect(url_for('dashboard'))
        
        target_langs = _split_csv_field(request.form.get('target_languages'))
        exclude_tags = _split_csv_field(request.form.get('exclude_tags'))

        base_rules = config.get('SEARCH_RULES') or _default_search_rules()
        rules = copy.deepcopy(base_rules)
        
        # Boolean rules mappings
        bool_rules = [
            ('use_original_title', 'use_original_title'),
            ('use_alt_titles_original', 'use_alt_titles_original'),
            ('sanitize_titles', 'sanitize_titles'),
            ('ignore_year_for_tv', 'ignore_year_for_tv'),
            ('require_audio_language', 'require_audio_language'),
            ('include_target_lang_base', 'include_target_lang_base'),
            ('search_episode_variants', 'search_episode_variants'),
            ('skip_available_content', 'skip_available_content'),
            ('skip_unreleased_content', 'skip_unreleased_content'),
        ]
        
        for form_key, rule_key in bool_rules:
            rules[rule_key] = bool(request.form.get(form_key))
        
        # Conditional logic for episode search
        if rules['search_episode_variants']:
            rules['skip_season_queries_when_episode_search'] = bool(request.form.get('skip_season_query_when_episode_search'))
        else:
            rules['skip_season_queries_when_episode_search'] = False
        
        # Integer rules
        rules['min_seeders'] = max(0, _coerce_request_int(request.form.get('min_seeders') or 0))
        
        # List rules
        rules['query_terms'] = _split_csv_field(request.form.get('query_terms'))
        rules['filter_terms'] = _split_csv_field(request.form.get('filter_terms'))
        rules['season_templates'] = _split_csv_field(request.form.get('season_templates')) or DEFAULT_CONFIG['SEARCH_RULES']['season_templates']
        
        # Language rules
        use_alt_language = bool(request.form.get('use_alt_titles_language'))
        selected_language = request.form.get('alt_titles_language') or 'all'
        if selected_language == 'custom':
            custom_value = request.form.get('alt_titles_language_custom', '').strip().lower()
            selected_language = custom_value or 'all'
        rules['use_alt_titles_language'] = use_alt_language
        rules['alt_titles_language'] = selected_language if use_alt_language else 'disabled'
        
        # Provider rules
        rules['use_prowlarr'] = bool(request.form.get('use_prowlarr'))
        rules['use_jackett'] = bool(request.form.get('use_jackett'))
        
        # Legacy sort
        legacy_sort_value = request.form.get('results_sort')
        if legacy_sort_value:
            rules['results_sort'] = legacy_sort_value

        # Sort modes
        tv_primary_raw = request.form.get('tv_sort_primary')
        tv_secondary_raw = request.form.get('tv_sort_secondary')
        movie_primary_raw = request.form.get('movie_sort_primary')
        movie_secondary_raw = request.form.get('movie_sort_secondary')

        rules['tv_sort_primary'] = _clean_sort_mode(
            tv_primary_raw if tv_primary_raw is not None else rules.get('tv_sort_primary'),
            TV_SORT_KEYS,
            base_rules.get('tv_sort_primary') or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
        )
        rules['tv_sort_secondary'] = _clean_sort_mode(
            tv_secondary_raw if tv_secondary_raw is not None else rules.get('tv_sort_secondary'),
            TV_SORT_KEYS,
            base_rules.get('tv_sort_secondary') or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
            allow_empty=True
        )
        rules['movie_sort_primary'] = _clean_sort_mode(
            movie_primary_raw if movie_primary_raw is not None else rules.get('movie_sort_primary'),
            MOVIE_SORT_KEYS,
            base_rules.get('movie_sort_primary') or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
        )
        rules['movie_sort_secondary'] = _clean_sort_mode(
            movie_secondary_raw if movie_secondary_raw is not None else rules.get('movie_sort_secondary'),
            MOVIE_SORT_KEYS,
            base_rules.get('movie_sort_secondary') or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
            allow_empty=True
        )

        rules = _normalize_sort_settings(rules)

        try:
            _update_app_settings_overrides({
                "TARGET_LANGUAGES": target_langs,
                "EXCLUDE_TAGS": exclude_tags,
                "SEARCH_RULES": rules
            })
        except StorageError as exc:
            flash(f"Errore salvataggio regole: {exc}")
            return redirect(url_for('dashboard'))

        global _ACTIVE_CONFIG
        if _ACTIVE_CONFIG is None:
            _ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
        _ACTIVE_CONFIG["TARGET_LANGUAGES"] = target_langs
        _ACTIVE_CONFIG["EXCLUDE_TAGS"] = exclude_tags
        _ACTIVE_CONFIG["SEARCH_RULES"] = rules
        flash("Regole aggiornate con successo")
        return redirect(url_for('dashboard'))

    @app.route('/update-request-rules', methods=['POST'])
    @login_required
    def update_request_rules_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        payload = request.get_json(silent=True) or {}
        rules_payload = payload.get('rules')
        if not isinstance(rules_payload, list):
            return jsonify({"success": False, "message": "Formato non valido"}), 400
        base_req_rules = config.get('REQUEST_RULES') or {}
        request_rules = base_req_rules.copy()
        base_search_rules = config.get('SEARCH_RULES') or _default_search_rules()
        for entry in rules_payload:
            req_id = entry.get('request_id')
            if req_id is None:
                continue
            key = str(req_id)
            query_terms = _sanitize_terms_list(entry.get('query_terms'))
            filter_terms = _sanitize_terms_list(entry.get('filter_terms'))
            exclude_terms = _sanitize_terms_list(entry.get('exclude_terms'))
            enabled = entry.get('enabled')
            if isinstance(enabled, str):
                enabled = enabled.lower() not in ("false", "0", "no")
            elif enabled is None:
                enabled = True if (query_terms or filter_terms or exclude_terms) else True
            else:
                enabled = bool(enabled)
            use_original_title = _coerce_request_bool(entry.get("use_original_title"), base_search_rules.get("use_original_title", True))
            use_alt_titles_original = _coerce_request_bool(entry.get("use_alt_titles_original"), base_search_rules.get("use_alt_titles_original", True))
            use_alt_titles_language = _coerce_request_bool(entry.get("use_alt_titles_language"), base_search_rules.get("use_alt_titles_language", False))
            alt_lang_default = (base_search_rules.get("alt_titles_language") or "all").lower()
            alt_titles_language = _normalize_alt_language(entry.get("alt_titles_language"), alt_lang_default)
            if not use_alt_titles_language:
                alt_titles_language = alt_lang_default
            year_variance = _coerce_request_int(entry.get("year_variance"), 0, 0, 10)

            has_custom = bool(
                query_terms or filter_terms or exclude_terms or not enabled or
                use_original_title != base_search_rules.get("use_original_title", True) or
                use_alt_titles_original != base_search_rules.get("use_alt_titles_original", True) or
                use_alt_titles_language != base_search_rules.get("use_alt_titles_language", False) or
                (use_alt_titles_language and alt_titles_language != alt_lang_default) or
                year_variance > 0
            )

            if not has_custom:
                if key in request_rules:
                    del request_rules[key]
                continue

            request_rules[key] = {
                "enabled": enabled,
                "query_terms": query_terms,
                "filter_terms": filter_terms,
                "exclude_terms": exclude_terms,
                "use_original_title": use_original_title,
                "use_alt_titles_original": use_alt_titles_original,
                "use_alt_titles_language": use_alt_titles_language,
                "alt_titles_language": alt_titles_language,
                "year_variance": year_variance
            }
        try:
            backend = _ensure_db_backend()
            backend.save_request_rules(request_rules)
        except StorageError as exc:
            return jsonify({"success": False, "message": f"Errore DB: {exc}"}), 500
        global _ACTIVE_CONFIG
        if _ACTIVE_CONFIG is None:
            _ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
        _ACTIVE_CONFIG["REQUEST_RULES"] = request_rules
        _refresh_request_overview_rules(config)
        return jsonify({"success": True, "message": "Regole per le richieste aggiornate"})

    @app.route('/refresh-requests', methods=['POST'])
    @login_required
    def refresh_requests_route():
        config, is_valid = load_config()
        if not is_valid:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        overview = _summarize_requests_for_dashboard(config)
        _save_cached_requests_overview(overview)
        tv_list = [req for req in overview if (req.get("media_type") or "").lower() == "tv"]
        movies_list = [req for req in overview if (req.get("media_type") or "").lower() in ("movie", "movies", "film", "")]
        return jsonify({
            "success": True,
            "message": "Lista aggiornata da Jellyseerr.",
            "counts": {
                "total": len(overview),
                "tv": len(tv_list),
                "movies": len(movies_list)
            }
        })

    @app.route('/update-scheduler', methods=['POST'])
    @login_required
    def update_scheduler_route():
        config, is_valid = load_config()
        if not is_valid or not config:
            flash("Config non valida.")
            return redirect(url_for('dashboard'))
        current = config.get("AUTO_TASKS") or _default_auto_tasks()
        updated = copy.deepcopy(current)
        updated["scan"] = _parse_auto_task_payload(request.form, "scan", current.get("scan", _default_auto_tasks()["scan"]))
        updated["refresh"] = _parse_auto_task_payload(request.form, "refresh", current.get("refresh", _default_auto_tasks()["refresh"]))
        try:
            _update_app_settings_overrides({"AUTO_TASKS": updated})
        except StorageError as exc:
            flash(f"Errore salvataggio automazioni: {exc}")
            return redirect(url_for('dashboard'))
        global _ACTIVE_CONFIG
        if _ACTIVE_CONFIG is None:
            _ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
        _ACTIVE_CONFIG["AUTO_TASKS"] = updated
        config["AUTO_TASKS"] = updated
        _sync_auto_scheduler(is_valid)
        flash("Automazioni aggiornate")
        return redirect(url_for('dashboard'))

    @app.route('/run-scan', methods=['POST'])
    @login_required
    def trigger_scan():
        config, is_valid = load_config()
        if not is_valid:
            flash("Config non valida. Completa la configurazione.")
            return redirect(url_for('dashboard'))
        if not validate_connections(config):
            flash("Connessioni non valide. Controlla i log.")
            return redirect(url_for('dashboard'))
        expects_json = request.is_json
        targets_payload = None
        if expects_json:
            payload = request.get_json(silent=True) or {}
            targets_payload = payload.get("targets") or payload.get("request_ids")
        else:
            selected_ids = request.form.getlist('request_ids')
            if selected_ids:
                targets_payload = [{"request_id": rid} for rid in selected_ids]
        started = scan_manager.start_scan(config, targets_payload, process_requests_func=process_requests)
        message = 'Ricerca avviata!' if started else 'Una ricerca è già in esecuzione.'
        if expects_json:
            status_code = 200 if started else 409
            return jsonify({"success": started, "message": message}), status_code
        if not started:
            flash("Una ricerca è già in esecuzione.")
            return redirect(url_for('dashboard'))
        flash(message)
        return redirect(url_for('dashboard'))

    @app.route('/stop-scan', methods=['POST'])
    @login_required
    def stop_scan_route():
        scan_manager.stop_scan()
        flash("Richiesta di stop inviata.")
        return redirect(url_for('dashboard'))

    @app.route('/send-torrent', methods=['POST'])
    @login_required
    def send_torrent_route():
        config, is_valid = load_config()
        if not is_valid:
            return jsonify({"success": False, "message": "Config non valida"}), 400
        data = request.get_json(silent=True) or {}
        link = data.get("link")
        if not link:
            return jsonify({"success": False, "message": "Link mancante"}), 400
        success, message = send_to_qbittorrent(link, config)
        status_code = 200 if success else 500
        return jsonify({"success": success, "message": message}), status_code

    @app.route('/scan-status')
    @login_required
    def scan_status_route():
        return jsonify(scan_manager.get_status())

    @app.route('/test-connections', methods=['POST'])
    @login_required
    def test_connections_route():
        config, is_valid = load_config()
        if not config:
            return jsonify({"success": False, "message": "Config mancante"}), 400

        jelly_ok, jelly_msg = _ping_jellyseerr(config)
        prowlarr_ok, prowlarr_msg = _ping_prowlarr(config)

        qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
        if qb_configured:
            qb_ok, qb_msg = _ping_qbittorrent(config)
        else:
            qb_ok, qb_msg = False, "Non configurato"
        db_ok, db_msg, _ = _ping_database(config)
        trakt_ok, trakt_msg, trakt_configured = _ping_trakt(config)
        jack_ok, jack_msg, jack_configured = _ping_jackett(config)
        justwatch_ok, justwatch_msg, justwatch_configured = _ping_justwatch(config)

        return jsonify({
            "success": True,
            "statuses": {
                "jellyseerr": {"ok": jelly_ok, "message": jelly_msg},
                "prowlarr": {"ok": prowlarr_ok, "message": prowlarr_msg},
                "qbittorrent": {"ok": qb_ok, "message": qb_msg, "configured": qb_configured},
                "jackett": {"ok": jack_ok, "message": jack_msg, "configured": jack_configured},
                "trakt": {"ok": trakt_ok, "message": trakt_msg, "configured": trakt_configured},
                "justwatch": {"ok": justwatch_ok, "message": justwatch_msg, "configured": justwatch_configured},
                "database": {"ok": db_ok, "message": db_msg}
            }
        })

    @app.route('/trakt/device/start', methods=['POST'])
    @login_required
    def trakt_device_start():
        """Start Trakt device authorization flow."""
        try:
            data = request.get_json() or {}
            client_id = (data.get('client_id') or '').strip()

            if not client_id:
                return jsonify({"success": False, "message": "Client ID mancante"}), 400

            # Request device code from Trakt
            response = requests.post(
                'https://api.trakt.tv/oauth/device/code',
                headers={
                    'Content-Type': 'application/json'
                },
                json={'client_id': client_id},
                timeout=10
            )

            if response.status_code != 200:
                return jsonify({
                    "success": False,
                    "message": f"Errore Trakt: {response.status_code}"
                }), 400

            result = response.json()
            return jsonify({
                "success": True,
                "device_code": result.get('device_code'),
                "user_code": result.get('user_code'),
                "verification_url": result.get('verification_url'),
                "expires_in": result.get('expires_in'),
                "interval": result.get('interval')
            })

        except Exception as exc:
            print(f"   -> Errore avvio device flow Trakt: {exc}")
            return jsonify({"success": False, "message": str(exc)}), 500

    @app.route('/trakt/device/poll', methods=['POST'])
    @login_required
    def trakt_device_poll():
        """Poll Trakt for device authorization status."""
        try:
            data = request.get_json() or {}
            client_id = (data.get('client_id') or '').strip()
            device_code = (data.get('device_code') or '').strip()

            if not client_id or not device_code:
                return jsonify({"success": False, "message": "Parametri mancanti"}), 400

            # Poll Trakt for token
            response = requests.post(
                'https://api.trakt.tv/oauth/device/token',
                headers={
                    'Content-Type': 'application/json'
                },
                json={
                    'code': device_code,
                    'client_id': client_id
                },
                timeout=10
            )

            if response.status_code == 400:
                # Still waiting for user authorization
                return jsonify({"status": "pending"})

            if response.status_code == 404:
                # Invalid device code
                return jsonify({
                    "success": False,
                    "message": "Codice device non valido o scaduto"
                }), 404

            if response.status_code == 410:
                # Code expired
                return jsonify({
                    "success": False,
                    "message": "Codice scaduto"
                }), 410

            if response.status_code != 200:
                return jsonify({
                    "success": False,
                    "message": f"Errore Trakt: {response.status_code}"
                }), 400

            result = response.json()
            access_token = result.get('access_token')
            expires_in = result.get('expires_in', 7776000)  # Default 90 days

            if not access_token:
                return jsonify({
                    "success": False,
                    "message": "Token non ricevuto"
                }), 500

            # Calculate expiration timestamp
            from datetime import datetime, timedelta, timezone
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            try:
                raw_config = read_raw_config() or {}
                trakt_config = raw_config.get('TRAKT', {})
                trakt_config['CLIENT_ID'] = client_id
                trakt_config['ACCESS_TOKEN'] = access_token
                trakt_config['ENABLED'] = True
                trakt_config['EXPIRES_AT'] = expires_at.isoformat()
                raw_config['TRAKT'] = trakt_config
                config_write_file(raw_config)
                load_config()
            except Exception as exc:
                print(f"   -> Errore salvataggio token Trakt: {exc}")

            return jsonify({
                "status": "authorized",
                "access_token": access_token,
                "expires_at": expires_at.isoformat()
            })

        except Exception as exc:
            print(f"   -> Errore polling device flow Trakt: {exc}")
            return jsonify({"success": False, "message": str(exc)}), 500

    @app.route('/trakt/clear', methods=['POST'])
    @login_required
    def trakt_clear():
        """Clear Trakt access token from configuration."""
        try:
            raw_config = read_raw_config() or {}
            trakt_config = raw_config.get('TRAKT', {})

            # Clear access token
            trakt_config['ACCESS_TOKEN'] = ''
            trakt_config['ENABLED'] = False

            raw_config['TRAKT'] = trakt_config
            config_write_file(raw_config)

            return jsonify({
                "success": True,
                "message": "Token Trakt rimosso"
            })

        except Exception as exc:
            print(f"   -> Errore rimozione token Trakt: {exc}")
            return jsonify({"success": False, "message": str(exc)}), 500

    return app

def run_dashboard_server():
    """Avvia una semplice interfaccia web per consultare risultati e modificare regole di ricerca."""
    app = create_dashboard_app()
    print("Avvio dashboard su http://127.0.0.1:5050 (Ctrl+C per uscire)")
    app.run(host='127.0.0.1', port=5050)


def parse_args():
    parser = argparse.ArgumentParser(description="OctoHub")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Avvia l'interfaccia web per risultati e regole di ricerca"
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Forza l'apertura della pagina di configurazione"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Esegue immediatamente lo scan da linea di comando"
    )
    return parser.parse_args()

# --- FUNZIONI CORE ---

def validate_connections(config):
    """Verifica rapidamente che Jellyseerr, gli indexer e il database rispondano."""
    print("0. Controllo configurazione e collegamenti...")
    jelly_ok = _check_jellyseerr_connection(config)
    rules = _search_rules(config)
    provider_available = True
    prowlarr_ok = True
    jackett_ok = True
    prowlarr_required = rules.get("use_prowlarr", True)
    jackett_required = rules.get("use_jackett", False)
    if prowlarr_required:
        if not _prowlarr_configured(config):
            print("   -> Le regole richiedono Prowlarr ma non risulta configurato.")
            provider_available = False
            prowlarr_ok = False
        else:
            prowlarr_ok = _check_prowlarr_connection(config)
    if jackett_required:
        if not _jackett_configured(config):
            print("   -> Le regole richiedono Jackett ma non risulta configurato.")
            provider_available = False
            jackett_ok = False
        else:
            jackett_ok = _check_jackett_connection(config)
    if not prowlarr_required and not jackett_required:
        print("   -> Nessun indexer attivo: abilita almeno Prowlarr o Jackett.")
        provider_available = False
    db_ok = _check_database_connection(config)
    qb_configured = all(config.get(k) for k in ["QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD"])
    if qb_configured:
        _check_qbittorrent_connection(config)

    if jelly_ok and prowlarr_ok and jackett_ok and db_ok and provider_available:
        print("   -> Connessioni a Jellyseerr, indexer e database verificate. Procedo.\n")
        return True
    print("   -> Configurazione incompleta o servizi non raggiungibili: correggi e riprova.\n")
    return False

def _ping_jackett(config):
    if not _jackett_configured(config):
        return False, "Non configurato", False
    base_url = config["JACKETT_URL"].rstrip("/")
    params = {"apikey": config["JACKETT_API_KEY"]}
    url = f"{base_url}/api/v2.0/indexers"
    ok, message = _ping_api_service(url, params=params)
    return ok, message, True

def _ping_trakt(config):
    settings = _merge_trakt_settings((config or {}).get("TRAKT"))
    if not _trakt_enabled(settings):
        return False, "Non configurato", False
    client = _get_trakt_client(settings)
    if not client:
        return False, "Configurazione non valida", False
    try:
        client.ping()
        return True, "Connessione OK", True
    except TraktAPIError as exc:
        return False, str(exc), True

def _ping_justwatch(config):
    settings = _merge_justwatch_settings((config or {}).get("JUSTWATCH"))
    if not _justwatch_enabled(settings):
        return False, "Non configurato", False
    if not is_justwatch_available():
        return False, "Libreria JustWatch non installata", True
    manager = _get_justwatch_manager(settings)
    if not manager:
        return False, "JustWatch non disponibile", True
    locale = settings.get("LOCALE") or "it_IT"
    return True, f"Locale {locale}", True

def _check_service_connection(ping_func, config, service_name, error_message_template, show_success=False):
    """
    Funzione generica per verificare la connessione a un servizio.

    Args:
        ping_func: Funzione di ping da chiamare (es. _ping_jellyseerr)
        config: Configurazione del servizio
        service_name: Nome del servizio per i messaggi di log
        error_message_template: Template del messaggio di errore
        show_success: Se True, mostra un messaggio anche in caso di successo

    Returns:
        bool: True se la connessione è riuscita, False altrimenti
    """
    result = ping_func(config)

    # Gestisce sia tuple a 2 che a 3 elementi (alcuni ping ritornano anche configured)
    if len(result) == 3:
        ok, message, configured = result
        if not configured:
            return True
    else:
        ok, message = result
        configured = True

    if not ok:
        print(f"   -> {error_message_template}: {message}")
    elif show_success and configured:
        print(f"   -> {service_name} raggiungibile.")

    return ok

def _check_jellyseerr_connection(config):
    return _check_service_connection(
        _ping_jellyseerr,
        config,
        "Jellyseerr",
        "Jellyseerr non risponde (controlla URL o API key)"
    )

def _check_prowlarr_connection(config):
    return _check_service_connection(
        _ping_prowlarr,
        config,
        "Prowlarr",
        "Prowlarr non risponde (controlla URL o API key)"
    )

def _check_jackett_connection(config):
    return _check_service_connection(
        _ping_jackett,
        config,
        "Jackett",
        "Jackett non risponde (controlla URL o API key)",
        show_success=True
    )

def _check_qbittorrent_connection(config):
    return _check_service_connection(
        _ping_qbittorrent,
        config,
        "qBittorrent",
        "qBittorrent non risponde (controlla URL o credenziali)",
        show_success=True
    )

def _check_database_connection(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return True
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return True
        ok, message = backend.test_connection()
        if not ok:
            print(f"   -> Database non raggiungibile: {message}")
        else:
            print("   -> Database raggiungibile.")
        return ok
    except StorageError as exc:
        print(f"   -> Database non utilizzabile: {exc}")
        return False

def _ping_database(config):
    settings = _merge_database_settings(config.get("DATABASE")) if config else DEFAULT_CONFIG["DATABASE"]
    if not _db_enabled(settings):
        return False, "Database non configurato", False
    try:
        backend = _get_db_backend(settings)
        if not backend:
            return False, "Database non disponibile", True
        ok, message = backend.test_connection()
        return ok, message or "Connessione OK", True
    except StorageError as exc:
        return False, str(exc), True

# Nota: fetch_request_details, fetch_media_info, _extract_tmdb_id, _fetch_tmdb_payload sono ora importate da api_clients.py
# Nota: extract_title_and_year, gather_title_candidates, build_search_queries, filter_results sono ora importate da scanner.py

def _collect_metadata_sources(source):
    """Still used by other functions in checker.py that haven't been moved yet."""
    collected = []
    if not isinstance(source, dict) or not source:
        return collected
    collected.append(source)
    media_info = source.get("mediaInfo") if isinstance(source.get("mediaInfo"), dict) else None
    media = source.get("media") if isinstance(source.get("media"), dict) else None
    if media_info:
        collected.append(media_info)
    if media:
        collected.append(media)
    return collected

def _collect_season_entries(*sources):
    entries = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        seasons = source.get("seasons")
        if isinstance(seasons, list):
            entries.extend(seasons)
        media = source.get("media") if isinstance(source.get("media"), dict) else None
        if media:
            media_seasons = media.get("seasons")
            if isinstance(media_seasons, list):
                entries.extend(media_seasons)
    return entries

def _coerce_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "available", "completed", "done", "downloaded", "ready"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return False

def _is_status_available(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 5
    if isinstance(value, str):
        return value.lower() in {"available", "fulfilled", "completed", "done", "downloaded", "ready"}
    return False

def _is_episode_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    status_fields = [
        entry.get("status"),
        entry.get("state"),
        entry.get("status4k"),
        entry.get("downloadStatus"),
        entry.get("downloadStatus4k"),
        entry.get("availability")
    ]
    bool_fields = [
        entry.get("available"),
        entry.get("hasFile"),
        entry.get("hasFile4k"),
        entry.get("isAvailable"),
        entry.get("downloaded")
    ]
    media_info = entry.get("mediaInfo") if isinstance(entry.get("mediaInfo"), dict) else None
    if media_info:
        bool_fields.extend([
            media_info.get("available"),
            media_info.get("hasFile"),
            media_info.get("hasFile4k")
        ])
    if any(_coerce_truthy(value) for value in bool_fields if value is not None):
        return True
    for value in status_fields:
        if _is_status_available(value):
            return True
    return False

def _is_season_entry_available(entry):
    if not isinstance(entry, dict):
        return False
    if _is_status_available(entry.get("status")) or _is_status_available(entry.get("state")) or _is_status_available(entry.get("status4k")):
        return True
    if _coerce_truthy(entry.get("available")):
        return True
    episodes = entry.get("episodes")
    if isinstance(episodes, list) and episodes:
        pending = [ep for ep in episodes if not _is_episode_entry_available(ep)]
        return len(pending) == 0
    return False

def _collect_request_season_payloads(request_item, include_related=False):
    payloads = []
    def _collect_from(source):
        if not isinstance(source, dict):
            return
        for key in ("seasonRequests", "seasons"):
            values = source.get(key)
            if isinstance(values, list):
                for entry in values:
                    if isinstance(entry, dict):
                        payloads.append(entry)
                    else:
                        payloads.append({"seasonNumber": entry})
    _collect_from(request_item)
    if include_related:
        _collect_from(request_item.get("media"))
        _collect_from(request_item.get("mediaInfo"))
    return payloads

def _describe_trakt_episode_statuses(request_item, season_number):
    if season_number is None:
        return None
    settings = _active_trakt_settings()
    if not _trakt_enabled(settings):
        return None
    tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not tmdb_id:
        print(f"   -> Trakt: impossibile determinare TMDB per stagione {season_number}")
        return None
    client = _get_trakt_client(settings)
    if not client:
        return None
    try:
        print(f"   -> Trakt: recupero episodi per TMDB {tmdb_id} stagione {season_number}")
        trakt_payload = client.get_season(tmdb_id, season_number)
    except TraktAPIError as exc:
        print(f"   -> Trakt: errore stagione {season_number} per TMDB {tmdb_id}: {exc}")
        return None
    if trakt_payload is None:
        return []
    try:
        collection_map = client.get_collection_map()
    except TraktAPIError as exc:
        print(f"   -> Trakt: impossibile recuperare collezione: {exc}")
        collection_map = {}
    collected = set()
    if collection_map:
        collected = collection_map.get(tmdb_id, {}).get(season_number, set()) or set()
    described = []
    now = datetime.now(timezone.utc)
    for ep in trakt_payload or []:
        if not isinstance(ep, dict):
            continue
        ep_number = _try_parse_int(ep.get("number"))
        if ep_number is None:
            continue
        release_dt = _parse_date_value(ep.get("first_aired"))
        if ep_number in collected:
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "trakt" if release_dt else None
        })
    described.sort(key=lambda item: item["episode"])
    print(f"   -> Trakt: trovati {len(described)} episodi per TMDB {tmdb_id} S{season_number:02d}")
    return _apply_justwatch_overrides(request_item, season_number, described)

def _resolve_justwatch_show_metadata(request_item):
    sources = _collect_metadata_sources(request_item)
    title, year = extract_title_and_year(request_item, extra_sources=sources)
    if not title:
        fallback_sources = [request_item, request_item.get("media"), request_item.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    if not title:
        tmdb_id = _extract_tmdb_id(request_item, request_item.get("media"), request_item.get("mediaInfo"))
        if tmdb_id:
            cached = _JUSTWATCH_METADATA_CACHE.get(tmdb_id)
            if cached:
                cached_title, cached_year = cached
                return cached_title, cached_year
            config = _ACTIVE_CONFIG or {}
            if config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"):
                media_type = _normalize_media_type(
                    request_item.get("type") or request_item.get("media", {}).get("mediaType")
                )
                media_payload, _resolved_type = fetch_media_info(
                    {"tmdbId": tmdb_id, "mediaType": media_type},
                    config,
                    _JUSTWATCH_MEDIA_CACHE,
                    media_type
                )
                if media_payload:
                    title, year = extract_title_and_year(media_payload, extra_sources=_collect_metadata_sources(media_payload))
                    if not title:
                        for key in ("title", "name", "originalTitle", "originalName"):
                            candidate = media_payload.get(key)
                            if candidate:
                                title = candidate
                                break
                    if title:
                        parsed_year = _try_parse_int(year) if year is not None else None
                        _JUSTWATCH_METADATA_CACHE[tmdb_id] = (title, parsed_year)
                        return title, parsed_year
    if not year and title:
        year = _extract_year_from_title(str(title))
    parsed_year = _try_parse_int(year) if year is not None else None
    return title, parsed_year

def _apply_justwatch_overrides(request_item, season_number, described):
    if season_number is None or not described:
        return described
    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return described
    manager = _get_justwatch_manager(settings)
    if not manager:
        return described
    show_name, year = _resolve_justwatch_show_metadata(request_item)
    if not show_name:
        print(f"   -> JustWatch: titolo non disponibile per stagione S{season_number:02d}")
        return described
    print(f"   -> JustWatch: verifica {show_name} S{season_number:02d} ({len(described)} episodi)")
    updated = []
    for entry in described:
        status = entry.get("status")
        if status == "available":
            updated.append(entry)
            continue
        if status == "unreleased":
            updated.append(entry)
            continue
        ep_number = entry.get("episode")
        if ep_number is None:
            updated.append(entry)
            continue
        try:
            is_available, providers = manager.check_availability_details(
                show_name,
                season_number,
                ep_number,
                year=year
            )
            updated_entry = dict(entry)
            updated_entry["justwatch_checked"] = True
            updated_entry["justwatch_available"] = bool(is_available)
            if is_available:
                updated_entry["justwatch"] = True
                if providers:
                    updated_entry["justwatch_providers"] = providers
                print(f"   -> JustWatch: disponibile {show_name} S{season_number:02d}E{int(ep_number):02d}")
            elif providers:
                updated_entry["justwatch_providers"] = providers
            updated.append(updated_entry)
        except JustWatchError as exc:
            print(f"   -> JustWatch: errore verifica {show_name} S{season_number:02d}E{ep_number}: {exc}")
            return described
    return updated

def describe_episode_statuses(request_item, season_number):
    requested = set(extract_request_seasons(request_item, skip_available=False))
    if season_number is None or season_number not in requested:
        return []
    season_payloads = _collect_request_season_payloads(request_item, include_related=True)
    best_entry = None
    for entry in season_payloads:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if best_entry is None:
            best_entry = entry
            continue
        existing_eps = best_entry.get("episodes") if isinstance(best_entry.get("episodes"), list) else None
        if isinstance(episodes, list) and episodes:
            if not existing_eps:
                best_entry = entry
            elif len(episodes) > len(existing_eps):
                best_entry = entry
    related_sources = [src for src in (request_item, request_item.get("media"), request_item.get("mediaInfo")) if isinstance(src, dict)]
    def _placeholder(count):
        if not count:
            return []
        return [{"episode": idx, "status": "pending", "release": None} for idx in range(1, count + 1)]
    trakt_details = None
    if not best_entry:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    episodes = best_entry.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        if trakt_details is None:
            trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details is not None:
            return trakt_details
        count = get_episode_count_for_season(related_sources, season_number)
        return _apply_justwatch_overrides(request_item, season_number, _placeholder(count))
    described = []
    trakt_details = None
    now = datetime.now(timezone.utc)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        ep_number = ep.get("episodeNumber") or ep.get("episode") or ep.get("number")
        ep_number = _try_parse_int(ep_number)
        if ep_number is None:
            continue
        release_value = ep.get("airDate") or ep.get("releaseDate") or ep.get("availableDate") or ep.get("firstAired")
        release_dt = _parse_date_value(release_value)
        if _is_episode_entry_available(ep):
            status = "available"
        elif release_dt and release_dt > now:
            status = "unreleased"
        else:
            status = "pending"
        described.append({
            "episode": ep_number,
            "status": status,
            "release": release_dt.strftime("%Y-%m-%d") if release_dt else None,
            "release_source": "tmdb" if release_dt else None
        })
    described.sort(key=lambda item: item["episode"])
    if not described:
        trakt_details = _describe_trakt_episode_statuses(request_item, season_number)
        if trakt_details:
            return trakt_details
    return _apply_justwatch_overrides(request_item, season_number, described)

def get_pending_episode_numbers(request_item, season_number):
    if season_number is None:
        return None
    details = describe_episode_statuses(request_item, season_number)
    if not details:
        return None
    pending = [entry["episode"] for entry in details if entry["status"] == "pending"]
    return sorted(set(pending))

def describe_season_statuses(request_item):
    seasons = extract_request_seasons(request_item, skip_available=False)
    if not seasons:
        return []
    release_map = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    described = []
    status_labels = {
        "available": "Disponibile",
        "partial": "Parzialmente disponibile",
        "pending": "Non disponibile",
        "unreleased": "Non ancora pubblicata",
        "unknown": "Stato sconosciuto"
    }
    status_classes = {
        "available": "info",
        "partial": "warn",
        "pending": "warn",
        "unreleased": "skip",
        "unknown": ""
    }
    for season in sorted(seasons):
        episodes = describe_episode_statuses(request_item, season)
        release_dt = release_map.get(season)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        total_eps = len(episodes)
        available_eps = len([ep for ep in episodes if ep["status"] == "available"])
        pending_eps = len([ep for ep in episodes if ep["status"] == "pending"])
        unreleased_eps = len([ep for ep in episodes if ep["status"] == "unreleased"])
        if release_dt and release_dt > datetime.now(timezone.utc) and available_eps == 0 and pending_eps == 0:
            status = "unreleased"
        elif total_eps == 0:
            pending_list = get_pending_episode_numbers(request_item, season)
            if pending_list is None:
                status = "unknown"
            elif len(pending_list) == 0:
                status = "available"
            else:
                status = "pending"
            pending_values = pending_list or []
        else:
            if available_eps == total_eps and total_eps > 0:
                status = "available"
            elif available_eps == 0 and pending_eps > 0:
                status = "pending"
            elif pending_eps == 0 and available_eps == 0 and unreleased_eps > 0:
                status = "unreleased"
            elif available_eps > 0 and pending_eps > 0:
                status = "partial"
            else:
                status = "partial"
            pending_values = [ep["episode"] for ep in episodes if ep["status"] == "pending"]
        described.append({
            "season": season,
            "status": status,
            "status_display": status_labels.get(status, status),
            "status_class": status_classes.get(status, ""),
            "pending": pending_values,
            "missing_count": len(pending_values),
            "release": release_label,
            "episodes": episodes,
            "episodes_total": total_eps,
            "available_count": available_eps,
            "pending_count": pending_eps,
            "unreleased_count": unreleased_eps
        })
    return described

def select_scan_seasons(season_statuses, skip_available, skip_unreleased):
    if not season_statuses:
        return []
    selected = []
    for entry in season_statuses:
        status = entry.get("status")
        if skip_available and status == "available":
            continue
        if skip_unreleased and status == "unreleased":
            continue
        selected.append(entry.get("season"))
    return [season for season in selected if season is not None]

# Nota: _parse_date_value è ora importata da utils.py

def _find_release_date(*sources):
    date_keys = [
        "airDate",
        "releaseDate",
        "inCinemaDate",
        "physicalRelease",
        "digitalRelease",
        "firstAirDate",
        "startDate",
        "start_date"
    ]
    best = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in date_keys:
            candidate = _parse_date_value(source.get(key))
            if candidate and (best is None or candidate < best):
                best = candidate
    return best

def _season_release_map(*sources):
    mapping = {}
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return mapping
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        season_number = _try_parse_int(entry.get("seasonNumber") or entry.get("season") or entry.get("number"))
        if season_number is None:
            continue
        date_value = entry.get("airDate") or entry.get("releaseDate") or entry.get("firstAirDate")
        parsed = _parse_date_value(date_value)
        if parsed:
            mapping[season_number] = parsed
    return mapping

def _request_release_date(request_item):
    sources = _collect_metadata_sources(request_item)
    return _find_release_date(*sources)

def _is_request_unreleased(request_item):
    release_date = _request_release_date(request_item)
    if release_date:
        return release_date > datetime.now(timezone.utc)
    return False

def _filter_unreleased_seasons(request_item, seasons):
    if not seasons:
        return seasons
    mapping = _season_release_map(request_item, request_item.get("media"), request_item.get("mediaInfo"))
    if not mapping:
        return seasons
    now = datetime.now(timezone.utc)
    filtered = []
    for season in seasons:
        if mapping.get(season) and mapping[season] > now:
            continue
        filtered.append(season)
    return filtered

def get_episode_count_for_season(sources, season_number):
    if season_number is None:
        return None
    season_entries = _collect_season_entries(*sources)
    if not season_entries:
        return None
    for entry in season_entries:
        if not isinstance(entry, dict):
            continue
        entry_number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        entry_number = _try_parse_int(entry_number)
        if entry_number != season_number:
            continue
        episodes = entry.get("episodes")
        if isinstance(episodes, list) and episodes:
            return len(episodes)
        for key in ("episodeCount", "episode_count", "episodesCount", "episodes_count"):
            count_value = entry.get(key)
            parsed = _try_parse_int(count_value)
            if parsed:
                return parsed
    return None

def extract_request_seasons(request_item, skip_available=False):
    payloads = _collect_request_season_payloads(request_item)
    season_numbers = []
    seen = set()
    for entry in payloads:
        if isinstance(entry, dict):
            number = entry.get("seasonNumber") or entry.get("season") or entry.get("number")
        else:
            number = entry
        parsed = _try_parse_int(number)
        if parsed is None or parsed in seen:
            continue
        if skip_available and isinstance(entry, dict) and _is_season_entry_available(entry):
            continue
        season_numbers.append(parsed)
        seen.add(parsed)
    return season_numbers

# Nota: _extract_tmdb_id, _try_parse_int sono ora importati da api_clients.py
# Nota: _normalize_media_type è ora importata da utils.py

def _try_parse_int(value):
    """Local copy for use in checker.py functions that haven't been moved yet."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

def _extract_imdb_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("imdbId", "imdb_id", "imdb"):
            value = source.get(key)
            normalized = _normalize_imdb_id(value)
            if normalized:
                return normalized
    return None

def _normalize_imdb_id(value):
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    return f"tt{digits}"

def _extract_tvdb_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tvdbId", "tvdb_id", "tvdb"):
            parsed = _try_parse_int(source.get(key))
            if parsed:
                return parsed
    return None

def _extract_tvrage_id(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tvRageId", "tvrageId", "tv_rage_id"):
            parsed = _try_parse_int(source.get(key))
            if parsed:
                return parsed
    return None

# Nota: _fetch_tmdb_payload è ora importata da api_clients.py
# Nota: _detect_original_language, gather_title_candidates, build_search_queries, sanitize_title sono ora importate da scanner.py

# Nota: search_prowlarr e search_jackett sono ora importate da api_clients.py

def search_indexers(query, media_type, config):
    providers_used = False
    aggregated = []
    if _should_use_prowlarr(config):
        providers_used = True
        aggregated.extend(search_prowlarr(query, media_type, config))
    if _should_use_jackett(config):
        providers_used = True
        aggregated.extend(search_jackett(query, media_type, config))
    if not providers_used:
        print("   -> Nessun indexer disponibile per le ricerche (abilita Prowlarr o Jackett).")
    return aggregated

# Nota: _detect_resolution_bucket, _extract_episode_from_title, _contains_isolated_tag sono ora importate da scanner.py
# Nota: filter_results, sanitize_title, _contains_language_token, _has_audio_language sono ora importate da scanner.py

def execute_search_with_variants(
    query_variants,
    media_type,
    config,
    canonical_titles=None,
    exclusion_collector=None,
    request_rules=None
):
    attempts = []
    collected = []
    seen_keys = set()

    def _result_key(item):
        return item.get("magnet") or item.get("torrent") or f"{item.get('title')}|{item.get('size_gb')}"

    for query in query_variants:
        raw_results = search_indexers(query, media_type, config)
        valid_results = filter_results(
            raw_results,
            config,
            canonical_titles=canonical_titles,
            media_type=media_type,
            exclusion_collector=exclusion_collector,
            request_rules=request_rules
        )
        attempts.append({
            "query": query,
            "results_found": len(valid_results)
        })
        for result in valid_results:
            key = _result_key(result)
            if key in seen_keys:
                continue
            collected.append(result)
            seen_keys.add(key)

    return collected, attempts

SORT_SPECS = {
    "seeders_desc": {"key": lambda x: x.get("seeders", 0), "reverse": True},
    "seeders_asc": {"key": lambda x: x.get("seeders", 0), "reverse": False},
    "size_desc": {"key": lambda x: x.get("size_gb", 0), "reverse": True},
    "size_asc": {"key": lambda x: x.get("size_gb", 0), "reverse": False},
    "title_asc": {"key": lambda x: x.get("title", "").lower(), "reverse": False},
    "title_desc": {"key": lambda x: x.get("title", "").lower(), "reverse": True},
    "episode_asc": {"key": lambda x: (x.get("episode_sort") is None, x.get("episode_sort") or 0), "reverse": False},
    "episode_desc": {"key": lambda x: (x.get("episode_sort") is None, -(x.get("episode_sort") or 0)), "reverse": False},
}

def _resolve_sort_modes_for_media(rules, media_type):
    normalized_rules = _normalize_sort_settings(copy.deepcopy(rules) if rules else _default_search_rules())
    normalized_type = (_normalize_media_type(media_type) or "tv")
    if normalized_type == "movie":
        primary = normalized_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
        secondary = normalized_rules.get("movie_sort_secondary") or ""
    else:
        primary = normalized_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
        secondary = normalized_rules.get("tv_sort_secondary") or ""
    if secondary == primary:
        secondary = ""
    return primary, secondary

def sort_results(results, rules, media_type=None):
    if not results:
        return []
    primary, secondary = _resolve_sort_modes_for_media(rules, media_type)
    ordered = list(results)
    modes = [mode for mode in [primary, secondary] if mode]
    if not modes:
        modes = [DEFAULT_SORT_MODE]
    for mode in reversed(modes):
        spec = SORT_SPECS.get(mode, SORT_SPECS[DEFAULT_SORT_MODE])
        ordered = sorted(ordered, key=spec["key"], reverse=spec["reverse"])
    return ordered

def merge_duplicate_results(results):
    grouped = []
    index = {}
    for res in results:
        key = (res.get("normalized_title"), res.get("size_gb"))
        if not key[0]:
            key = (res.get("title", "").lower(), res.get("size_gb"))
        existing = index.get(key)
        if not existing:
            res_copy = dict(res)
            res_copy["duplicates"] = []
            index[key] = res_copy
            grouped.append(res_copy)
        else:
            existing.setdefault("duplicates", []).append(res)
    return grouped

def process_requests(config, status_callback=None, stop_event=None, target_map=None):
    print("--- Avvio OctoHub ---")
    requests_list = get_jellyseerr_requests(config)
    rules = config.get("SEARCH_RULES", {})
    previous_summary = load_results_file()
    target_map = target_map or {}

    if target_map:
        target_ids = set(target_map.keys())
        filtered = [req for req in requests_list if str(req.get("id")) in target_ids]
        missing = target_ids - {str(req.get("id")) for req in filtered}
        requests_list = filtered
        if missing:
            print(f"   -> Attenzione: {len(missing)} richieste selezionate non risultano più pendenti/approvate.")
        print(f"   -> Ricerca mirata su {len(requests_list)} richieste.")
    
    if not requests_list:
        print("\nNessuna richiesta da elaborare. Interrompo.")
        empty_summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": 0,
            "checked_requests": 0,
            "found": 0,
            "items": []
        }
        merged_empty = _merge_scan_summaries(previous_summary, empty_summary)
        save_results(merged_empty)
        return merged_empty

    total_requests = len(requests_list)
    non_available_requests = []
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    skipped_available = 0
    skipped_unreleased = 0
    skipped_type = 0
    skipped_disabled = 0
    skipped_season_only = 0

    # Primo passo: filtrare le richieste per media non disponibili
    for req in requests_list:
        media_info = req.get("media", {})
        status = media_info.get("status")
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        force_include = bool(target_spec)
        if skip_available and status == 5 and not force_include:
            skipped_available += 1
            continue
        if skip_unreleased and _is_request_unreleased(req) and not force_include:
            skipped_unreleased += 1
            continue
        media_type = req.get("type") or media_info.get("mediaType")
        normalized_type = _normalize_media_type(media_type)
        request_rule = _get_request_rule(config, req.get("id"))
        if request_rule and not request_rule.get("enabled", True) and not force_include:
            skipped_disabled += 1
            continue
        non_available_requests.append(req)
    
    print(f"   -> Dopo i filtri rimangono {len(non_available_requests)} richieste da analizzare (su {total_requests} totali).")
    if skipped_available:
        print(f"      (Saltate {skipped_available} richieste già disponibili)")
    if skipped_unreleased:
        print(f"      (Saltate {skipped_unreleased} richieste non ancora pubblicate)")
    if skipped_type:
        print(f"      (Saltate {skipped_type} richieste di tipologia esclusa)")
    if skipped_disabled:
        print(f"      (Saltate {skipped_disabled} richieste disattivate manualmente)")
    details_cache = {}
    media_details_cache = {}
    prepared_requests = []
    for req in non_available_requests:
        normalized_type = _normalize_media_type(req.get("type") or req.get("media", {}).get("mediaType"))
        resolved = req
        if normalized_type == "tv" and (skip_available or skip_unreleased):
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                resolved = detailed
        prepared_requests.append(resolved)
    non_available_requests = prepared_requests

    job_queue = []
    skipped_season_only = 0
    for req in non_available_requests:
        media_type_value = req.get("type") or req.get("media", {}).get("mediaType")
        normalized_type = _normalize_media_type(media_type_value)
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        forced_seasons_spec = target_spec.get("seasons") if target_spec else None
        seasons = []
        season_overview = []
        if normalized_type == "tv":
            season_overview = describe_season_statuses(req)
            if forced_seasons_spec:
                seasons = sorted(forced_seasons_spec)
            else:
                seasons = select_scan_seasons(season_overview, skip_available, skip_unreleased)
                if not seasons and season_overview and not target_spec:
                    skipped_season_only += 1
                    continue
                if not seasons:
                    seasons = extract_request_seasons(req, skip_available=False)
                    if seasons and skip_unreleased and not target_spec:
                        seasons = _filter_unreleased_seasons(req, seasons)
            req["_season_overview"] = season_overview
            if target_spec and forced_seasons_spec is None:
                seasons = seasons if seasons else extract_request_seasons(req, skip_available=False)
        else:
            if forced_seasons_spec:
                seasons = [None]
        job_queue.append((req, seasons if seasons else [None]))

    if skipped_season_only:
        print(f"      (Saltate {skipped_season_only} richieste TV senza episodi/stagioni da cercare)")

    total_iterations = sum(len(entry[1]) for entry in job_queue)
    if status_callback:
        status_callback(0, total_iterations, None, None)

    found_items_count = 0
    processed_iterations = 0
    processed_results = []
    aborted = False

    for i, (req, seasons) in enumerate(job_queue):
        if stop_event and stop_event.is_set():
            aborted = True
            break
        base_data = req
        media_info = base_data.get("media") or {}
        media_type = req.get("type") or media_info.get("mediaType")

        extra_sources = []
        def _extend_extra_sources(*values):
            for value in values:
                if isinstance(value, dict):
                    extra_sources.append(value)
        media_details = None
        title, year = extract_title_and_year(base_data)

        if not title or not media_type:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)

        normalized_media_type = _normalize_media_type(media_type)
        force_search = bool(target_spec and target_spec.get("force"))
        need_availability_details = rules.get("skip_available_content", True) and normalized_media_type == "tv"
        if need_availability_details and base_data is req:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources) or (title, year)

        if not title:
            print(f"   -> Recupero dettagli TMDB aggiuntivi per richiesta {req.get('id')}...")
            media_details, resolved_type = fetch_media_info(media_info, config, media_details_cache, media_type)
            if (not media_details) and base_data.get("mediaInfo"):
                alt_details, alt_type = fetch_media_info(base_data.get("mediaInfo"), config, media_details_cache, media_type)
                if alt_details:
                    media_details = alt_details
                    resolved_type = resolved_type or alt_type
            if media_details:
                _extend_extra_sources(media_details)
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
            if resolved_type and not media_type:
                media_type = resolved_type

        if not media_type:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: tipo di media non disponibile.")
            continue

        if not title:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: titolo non trovato nei dati di Jellyseerr.")
            continue

        display_year = year or "----"

        request_rule = _get_request_rule(config, req.get("id"))
        effective_rules = _compose_request_search_rules(config.get("SEARCH_RULES"), request_rule)
        title_candidates = gather_title_candidates(base_data, extra_sources, effective_rules)
        if title not in title_candidates:
            title_candidates.insert(0, title)
        id_sources = [req, base_data, media_info, base_data.get("media"), base_data.get("mediaInfo"), media_details]
        id_sources.extend(extra_sources)

        season_overview_map = {}
        if normalized_media_type == "tv":
            overview = req.get("_season_overview") or describe_season_statuses(base_data)
            season_overview_map = {entry["season"]: entry for entry in overview}
        for season in seasons:
            if stop_event and stop_event.is_set():
                aborted = True
                break

            season_label = f" - Stagione {season:02d}" if season is not None else ""
            print(f"\n2. Elaboro richiesta [{i+1}/{len(non_available_requests)}]{season_label}: {title} ({display_year})")

            episode_count = get_episode_count_for_season([src for src in id_sources if isinstance(src, dict)], season)
            pending_episodes = None
            if rules.get("skip_available_content", True) and normalized_media_type == "tv" and not force_search:
                entry = season_overview_map.get(season)
                if entry:
                    pending_episodes = entry.get("pending")
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria.")
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available"
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
                if pending_episodes is None:
                    pending_episodes = get_pending_episode_numbers(base_data, season)
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria.")
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available"
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
            movie_year_variance = request_rule.get("year_variance", 0) if normalized_media_type == "movie" else 0
            query_variants = build_search_queries(
                title_candidates,
                year,
                config,
                media_type=media_type,
                season_code=season,
                episode_count=episode_count,
                request_terms=request_rule,
                pending_episodes=pending_episodes,
                search_rules_override=effective_rules,
                year_variance=movie_year_variance
            )
            print(f"   -> Varianti provate: {len(query_variants)}")
            exclusion_reasons = []
            valid_results, attempts = execute_search_with_variants(
                query_variants,
                media_type,
                config,
                canonical_titles=title_candidates,
                exclusion_collector=exclusion_reasons,
                request_rules=request_rule
            )

            if valid_results:
                found_items_count += 1
                sorted_results = sort_results(
                    valid_results,
                    config.get("SEARCH_RULES", {}),
                    media_type=media_type
                )
                grouped_results = merge_duplicate_results(sorted_results)
                print(f"   => {len(grouped_results)} risultati utili per '{title}'{season_label}:")
                for item in grouped_results[:5]:
                    print(f"     - Titolo: {item['title']}")
                    print(f"       Dim: {item['size_gb']} GB, Seeders: {item['seeders']}, Fonte: {item['indexer']}")
                    print(f"       Link: {item['link']}\n")
            else:
                grouped_results = []
                print(f"   => Nessun risultato valido per '{title}'{season_label}.")

            processed_results.append({
                "request_id": req.get("id"),
                "title": title,
                "year": year,
                "media_type": media_type,
                "season": season,
                "queries": attempts,
                "results_found": len(grouped_results),
                "results": grouped_results,
                "excluded": exclusion_reasons
            })

            processed_iterations += 1
            if status_callback:
                status_callback(processed_iterations, total_iterations, title, season)

        if aborted:
            break

    print(f"\n--- Riepilogo ---")
    print(f"Ricerca completata. Trovati contenuti per {found_items_count} su {len(non_available_requests)} richieste analizzate.")

    run_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "checked_requests": len(non_available_requests),
        "found": found_items_count,
        "items": processed_results,
        "aborted": aborted,
        "target_subset": bool(target_map)
    }
    merged_summary = _merge_scan_summaries(previous_summary, run_summary)
    save_results(merged_summary)
    return merged_summary

class TraktAPIError(RuntimeError):
    """Raised when Trakt API calls fail."""

class TraktClient:
    BASE_URL = "https://api.trakt.tv"

    def __init__(self, client_id: str, access_token: str):
        self.client_id = (client_id or "").strip()
        self.access_token = (access_token or "").strip()
        self._collection_cache = None
        self._collection_timestamp = 0.0
        self._season_cache: Dict[tuple, Any] = {}
        self._show_id_cache: Dict[int, Any] = {}
        self._lock = threading.Lock()

    def _headers(self):
        return {
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OctoHub/1.0 (+https://github.com/roy/octohub)"
        }

    def _request(self, method: str, path: str, **kwargs):
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        timeout = kwargs.pop("timeout", 15)
        try:
            response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise TraktAPIError(f"Errore di rete Trakt: {exc}") from exc
        if response.status_code == 401:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = (
                        payload.get("error_description")
                        or payload.get("description")
                        or payload.get("error")
                    )
            except Exception:
                detail = response.text
            detail = (detail or response.text or "").strip()
            if detail:
                raise TraktAPIError(f"Credenziali Trakt non valide (401): {detail}")
            raise TraktAPIError("Credenziali Trakt non valide (401).")
        if response.status_code == 403:
            raise TraktAPIError("Accesso Trakt negato (403).")
        if response.status_code >= 500:
            raise TraktAPIError("Trakt non disponibile (errore 5xx).")
        if response.status_code >= 400:
            raise TraktAPIError(f"Errore Trakt {response.status_code}.")
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise TraktAPIError("Risposta Trakt non valida.") from exc

    def ping(self) -> bool:
        self._request("GET", "/sync/last_activities")
        return True

    def get_collection_map(self, max_age: int = 900) -> Dict[int, Dict[int, set]]:
        now = time.time()
        with self._lock:
            if self._collection_cache and (now - self._collection_timestamp) < max_age:
                return self._collection_cache
        try:
            payload = self._request(
                "GET",
                "/sync/collection/shows?extended=episodes",
                timeout=30
            ) or []
        except TraktAPIError:
            with self._lock:
                self._collection_cache = {}
                self._collection_timestamp = now
            raise
        mapping: Dict[int, Dict[int, set]] = {}
        for entry in payload:
            show = entry.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = ids.get("tmdb")
            tmdb_id = _try_parse_int(tmdb_id)
            if not tmdb_id:
                continue
            show_map = mapping.setdefault(tmdb_id, {})
            for season in entry.get("seasons") or []:
                season_number = _try_parse_int(season.get("number"))
                if season_number is None:
                    continue
                eps_set = show_map.setdefault(season_number, set())
                for episode in season.get("episodes") or []:
                    ep_number = _try_parse_int(episode.get("number"))
                    if ep_number is not None:
                        eps_set.add(ep_number)
        with self._lock:
            self._collection_cache = mapping
            self._collection_timestamp = now
        return mapping

    def get_season(self, tmdb_id: int, season_number: int):
        if tmdb_id is None or season_number is None:
            return None
        cache_key = (tmdb_id, season_number)
        with self._lock:
            if cache_key in self._season_cache:
                return self._season_cache[cache_key]
        show_identifier = self._resolve_show_identifier(tmdb_id)
        if not show_identifier:
            return None
        path = f"/shows/{show_identifier}/seasons/{season_number}?extended=episodes"
        payload = self._request("GET", path) or []
        with self._lock:
            self._season_cache[cache_key] = payload
        return payload

    def _resolve_show_identifier(self, tmdb_id: int):
        if tmdb_id in self._show_id_cache:
            return self._show_id_cache[tmdb_id]
        # Try to fetch via search API
        try:
            search_results = self._request(
                "GET",
                f"/search/tmdb/{tmdb_id}?type=show",
                timeout=10
            )
        except TraktAPIError:
            search_results = None
        identifier = None
        if isinstance(search_results, list):
            for entry in search_results:
                show = entry.get("show") if isinstance(entry, dict) else None
                ids = show.get("ids") if isinstance(show, dict) else None
                if ids:
                    identifier = ids.get("slug") or ids.get("trakt") or ids.get("tmdb")
                    if identifier:
                        break
        if not identifier:
            identifier = tmdb_id
        with self._lock:
            self._show_id_cache[tmdb_id] = identifier
        return identifier


# --- MAIN ---

if __name__ == "__main__":
    args = parse_args()

    if args.configure:
        run_config_server()
        sys.exit(0)

    config, is_valid = load_config()

    if not config or not is_valid:
        print("Configurazione mancante o non valida.")
        run_config_server()
        sys.exit(0)

    if args.web:
        run_dashboard_server()
    elif args.cli:
        if not validate_connections(config):
            sys.exit(1)
        summary = process_requests(config)
        print(f"\nRisultati salvati. Trovati contenuti per {summary.get('found', 0)} richieste.")
    else:
        run_dashboard_server()
