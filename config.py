# config.py
"""
Modulo per la gestione della configurazione statica e di default dell'applicazione.
"""

import copy
import json
import os
import uuid
from typing import Any, Dict, Optional

from utils import (
    _split_csv_field,
    _coerce_request_bool,
    _coerce_request_int,
    _normalize_alt_language,
    _sanitize_terms_list
)

# --- COSTANTI ---
CONFIG_FILE = os.environ.get("OCTOHUB_CONFIG_FILE", "config.json")
RESULTS_FILE = os.environ.get("OCTOHUB_RESULTS_FILE", "last_results.json")
MAX_PRIMARY_QUERY_VARIANTS = 80

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
EMBY_REQUEST_TIMEOUT = 6

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
    "OMDB_API_KEY": "",
    "OMDB_API_KEYS": [],
    "MDBLIST_API_KEYS": [],
    "TARGET_LANGUAGES": ["ita", "italian"],
    "EXCLUDE_TAGS": ["md", "cam", "ts", "tc", "vmd", "sub", "subs", "forced", "screener"],
    "SEARCH_RULES": {
        "use_original_title": True,
        "use_alt_titles_original": True,
        "use_alt_titles_language": False,
        "alt_titles_language": "all",
        "sanitize_titles": True,
        "query_languages": [],
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
        "HOST": "",
        "PORT": "",
        "NAME": "",
        "USER": "",
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
    "MDBLIST": {
        "API_KEY": ""
    },
    "JUSTWATCH": {
        "ENABLED": False,
        "LOCALE": "it_IT"
    },
    "RSS_IMPORT": {
        "ENABLED": False,
        "POLL_INTERVAL_MINUTES": 30,
        "DEDUP_KEEP": "newest",
        "SOURCES": []
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
        },
        "workflow": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 360,
            "times": []
        },
        "sync": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 60,
            "times": []
        },
        "rss": {
            "enabled": False,
            "mode": "interval",
            "interval_minutes": 30,
            "times": []
        }
    },
    "EMBY": {
        "SERVERS": []
    }
    ,
    "COLLECTIONS": {
        "AUTO_REFRESH_ENABLED": True,
        "AUTO_REFRESH_INTERVAL_MINUTES": 240,
        "AUTO_REFRESH_MODE": "interval",
        "AUTO_REFRESH_TIMES": []
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
    "TMDB_LANGUAGE",
    "OMDB_API_KEY",
    "OMDB_API_KEYS",
    "MDBLIST_API_KEYS"
]

# Funzioni di "default"
def _default_search_rules() -> Dict[str, Any]:
    """Restituisce una copia delle regole di ricerca di default."""
    return copy.deepcopy(DEFAULT_CONFIG["SEARCH_RULES"])

def _default_auto_tasks() -> Dict[str, Any]:
    """Restituisce una copia delle impostazioni dei task automatici di default."""
    return copy.deepcopy(DEFAULT_CONFIG["AUTO_TASKS"])

def _default_emby_settings() -> Dict[str, Any]:
    """Restituisce una copia delle impostazioni Emby di default."""
    return copy.deepcopy(DEFAULT_CONFIG["EMBY"])

# Helper per la conversione di tipi (da spostare in utils.py in futuro)
def _normalize_time_token(token: Any) -> Optional[str]:
    """Normalizes a string like '14' or '14:30' into 'HH:MM' format."""
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None
    if ":" not in text:
        text = f"{text}:00"
    try:
        hour_str, minute_str = text.split(":", 1)
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
    except (ValueError, IndexError):
        return None
    return f"{hour:02d}:{minute:02d}"

def _normalize_time_list(values: Any) -> list[str]:
    """Normalizes a list or CSV string of time values."""
    if not values:
        return []
    if isinstance(values, str):
        values = _split_csv_field(values)
    normalized = []
    if isinstance(values, list):
        for entry in values:
            parsed = _normalize_time_token(entry)
            if parsed:
                normalized.append(parsed)
    return sorted(set(normalized))

