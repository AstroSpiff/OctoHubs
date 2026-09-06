import requests
import time

from core.log_sanitization import (
    sanitize_download_reference_for_log,
    sanitize_diagnostic_text,
    sanitize_url_for_log,
)
from core.safe_output import safe_print as print
from core.outbound_redirects import response_is_redirect
from search.query_safety import search_query_for_log
from search.provider_outcomes import (
    ProviderSearchError,
    ProviderSearchResults,
    bounded_number,
    bounded_provider_rows,
    bounded_text,
    load_bounded_json,
)


INDEXER_REQUEST_TIMEOUT_SECONDS = 25


def _download_log_value(value):
    return sanitize_diagnostic_text(sanitize_download_reference_for_log(value))


def _info_log_value(value):
    return sanitize_diagnostic_text(sanitize_url_for_log(value)) if value else value


def search_prowlarr(query, media_type, config):
    """Cerca un titolo su Prowlarr usando la sua API."""
    print(f"   -> Cercando su Prowlarr: {search_query_for_log(query)!r}")
    headers = {"X-Api-Key": config["PROWLARR_API_KEY"]}
    categories = ["2000"] if media_type == "movie" else ["5000"]  # Prowlarr si aspetta una lista
    params = {"query": query, "categories": categories, "type": "search"}

    response = None
    try:
        start_time = time.perf_counter()
        response = requests.get(
            f"{config['PROWLARR_URL']}/api/v1/search",
            headers=headers,
            params=params,
            allow_redirects=False,
            timeout=INDEXER_REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )
        if response_is_redirect(response):
            raise ProviderSearchError("Redirect Prowlarr rifiutato")
        response.raise_for_status()
        elapsed = time.perf_counter() - start_time
        print(f"      -> Risposta Prowlarr in {elapsed:.1f}s (status {response.status_code})")
        data = load_bounded_json(response, provider="Prowlarr")
        if not isinstance(data, list):
            raise ProviderSearchError("Risposta inattesa da Prowlarr")
        rows, truncated = bounded_provider_rows(data, provider="Prowlarr")

        # Normalizza i risultati per assicurare mapping corretto dei campi
        normalized = []
        for idx, item in enumerate(rows):

            title = bounded_text(
                item.get("title"),
                limit=500,
                provider="Prowlarr",
                field="title",
                required=True,
            )
            magnet_url = bounded_text(
                item.get("magnetUrl"), provider="Prowlarr", field="magnetUrl"
            )
            magnet_uri = bounded_text(
                item.get("magnetUri"), provider="Prowlarr", field="magnetUri"
            )
            magnet_link = magnet_url or magnet_uri
            download_link = bounded_text(
                item.get("downloadUrl"), provider="Prowlarr", field="downloadUrl"
            )
            info_url = bounded_text(
                item.get("infoUrl"), provider="Prowlarr", field="infoUrl"
            )
            guid_value = bounded_text(
                item.get("guid"), provider="Prowlarr", field="guid"
            )

            # Debug: stampa il primo risultato
            if idx == 0:
                print("      -> [DEBUG Prowlarr] Primo risultato RAW:")
                print(f"         title: {sanitize_diagnostic_text(title)}")
                print(f"         magnetUrl: {_download_log_value(item.get('magnetUrl'))}")
                print(f"         magnetUri: {_download_log_value(item.get('magnetUri'))}")
                print(f"         downloadUrl: {_download_log_value(download_link)}")
                print(f"         infoUrl: {_info_log_value(info_url)}")
                print(f"         guid: {_download_log_value(guid_value)}")

            # Se magnetUrl/magnetUri è vuoto ma guid è un magnet, usa guid come magnet
            if not magnet_link and isinstance(guid_value, str) and guid_value.startswith("magnet:"):
                magnet_link = guid_value

            # Se download_link è un magnet, spostalo su magnet
            if isinstance(download_link, str) and download_link.startswith("magnet:"):
                if not magnet_link:
                    magnet_link = download_link
                download_link = None

            # infoUrl deve essere solo il link alla pagina web, mai magnet o download
            info_link = info_url
            if not info_link and isinstance(guid_value, str):
                # Usa guid solo se non è un magnet link
                if not guid_value.startswith("magnet:"):
                    # E se è un URL http, usalo solo se diverso dal download link
                    if guid_value.startswith("http"):
                        if guid_value != download_link:
                            info_link = guid_value
                    else:
                        info_link = guid_value

            # Se non c'è download_link ma guid è un http, potrebbe essere il download link
            if not download_link and isinstance(guid_value, str) and guid_value.startswith("http") and not magnet_link:
                download_link = guid_value

            # guid per download: preferisci magnet, poi download link
            if isinstance(magnet_link, str) and magnet_link.startswith("magnet:"):
                guid_for_download = magnet_link
            elif isinstance(download_link, str):
                guid_for_download = download_link
            else:
                guid_for_download = magnet_link or download_link

            result_dict = {
                "title": title,
                "guid": guid_for_download,
                "magnet": magnet_link if (isinstance(magnet_link, str) and magnet_link.startswith("magnet:")) else None,
                "magnetUri": magnet_link if isinstance(magnet_link, str) else None,
                "torrent": download_link if isinstance(download_link, str) else None,
                "downloadUrl": download_link if isinstance(download_link, str) else None,
                "web": info_link if isinstance(info_link, str) else None,
                "infoUrl": info_link if isinstance(info_link, str) else None,
                "indexer": bounded_text(
                    "Prowlarr" if item.get("indexer") in (None, "") else item.get("indexer"),
                    limit=200,
                    provider="Prowlarr",
                    field="indexer",
                    required=True,
                ),
                "seeders": bounded_number(
                    item.get("seeders"), provider="Prowlarr", field="seeders"
                ),
                "size": bounded_number(
                    item.get("size"), provider="Prowlarr", field="size"
                ),
            }

            # Debug: stampa il primo risultato normalizzato
            if idx == 0:
                print("      -> [DEBUG Prowlarr] Primo risultato NORMALIZZATO:")
                print(f"         magnet: {_download_log_value(result_dict['magnet'])}")
                print(f"         torrent: {_download_log_value(result_dict['torrent'])}")
                print(f"         web: {_info_log_value(result_dict['web'])}")

            normalized.append(result_dict)
        return ProviderSearchResults(normalized, provider="prowlarr", truncated=truncated)
    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare Prowlarr: {sanitize_diagnostic_text(exc)}")
        raise ProviderSearchError("Prowlarr non disponibile") from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def search_jackett(query, media_type, config):
    """Cerca un titolo su Jackett usando la sua API."""
    # Nota: questa funzione richiede _jackett_configured che è in checker.py
    # Per ora la rendiamo autonoma verificando direttamente la configurazione
    if not (config.get("JACKETT_URL") and config.get("JACKETT_API_KEY")):
        return []

    print(f"   -> Cercando su Jackett: {search_query_for_log(query)!r}")
    base_url = config["JACKETT_URL"].rstrip("/")
    endpoint = f"{base_url}/api/v2.0/indexers/all/results"
    categories = ["2000"] if media_type == "movie" else ["5000"]
    params = [
        ("apikey", config["JACKETT_API_KEY"]),
        ("Query", query),
        ("Limit", 100),
        ("Offset", 0)
    ]
    for cat in categories:
        params.append(("Category[]", cat))
    response = None
    try:
        start_time = time.perf_counter()
        response = requests.get(
            endpoint,
            params=params,
            allow_redirects=False,
            timeout=INDEXER_REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )
        if response_is_redirect(response):
            raise ProviderSearchError("Redirect Jackett rifiutato")
        response.raise_for_status()
        elapsed = time.perf_counter() - start_time
        print(f"      -> Risposta Jackett in {elapsed:.1f}s (status {response.status_code})")
        payload = load_bounded_json(response, provider="Jackett")
        results = payload.get("Results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ProviderSearchError("Risposta inattesa da Jackett")
        rows, truncated = bounded_provider_rows(results, provider="Jackett")
        normalized = []
        for idx, item in enumerate(rows):
            title = bounded_text(
                item.get("Title"),
                limit=500,
                provider="Jackett",
                field="Title",
                required=True,
            )
            magnet_link = bounded_text(
                item.get("MagnetUri"), provider="Jackett", field="MagnetUri"
            )
            download_link = bounded_text(
                item.get("Link"), provider="Jackett", field="Link"
            )
            details_link = bounded_text(
                item.get("Details"), provider="Jackett", field="Details"
            )
            guid_value = bounded_text(
                item.get("Guid"), provider="Jackett", field="Guid"
            )

            # Debug: stampa il primo risultato
            if idx == 0:
                print("      -> [DEBUG Jackett] Primo risultato RAW:")
                print(f"         Title: {sanitize_diagnostic_text(title)}")
                print(f"         MagnetUri: {_download_log_value(magnet_link)}")
                print(f"         Link: {_download_log_value(download_link)}")
                print(f"         Details: {_info_log_value(details_link)}")
                print(f"         Guid: {_download_log_value(guid_value)}")

            # Se MagnetUri è vuoto ma Guid è un magnet, usa Guid come magnet
            if not magnet_link and isinstance(guid_value, str) and guid_value.startswith("magnet:"):
                magnet_link = guid_value

            # Se Link è un magnet, spostalo su magnet
            if isinstance(download_link, str) and download_link.startswith("magnet:"):
                if not magnet_link:
                    magnet_link = download_link
                download_link = None

            # infoUrl deve essere solo il link alla pagina web del sito, mai magnet o download
            info_link = details_link
            if not info_link and isinstance(guid_value, str):
                # Usa Guid solo se non è un magnet link
                if not guid_value.startswith("magnet:"):
                    # E se è un URL http, usalo solo se diverso dal download link
                    if guid_value.startswith("http"):
                        if guid_value != download_link:
                            info_link = guid_value
                    else:
                        info_link = guid_value

            # guid per download: preferisci magnet, poi download link
            if isinstance(magnet_link, str) and magnet_link.startswith("magnet:"):
                guid_for_download = magnet_link
            elif isinstance(download_link, str):
                guid_for_download = download_link
            else:
                guid_for_download = magnet_link or download_link

            result_dict = {
                "title": title,
                "guid": guid_for_download,
                "magnet": magnet_link if (isinstance(magnet_link, str) and magnet_link.startswith("magnet:")) else None,
                "magnetUri": magnet_link if isinstance(magnet_link, str) else None,
                "torrent": download_link if isinstance(download_link, str) else None,
                "downloadUrl": download_link if isinstance(download_link, str) else None,
                "web": info_link if isinstance(info_link, str) else None,
                "infoUrl": info_link if isinstance(info_link, str) else None,
                "indexer": bounded_text(
                    "Jackett" if item.get("Indexer") in (None, "") else item.get("Indexer"),
                    limit=200,
                    provider="Jackett",
                    field="Indexer",
                    required=True,
                ),
                "seeders": bounded_number(
                    item.get("Seeders"), provider="Jackett", field="Seeders"
                ),
                "size": bounded_number(
                    item.get("Size"), provider="Jackett", field="Size"
                ),
            }

            # Debug: stampa il primo risultato normalizzato
            if idx == 0:
                print("      -> [DEBUG Jackett] Primo risultato NORMALIZZATO:")
                print(f"         magnet: {_download_log_value(result_dict['magnet'])}")
                print(f"         torrent: {_download_log_value(result_dict['torrent'])}")
                print(f"         web: {_info_log_value(result_dict['web'])}")

            normalized.append(result_dict)
        return ProviderSearchResults(normalized, provider="jackett", truncated=truncated)
    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare Jackett: {sanitize_diagnostic_text(exc)}")
        raise ProviderSearchError("Jackett non disponibile") from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
