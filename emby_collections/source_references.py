"""Validation and canonical projection for collection source references."""

from __future__ import annotations

import re
import urllib.parse


_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TRAKT_SORT = re.compile(r"[A-Za-z0-9_]+(?:,(?:asc|desc))?\Z", re.IGNORECASE)
_TRAKT_SORT_BY = re.compile(r"[A-Za-z0-9_]+\Z")
_PROVIDER_HOSTS = {
    "trakt_list": {"trakt.tv", "www.trakt.tv"},
    "tmdb_list": {"themoviedb.org", "www.themoviedb.org"},
    "tmdb_collection": {"themoviedb.org", "www.themoviedb.org"},
    "mdblist": {"mdblist.com", "www.mdblist.com", "api.mdblist.com"},
}


def _parse_https_provider_url(source_type: str, value: str) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL fonte non valido") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in _PROVIDER_HOSTS[source_type]
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("URL fonte non autorizzato")
    return parsed


def _normalize_trakt_query(query: str) -> str:
    try:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("Parametri Trakt non validi") from exc
    if not pairs:
        return ""
    if len(pairs) > 2 or len({key for key, _value in pairs}) != len(pairs):
        raise ValueError("Parametri Trakt non validi")
    params = dict(pairs)
    if "sort" in params:
        if len(params) != 1 or not _TRAKT_SORT.fullmatch(params["sort"]):
            raise ValueError("Parametri Trakt non validi")
        return f"sort={params['sort'].lower()}"
    if not set(params).issubset({"sort_by", "sort_how"}):
        raise ValueError("Parametri Trakt non autorizzati")
    if "sort_by" in params and not _TRAKT_SORT_BY.fullmatch(params["sort_by"]):
        raise ValueError("Parametro sort_by non valido")
    if "sort_how" in params and params["sort_how"].lower() not in {"asc", "desc"}:
        raise ValueError("Parametro sort_how non valido")
    return urllib.parse.urlencode([(key, value.lower()) for key, value in pairs])


def _normalize_trakt(value: str) -> str:
    if value.lower().startswith(("http://", "https://")):
        parsed = _parse_https_provider_url("trakt_list", value)
        path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if len(path_parts) == 2 and path_parts[0].lower() == "lists":
            base_value = path_parts[1]
        elif len(path_parts) == 4 and path_parts[0].lower() == "users" and path_parts[2].lower() == "lists":
            base_value = f"{path_parts[1].lower()}/{path_parts[3]}"
        else:
            raise ValueError("Percorso lista Trakt non valido")
        query = parsed.query
    else:
        base_value, separator, query = value.partition("?")
        if not separator:
            query = ""
    parts = base_value.split("/")
    if len(parts) not in {1, 2} or any(not _SAFE_TOKEN.fullmatch(part) for part in parts):
        raise ValueError("Riferimento lista Trakt non valido")
    if len(parts) == 2:
        parts[0] = parts[0].lower()
    canonical = "/".join(parts)
    canonical_query = _normalize_trakt_query(query) if query else ""
    return f"{canonical}?{canonical_query}" if canonical_query else canonical


def _normalize_tmdb(source_type: str, value: str) -> str:
    segment = "list" if source_type == "tmdb_list" else "collection"
    if value.lower().startswith(("http://", "https://")):
        parsed = _parse_https_provider_url(source_type, value)
        if parsed.query:
            raise ValueError("I parametri URL TMDB non sono consentiti")
        match = re.fullmatch(rf"/{segment}/(\d+)/?", parsed.path, re.IGNORECASE)
        if not match:
            raise ValueError("Percorso TMDB non valido")
        return match.group(1)
    if not value.isdigit():
        raise ValueError("ID TMDB non valido")
    return value


def _normalize_mdblist(value: str) -> str:
    external = re.fullmatch(r"external:(\d+)", value, re.IGNORECASE)
    if external:
        return f"external:{external.group(1)}"
    if _SAFE_TOKEN.fullmatch(value):
        return value
    parsed = _parse_https_provider_url("mdblist", value)
    if parsed.query:
        raise ValueError("I parametri URL MDBList non sono consentiti")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    patterns = (
        ("external", r"/(?:external/lists|lists/[^/]+/external)/(\d+)(?:/items)?"),
        ("list", r"/(?:list|lists)/(\d+)(?:/items)?"),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, path, re.IGNORECASE)
        if match:
            return f"external:{match.group(1)}" if kind == "external" else match.group(1)
    raise ValueError("Percorso MDBList non valido")


def normalize_source_reference(source_type: str, source_value: str) -> str:
    """Return the provider-specific canonical reference or reject it."""
    value = str(source_value or "").strip()
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Valore della lista non valido")
    if source_type == "trakt_list":
        return _normalize_trakt(value)
    if source_type in {"tmdb_list", "tmdb_collection"}:
        return _normalize_tmdb(source_type, value)
    if source_type == "mdblist":
        return _normalize_mdblist(value)
    raise ValueError("Tipo di fonte non valido")


def detect_source_type(source_value: str) -> str | None:
    """Identify only exact supported provider URLs, never host substrings."""
    value = str(source_value or "").strip()
    if not value.lower().startswith(("http://", "https://")):
        return None
    for source_type in ("trakt_list", "tmdb_list", "tmdb_collection", "mdblist"):
        try:
            normalize_source_reference(source_type, value)
        except ValueError:
            continue
        return source_type
    return None
