"""Source providers used by the Emby collection workflow."""

from __future__ import annotations

import urllib.parse
from typing import Any, Callable, Dict, List, Tuple

from .sources_common import PROVIDER_LABEL_MAP
from .sources_imdb import _fetch_imdb_list_from_value
from .sources_mdblist import _fetch_imdb_via_mdblist_items, _fetch_mdblist_items, is_mdblist_enabled, list_mdblist_user_lists
from .sources_tmdb import _fetch_tmdb_collection_from_value, _fetch_tmdb_list_from_value
from .sources_trakt import list_trakt_lists, _fetch_trakt_list_items


def build_source_link(source_type: str, source_value: str) -> str:
    value = (source_value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if source_type == "trakt_list":
        base_value, _, query = value.partition("?")
        parts = base_value.split("/", 1)
        if len(parts) == 1:
            url = f"https://trakt.tv/lists/{urllib.parse.quote(parts[0])}"
        else:
            url = f"https://trakt.tv/users/{urllib.parse.quote(parts[0])}/lists/{urllib.parse.quote(parts[1])}"
        if query:
            url = f"{url}?{query}"
        return url
    if source_type in {"imdb_list", "imdb_mdblist"}:
        if value.startswith("ls"):
            return f"https://www.imdb.com/list/{value}"
        return value
    if source_type == "tmdb_list":
        return f"https://www.themoviedb.org/list/{value}"
    if source_type == "tmdb_collection":
        return f"https://www.themoviedb.org/collection/{value}"
    if source_type == "mdblist":
        if value.lower().startswith("http"):
            return value
        return f"https://mdblist.com/list/{value}"
    return value


SourceFetchFunc = Callable[[str], List[Dict[str, Any]]]

SOURCE_PROVIDER_CONFIG: List[Tuple[str, Dict[str, Any]]] = [
    (
        "trakt_list",
        {
            "label": "Lista Trakt",
            "description": "Formato <code>utente/lista</code> oppure URL completo.",
            "placeholder": "mio-utente/la-mia-lista",
            "help": "Indirizza una lista Trakt (public/private). Usa user/lista o link completo.",
            "fetch": _fetch_trakt_list_items
        }
    ),
    (
        "imdb_list",
        {
            "label": "Lista IMDb",
            "description": "Copia l'ID <code>ls</code> o l'URL IMDb (lista o chart).",
            "placeholder": "ls123456789",
            "help": "Supporta ID, URL lista e chart.",
            "fetch": _fetch_imdb_list_from_value
        }
    ),
    (
        "imdb_mdblist",
        {
            "label": "IMDb tramite MDBList",
            "description": "Usa un URL IMDb lista/chart collegato a una External List MDBList già creata.",
            "placeholder": "https://www.imdb.com/chart/toptv/",
            "help": "OctoHub legge ogni volta la lista MDBList aggiornata, evitando il WAF IMDb.",
            "fetch": _fetch_imdb_via_mdblist_items
        }
    ),
    (
        "tmdb_list",
        {
            "label": "Lista TMDB",
            "description": "Usa l'ID numerico di una lista (es. <code>709'xxx</code>) o l'URL <code>https://www.themoviedb.org/list/xxxx</code>.",
            "placeholder": "123456",
            "help": "Lista personale o pubblica TMDB.",
            "fetch": _fetch_tmdb_list_from_value
        }
    ),
    (
        "tmdb_collection",
        {
            "label": "Collezione TMDB",
            "description": "Inserisci l'ID numerico della raccolta (es. <code>121867</code>) o l'URL <code>https://www.themoviedb.org/collection/121867</code>.",
            "placeholder": "121867",
            "help": "Le collezioni TMDB raggruppano film correlati.",
            "fetch": _fetch_tmdb_collection_from_value
        }
    ),
    (
        "mdblist",
        {
            "label": "Lista MDBList",
            "description": "Inserisci un ID o URL MDBList per importare la lista come collezione Emby.",
            "placeholder": "https://mdblist.com/list/...",
            "help": "Supporta liste pubbliche o le tue liste personali (serve API key).",
            "fetch": _fetch_mdblist_items
        }
    )
]

SOURCE_TYPES: List[Dict[str, Any]] = [
    {
        "value": value,
        "label": meta["label"],
        "description": meta["description"],
        "placeholder": meta["placeholder"],
        "help": meta["help"]
    }
    for value, meta in SOURCE_PROVIDER_CONFIG
]

SOURCE_TYPE_MAP: Dict[str, Dict[str, Any]] = {entry["value"]: entry for entry in SOURCE_TYPES}

SOURCE_FETCHERS: Dict[str, SourceFetchFunc] = {
    value: meta["fetch"]
    for value, meta in SOURCE_PROVIDER_CONFIG
}


def fetch_source_items(source_type: str, source_value: str) -> List[Dict[str, Any]]:
    fetcher = SOURCE_FETCHERS.get(source_type)
    if not fetcher:
        raise RuntimeError(f"Fonte {source_type} non supportata")
    result = fetcher(source_value)
    if not isinstance(result, list):
        raise RuntimeError("Risposta fonte non valida")
    return result


__all__ = [
    "SOURCE_TYPES",
    "SOURCE_TYPE_MAP",
    "SOURCE_FETCHERS",
    "fetch_source_items",
    "list_trakt_lists",
    "build_source_link",
    "list_mdblist_user_lists",
    "is_mdblist_enabled",
    "PROVIDER_LABEL_MAP"
]