# Funzioni di merge e normalizzazione
def _merge_database_settings(user_settings: Optional[Dict]) -> Dict[str, Any]:
    """Unisci le impostazioni del database dell'utente con quelle di default."""
    merged = copy.deepcopy(DEFAULT_CONFIG["DATABASE"])
    if isinstance(user_settings, dict):
        for key, value in user_settings.items():
            if value in (None, "") and key in {"URL", "PASSWORD"}:
                continue
            normalized = key.upper()
            if normalized in merged:
                merged[normalized] = value
            else:
                merged[key] = value
    return merged

def _merge_trakt_settings(user_settings: Optional[Dict]) -> Dict[str, Any]:
    """Unisci le impostazioni Trakt dell'utente con quelle di default."""
    merged = copy.deepcopy(DEFAULT_CONFIG["TRAKT"])
    if isinstance(user_settings, dict):
        for key, value in user_settings.items():
            if isinstance(value, str):
                value = value.strip()
            normalized = key.upper()
            if normalized in merged:
                if normalized == "ENABLED":
                    merged[normalized] = bool(value)
                else:
                    merged[normalized] = value or ""
            else:
                merged[key] = value
    if merged.get("CLIENT_ID") and merged.get("ACCESS_TOKEN"):
        merged["ENABLED"] = bool(merged.get("ENABLED"))
    else:
        merged["ENABLED"] = False
    return merged

def _merge_justwatch_settings(user_settings: Optional[Dict]) -> Dict[str, Any]:
    """Unisci le impostazioni JustWatch dell'utente con quelle di default."""
    merged = copy.deepcopy(DEFAULT_CONFIG["JUSTWATCH"])
    if isinstance(user_settings, dict):
        for key, value in user_settings.items():
            if isinstance(value, str):
                value = value.strip()
            normalized = key.upper()
            if normalized in merged:
                if normalized == "ENABLED":
                    merged[normalized] = bool(value)
                else:
                    merged[normalized] = value or merged.get(normalized, "")
            else:
                merged[key] = value
    return merged

def _merge_rss_import_settings(user_settings: Optional[Dict]) -> Dict[str, Any]:
    """Unisci le impostazioni RSS/Import dell'utente con quelle di default."""
    merged = copy.deepcopy(DEFAULT_CONFIG["RSS_IMPORT"])
    if not isinstance(user_settings, dict):
        return merged
    for key, value in user_settings.items():
        normalized = key.upper()
        if normalized == "ENABLED":
            merged["ENABLED"] = bool(value)
        elif normalized == "POLL_INTERVAL_MINUTES":
            merged["POLL_INTERVAL_MINUTES"] = _coerce_request_int(value, merged.get("POLL_INTERVAL_MINUTES", 30), 5, 1440)
        elif normalized == "DEDUP_KEEP":
            keep = (str(value) or "").lower().strip()
            merged["DEDUP_KEEP"] = "newest" if keep == "newest" else "oldest"
        elif normalized == "SOURCES":
            sources = []
            if isinstance(value, list):
                for entry in value:
                    if not isinstance(entry, dict):
                        continue
                    url = (entry.get("url") or "").strip()
                    if not url:
                        continue
                    sources.append({
                        "name": (entry.get("name") or "").strip(),
                        "url": url,
                        "tags": _split_csv_field(entry.get("tags")) if isinstance(entry.get("tags"), str) else (entry.get("tags") or []),
                        "enabled": _coerce_request_bool(entry.get("enabled"), True)
                    })
            merged["SOURCES"] = sources
        else:
            merged[key] = value
    return merged


def _merge_collection_settings(user_settings: Optional[Dict]) -> Dict[str, Any]:
    """Merge user-defined collection settings with defaults."""
    merged = copy.deepcopy(DEFAULT_CONFIG["COLLECTIONS"])
    if not isinstance(user_settings, dict):
        return merged
    has_minutes = any(
        str(key).upper() == "AUTO_REFRESH_INTERVAL_MINUTES"
        for key in user_settings.keys()
    )
    for key, value in user_settings.items():
        normalized = key.upper()
        if normalized == "AUTO_REFRESH_INTERVAL_HOURS":
            if not has_minutes and value not in (None, "") and merged.get("AUTO_REFRESH_INTERVAL_MINUTES") is not None:
                try:
                    merged["AUTO_REFRESH_INTERVAL_MINUTES"] = int(value) * 60
                except (TypeError, ValueError):
                    pass
            continue
        if normalized not in merged:
            merged[normalized] = value
            continue
        current = merged[normalized]
        if isinstance(current, bool):
            merged[normalized] = bool(value)
        elif isinstance(current, int):
            try:
                merged[normalized] = int(value)
            except (TypeError, ValueError):
                pass
        else:
            merged[normalized] = value
    return merged

