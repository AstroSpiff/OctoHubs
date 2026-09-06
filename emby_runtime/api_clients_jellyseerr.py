import logging
import time

import requests

from core.http_response_limits import close_response_safely, read_bounded_json_response
from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print
from core.utils import _normalize_media_type
from core.outbound_redirects import response_is_redirect
from emby_runtime.api_client_urls import build_jellyseerr_api_url
from emby_runtime.api_clients_tmdb import _extract_tmdb_id, _fetch_tmdb_payload


# --- FUNZIONI JELLYSEERR ---

JELLYSEERR_REQUEST_PAGE_SIZE = 100
JELLYSEERR_REQUEST_MAX_ITEMS = 5000
_JELLYSEERR_REQUEST_ERROR = "Jellyseerr non disponibile"
logger = logging.getLogger(__name__)


def _log_jellyseerr_error(context: str, exc: BaseException) -> None:
    logger.warning("%s:\n%s", context, format_exception_for_log(exc))

def get_jellyseerr_requests(config, silent=False, return_status=False):
    """Recupera le richieste in sospeso da Jellyseerr."""
    if not silent:
        print("1. Recupero le richieste da Jellyseerr...")
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    try:
        all_results = []
        seen_ids = set()
        # Recupera richieste in attesa, approvate e disponibili (soddisfatte)
        for status in ["pending", "approved", "available"]:
            if not silent:
                print(f"   - Stato interrogato: {status}")
            skip = 0
            while len(all_results) < JELLYSEERR_REQUEST_MAX_ITEMS:
                params = {
                    "take": JELLYSEERR_REQUEST_PAGE_SIZE,
                    "skip": skip,
                    "filter": status,
                    "sort": "added",
                }
                response = requests.get(
                    build_jellyseerr_api_url(config, "/api/v1/request"),
                    headers=headers,
                    params=params,
                    allow_redirects=False,
                    timeout=10,
                    stream=True,
                )
                if response_is_redirect(response):
                    close_response_safely(response)
                    raise requests.TooManyRedirects("Redirect Jellyseerr rifiutato")
                data = read_bounded_json_response(response)
                page_results = data.get("results", []) if isinstance(data, dict) else []
                if not isinstance(page_results, list):
                    raise ValueError("Risposta Jellyseerr non valida")
                added_on_page = 0
                for entry in page_results:
                    entry_id = entry.get("id") if isinstance(entry, dict) else None
                    dedupe_key = str(entry_id) if entry_id is not None else repr(entry)
                    if dedupe_key in seen_ids:
                        continue
                    seen_ids.add(dedupe_key)
                    all_results.append(entry)
                    added_on_page += 1
                    if len(all_results) >= JELLYSEERR_REQUEST_MAX_ITEMS:
                        break
                page_info = data.get("pageInfo") if isinstance(data, dict) else None
                total = page_info.get("results") if isinstance(page_info, dict) else None
                if len(page_results) < JELLYSEERR_REQUEST_PAGE_SIZE:
                    break
                if added_on_page == 0:
                    break
                skip += len(page_results)
                if isinstance(total, int) and skip >= total:
                    break
        if not silent:
            print(f"   -> Recuperate {len(all_results)} richieste (pendenti + approvate + disponibili).")
        return (all_results, True) if return_status else all_results
    except (requests.exceptions.RequestException, ValueError) as exc:
        _log_jellyseerr_error("Recupero richieste Jellyseerr non riuscito", exc)
        if not silent:
            print(f"   -> {_JELLYSEERR_REQUEST_ERROR}")
        return ([], False) if return_status else []


# --- FUNZIONI JELLYSEERR ESTESE ---

