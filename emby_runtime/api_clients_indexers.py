import requests
import time

from core.log_sanitization import (
    sanitize_download_reference_for_log,
    sanitize_text_for_log,
    sanitize_url_for_log,
)


def _download_log_value(value):
    if not isinstance(value, str):
        return value
    if value.lower().startswith(("magnet:", "http://", "https://")):
        return sanitize_download_reference_for_log(value)
    return value


def _info_log_value(value):
    return sanitize_url_for_log(value) if value else value


def search_prowlarr(query, media_type, config):
    """Cerca un titolo su Prowlarr usando la sua API."""
    print(f"   -> Cercando su Prowlarr: '{query}'")
    headers = {"X-Api-Key": config["PROWLARR_API_KEY"]}
    categories = ["2000"] if media_type == "movie" else ["5000"]  # Prowlarr si aspetta una lista
    params = {"query": query, "categories": categories, "type": "search"}

    try:
        start_time = time.perf_counter()
        response = requests.get(
            f"{config['PROWLARR_URL']}/api/v1/search",
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        elapsed = time.perf_counter() - start_time
        print(f"      -> Risposta Prowlarr in {elapsed:.1f}s (status {response.status_code})")
        data = response.json()
        if not isinstance(data, list):
            print("      -> Risposta inattesa da Prowlarr: verifica la configurazione.")
            return []

        # Normalizza i risultati per assicurare mapping corretto dei campi
        normalized = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            magnet_link = item.get("magnetUrl") or item.get("magnetUri")
            download_link = item.get("downloadUrl")
            info_url = item.get("infoUrl")
            guid_value = item.get("guid")

            # Debug: stampa il primo risultato
            if idx == 0:
                print("      -> [DEBUG Prowlarr] Primo risultato RAW:")
                print(f"         title: {title}")
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
                "indexer": item.get("indexer") or "Prowlarr",
                "seeders": item.get("seeders") or 0,
                "size": item.get("size") or 0
            }

            # Debug: stampa il primo risultato normalizzato
            if idx == 0:
                print("      -> [DEBUG Prowlarr] Primo risultato NORMALIZZATO:")
                print(f"         magnet: {_download_log_value(result_dict['magnet'])}")
                print(f"         torrent: {_download_log_value(result_dict['torrent'])}")
                print(f"         web: {_info_log_value(result_dict['web'])}")

            normalized.append(result_dict)
        return normalized
    except requests.exceptions.RequestException as e:
        print(f"   -> Impossibile contattare Prowlarr: {sanitize_text_for_log(e)}")
        return []


def search_jackett(query, media_type, config):
    """Cerca un titolo su Jackett usando la sua API."""
    # Nota: questa funzione richiede _jackett_configured che è in checker.py
    # Per ora la rendiamo autonoma verificando direttamente la configurazione
    if not (config.get("JACKETT_URL") and config.get("JACKETT_API_KEY")):
        return []

    print(f"   -> Cercando su Jackett: '{query}'")
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
    try:
        start_time = time.perf_counter()
        response = requests.get(endpoint, params=params, timeout=60)
        response.raise_for_status()
        elapsed = time.perf_counter() - start_time
        print(f"      -> Risposta Jackett in {elapsed:.1f}s (status {response.status_code})")
        payload = response.json()
        results = payload.get("Results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            print("      -> Risposta inattesa da Jackett.")
            return []
        normalized = []
        for idx, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            title = item.get("Title")
            magnet_link = item.get("MagnetUri")
            download_link = item.get("Link")
            details_link = item.get("Details")
            guid_value = item.get("Guid")

            # Debug: stampa il primo risultato
            if idx == 0:
                print("      -> [DEBUG Jackett] Primo risultato RAW:")
                print(f"         Title: {title}")
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
                "indexer": item.get("Indexer") or "Jackett",
                "seeders": item.get("Seeders") or 0,
                "size": item.get("Size") or 0
            }

            # Debug: stampa il primo risultato normalizzato
            if idx == 0:
                print("      -> [DEBUG Jackett] Primo risultato NORMALIZZATO:")
                print(f"         magnet: {_download_log_value(result_dict['magnet'])}")
                print(f"         torrent: {_download_log_value(result_dict['torrent'])}")
                print(f"         web: {_info_log_value(result_dict['web'])}")

            normalized.append(result_dict)
        return normalized
    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare Jackett: {sanitize_text_for_log(exc)}")
        return []