def _normalize_emby_server(entry: Optional[Dict]) -> Dict[str, Any]:
    """Normalizza una singola voce di configurazione di un server Emby."""
    if not isinstance(entry, dict):
        entry = {}
    server_id = str(entry.get("id") or uuid.uuid4())
    alias = (entry.get("alias") or "").strip()
    original_name = (entry.get("original_name") or "").strip()
    name = (entry.get("name") or original_name or alias).strip()
    if not name:
        name = f"Server Emby {server_id[:6]}"
    normalized = {
        "id": server_id,
        "name": name,
        "alias": alias,
        "original_name": original_name,
        "emby_server_id": (entry.get("emby_server_id") or "").strip(),
        "url": (entry.get("url") or "").strip(),
        "api_key": entry.get("api_key") or "",
        "enabled": _coerce_request_bool(entry.get("enabled"), True),
        "notes": (entry.get("notes") or "").strip(),
        "last_action": {
            "name": (entry.get("last_action") or {}).get("name", "").strip(),
            "timestamp": (entry.get("last_action") or {}).get("timestamp", "").strip(),
            "result": (entry.get("last_action") or {}).get("result", "").strip()
        },
        "strm_task_id": (entry.get("strm_task_id") or "").strip()
    }
    icon = (entry.get("icon") or "").strip()
    icon_color = (entry.get("icon_color") or "").strip()
    icon_style = (entry.get("icon_style") or "").strip().lower()
    if not icon or not icon.startswith("fa-"):
        icon = "fa-server"
    if not icon_color:
        icon_color = "#3b82f6"
    if icon_style not in ("solid", "regular"):
        icon_style = "solid"
    normalized["icon"] = icon
    normalized["icon_color"] = icon_color
    normalized["icon_style"] = icon_style
    return normalized

def _merge_emby_settings(settings: Optional[Dict]) -> Dict[str, Any]:
    """Unisci le impostazioni Emby dell'utente, normalizzando ogni server."""
    merged = _default_emby_settings()
    servers = []
    if isinstance(settings, dict):
        for entry in settings.get("SERVERS") or []:
            normalized = _normalize_emby_server(entry)
            servers.append(normalized)
    merged["SERVERS"] = servers
    return merged

def _normalize_auto_entry(entry: Optional[Dict], fallback: Dict) -> Dict[str, Any]:
    """Normalizza una singola voce di configurazione per un task automatico."""
    base = copy.deepcopy(fallback)
    if not isinstance(entry, dict):
        return base
    base["enabled"] = bool(entry.get("enabled"))
    mode = entry.get("mode") or base.get("mode") or "interval"
    if mode not in ("interval", "fixed"):
        mode = "interval"
    base["mode"] = mode
    raw_minutes = entry.get("interval_minutes")
    minutes = base.get("interval_minutes", 60)
    if raw_minutes not in (None, ""):
        minutes = _coerce_request_int(raw_minutes, base.get("interval_minutes", 60))
    base["interval_minutes"] = max(5, minutes)
    times = _normalize_time_list(entry.get("times"))
    base["times"] = times
    return base

def _normalize_auto_settings(settings: Optional[Dict]) -> Dict[str, Dict[str, Any]]:
    """Normalizza l'intera sezione dei task automatici."""
    defaults = _default_auto_tasks()
    normalized = {}
    settings = settings or {}
    for key, fallback in defaults.items():
        normalized[key] = _normalize_auto_entry(settings.get(key) or {}, fallback)
    return normalized

def _sanitize_sort_fallback(fallback: str, allowed: list[str]) -> str:
    """Garantisce che il fallback per l'ordinamento sia un valore valido."""
    if fallback in allowed:
        return fallback
    return allowed[0] if allowed else DEFAULT_SORT_MODE