def fetch_request_details(request_id, config, cache, max_retries=2):
    """
    Recupera dettagli aggiuntivi di una richiesta se non presenti nella raccolta principale.

    Args:
        request_id: ID della richiesta Jellyseerr
        config: Configurazione con credenziali Jellyseerr
        cache: Cache per evitare chiamate duplicate
        max_retries: Numero massimo di tentativi in caso di errore (default: 2)

    Returns:
        Dizionario con i dettagli della richiesta, o None se non disponibile
    """
    if not request_id:
        return None
    if request_id in cache:
        return cache[request_id]

    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    url = build_jellyseerr_api_url(config, f"/api/v1/request/{request_id}")

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                allow_redirects=False,
                timeout=15,  # Aumentato timeout da 10 a 15 secondi
                stream=True,
            )
            if response_is_redirect(response):
                close_response_safely(response)
                return None
            data = read_bounded_json_response(response)
            cache[request_id] = data

            # Log successo solo al primo tentativo
            if attempt == 0:
                print(f"   -> Dettagli richiesta {request_id} recuperati correttamente")
            else:
                print(f"   -> Dettagli richiesta {request_id} recuperati al tentativo {attempt + 1}/{max_retries + 1}")

            return data

        except requests.exceptions.Timeout as exc:
            if attempt < max_retries:
                print(f"   -> Timeout richiesta {request_id}, ritento... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(1)  # Attendi 1 secondo prima di riprovare
                continue
            else:
                _log_jellyseerr_error(
                    f"Timeout definitivo richiesta Jellyseerr {request_id}", exc
                )
                print(f"   -> [ERRORE] Timeout definitivo per richiesta {request_id}")
                return None

        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            _log_jellyseerr_error(
                f"Errore HTTP {status_code} richiesta Jellyseerr {request_id}", exc
            )
            print(f"   -> [ERRORE] HTTP {status_code} recuperando dettagli richiesta {request_id}")
            # Non ritentare per errori HTTP 4xx (client errors)
            if exc.response and 400 <= exc.response.status_code < 500:
                return None
            # Ritenta per errori 5xx (server errors)
            if attempt < max_retries:
                print(f"   -> Ritento richiesta {request_id}... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(2)  # Attendi 2 secondi per errori server
                continue
            return None

        except requests.exceptions.RequestException as exc:
            _log_jellyseerr_error(
                f"Recupero dettagli richiesta Jellyseerr {request_id} non riuscito", exc
            )
            print(f"   -> [ERRORE] Impossibile ottenere dettagli per la richiesta {request_id}")
            if attempt < max_retries:
                print(f"   -> Ritento richiesta {request_id}... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(1)
                continue
            return None

    return None


def fetch_media_info(media_entry, config, cache, fallback_media_type=None):
    """Scarica informazioni complete sul media associato ad una richiesta."""
    media_entry = media_entry or {}

    media_type_candidates = []
    primary_type = _normalize_media_type(media_entry.get("mediaType") or media_entry.get("type"))
    if primary_type:
        media_type_candidates.append(primary_type)
    fallback_type = _normalize_media_type(fallback_media_type)
    if fallback_type and fallback_type not in media_type_candidates:
        media_type_candidates.append(fallback_type)

    tmdb_id = _extract_tmdb_id(media_entry, media_entry.get("mediaInfo"))

    tmdb_payload, resolved_type = _fetch_tmdb_payload(tmdb_id, media_type_candidates, config, cache)

    if tmdb_payload:
        return tmdb_payload, resolved_type or (media_type_candidates[0] if media_type_candidates else None)

    return None, media_type_candidates[0] if media_type_candidates else fallback_type


# --- FUNZIONI DI RICERCA JELLYSEERR ---

def search_jellyseerr(query, config):
    """Cerca contenuti su Jellyseerr e restituisce la lista results."""
    if not query:
        return []
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return []
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    try:
        url = build_jellyseerr_api_url(config, "/api/v1/search")
        response = requests.get(
            url,
            headers=headers,
            params={"query": query},
            allow_redirects=False,
            timeout=10,
            stream=True,
        )
        if response_is_redirect(response):
            close_response_safely(response)
            return []
        data = read_bounded_json_response(response)
        if isinstance(data, dict):
            results = data.get("results") or []
            return results if isinstance(results, list) else []
        if isinstance(data, list):
            return data
        return []
    except requests.exceptions.RequestException:
        return []


def submit_jellyseerr_request(payload, config):
    """Invia una richiesta a Jellyseerr usando l'endpoint /api/v1/request."""
    if not isinstance(payload, dict):
        return False, "Payload non valido", None
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return False, "Configurazione Jellyseerr incompleta", None
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    try:
        response = requests.post(
            build_jellyseerr_api_url(config, "/api/v1/request"),
            headers=headers,
            json=payload,
            allow_redirects=False,
            timeout=15,
            stream=True,
        )
        if response_is_redirect(response):
            close_response_safely(response)
            return False, "Redirect Jellyseerr rifiutato", None
        data = read_bounded_json_response(response, allow_empty=True)
        return True, "Richiesta inviata", data
    except requests.exceptions.RequestException as exc:
        _log_jellyseerr_error("Invio richiesta Jellyseerr non riuscito", exc)
        return False, _JELLYSEERR_REQUEST_ERROR, None


def _coerce_jellyseerr_status(value):
    """Normalize Jellyseerr status to an integer code."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.isdigit():
            return int(lowered)
        mapping = {
            "unknown": 1,
            "pending": 2,
            "processing": 3,
            "partial": 4,
            "available": 5
        }
        return mapping.get(lowered)
    return None


def _describe_jellyseerr_status(status_code):
    """Return (status_key, status_label, icon) for Jellyseerr status codes."""
    mapping = {
        1: ("unknown", "Stato sconosciuto", "❔"),
        2: ("pending", "Richiesto", "🕒"),
        3: ("processing", "In lavorazione", "⚙️"),
        4: ("partial", "Parziale", "🌓"),
        5: ("available", "Disponibile", "✅")
    }
    return mapping.get(status_code, ("present", "Presente", "📌"))


def check_jellyseerr_availability(tmdb_id, media_type, config):
    """Check if a TMDB item is present on Jellyseerr."""
    if not tmdb_id or not config:
        return None
    if not (config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY")):
        return None
    cache = {}
    tmdb_payload, resolved_type = _fetch_tmdb_payload(
        tmdb_id,
        [_normalize_media_type(media_type)] if media_type else [],
        config,
        cache
    )
    if not tmdb_payload:
        return None

    media_info = tmdb_payload.get("mediaInfo") or tmdb_payload.get("media") or {}
    if not isinstance(media_info, dict) or not media_info:
        return None

    status_value = media_info.get("status") or tmdb_payload.get("status")
    status_code = _coerce_jellyseerr_status(status_value)
    if status_code != 5:
        return None

    status_key, status_label, icon = _describe_jellyseerr_status(status_code)
    return {
        "label": "Jellyseerr",
        "status": status_key,
        "status_label": status_label,
        "icon": icon,
        "media_type": resolved_type or _normalize_media_type(media_type)
    }