def _clean_sort_mode(value: Optional[str], allowed: list[str], fallback: str, allow_empty: bool = False) -> str:
    """Pulisce e valida una modalità di ordinamento."""
    fallback = _sanitize_sort_fallback(fallback, allowed)
    if value is None:
        return fallback
    if allow_empty and value == "":
        return ""
    if value in allowed:
        return value
    return fallback

def _normalize_sort_settings(rules: Optional[Dict]) -> Dict[str, Any]:
    """Normalizza e corregge le impostazioni di ordinamento per TV e film."""
    if not isinstance(rules, dict):
        rules = _default_search_rules()
    legacy = rules.get("results_sort") or DEFAULT_SORT_MODE
    tv_primary = _clean_sort_mode(
        rules.get("tv_sort_primary"),
        TV_SORT_KEYS,
        rules.get("results_sort") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"]
    )
    tv_secondary = _clean_sort_mode(
        rules.get("tv_sort_secondary"),
        TV_SORT_KEYS,
        DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
        allow_empty=True
    )
    if tv_secondary and tv_secondary == tv_primary:
        tv_secondary = ""
    movie_primary = _clean_sort_mode(
        rules.get("movie_sort_primary"),
        MOVIE_SORT_KEYS,
        rules.get("results_sort") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"]
    )
    movie_secondary = _clean_sort_mode(
        rules.get("movie_sort_secondary"),
        MOVIE_SORT_KEYS,
        DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
        allow_empty=True
    )
    if movie_secondary and movie_secondary == movie_primary:
        movie_secondary = ""
    rules["tv_sort_primary"] = tv_primary
    rules["tv_sort_secondary"] = tv_secondary
    rules["movie_sort_primary"] = movie_primary
    rules["movie_sort_secondary"] = movie_secondary
    rules["results_sort"] = tv_primary or movie_primary or legacy or DEFAULT_SORT_MODE
    return rules

# Funzioni di I/O per il file di configurazione
def read_raw_config() -> Optional[Dict]:
    """Legge il file config.json e lo restituisce come dizionario."""
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

def _normalize_api_keys(value: Any) -> list[str]:
    """Normalizza un valore in una lista di API keys."""
    if not value:
        return []
    if isinstance(value, str):
        # Split by comma and clean each key
        keys = [k.strip() for k in value.split(',') if k.strip()]
        return keys
    if isinstance(value, list):
        # Filter out empty strings and ensure all are strings
        return [str(k).strip() for k in value if k and str(k).strip()]
    return []

def write_config_file(data: Dict):
    """Scrive un dizionario nel file config.json."""
    data = data or {}
    persisted = read_raw_config() or {}
    payload = {}
    for key in CONNECTION_FIELDS:
        # Use data value if explicitly provided (even if empty string), otherwise use persisted
        value = data.get(key) if key in data else persisted.get(key)

        # Special handling for API key arrays
        if key == "OMDB_API_KEYS":
            payload[key] = _normalize_api_keys(value)
            # Backward compatibility: if OMDB_API_KEY is set and OMDB_API_KEYS is empty, use it
            if not payload[key] and data.get("OMDB_API_KEY"):
                payload[key] = _normalize_api_keys(data.get("OMDB_API_KEY"))
        elif key == "MDBLIST_API_KEYS":
            payload[key] = _normalize_api_keys(value)
        else:
            # Save all connection fields, even if empty (to allow clearing values)
            payload[key] = value if value is not None else ""
    database_settings = _merge_database_settings(data.get("DATABASE") or persisted.get("DATABASE"))
    database_settings["ENABLED"] = True  # Forza l'abilitazione durante la scrittura
    database_settings["PASSWORD"] = ""
    database_settings["URL"] = ""
    payload["DATABASE"] = database_settings
    trakt_settings = data.get("TRAKT") or persisted.get("TRAKT")
    payload["TRAKT"] = _merge_trakt_settings(trakt_settings)
    justwatch_settings = data.get("JUSTWATCH") or persisted.get("JUSTWATCH")
    payload["JUSTWATCH"] = _merge_justwatch_settings(justwatch_settings)
    emby_settings = data.get("EMBY") or persisted.get("EMBY") or DEFAULT_CONFIG["EMBY"]
    payload["EMBY"] = _merge_emby_settings(emby_settings)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(payload, f, indent=4)

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
