import requests
import time

from core.http_response_limits import (
    close_response_safely,
    read_bounded_json_response,
    read_bounded_text_response,
)
from core.log_sanitization import (
    sanitize_download_reference_for_log,
    sanitize_diagnostic_text,
    sanitize_url_for_log,
)
from core.safe_output import safe_print as print


def _normalize_download_url(link: str) -> str:
    if not link or not isinstance(link, str):
        return link
    cleaned = link.replace("&amp;", "&").strip()
    if not cleaned.startswith(("http://", "https://")):
        return cleaned
    if "?" not in cleaned:
        return cleaned
    base, rest = cleaned.split("?", 1)
    if "#" in rest:
        query, frag = rest.split("#", 1)
        frag = f"#{frag}"
    else:
        query, frag = rest, ""
    # Preserve literal plus signs that would be decoded as spaces
    query = query.replace("+", "%2B")
    return f"{base}?{query}{frag}"


def send_to_qbittorrent(link, config, max_retries=2):
    """
    Invia un torrent (magnet link o URL .torrent) a qBittorrent.

    Args:
        link: Magnet link o URL del file .torrent
        config: Configurazione con credenziali qBittorrent
        max_retries: Numero massimo di tentativi in caso di errore (default: 2)

    Returns:
        Tupla (success: bool, message: str)
    """
    qb_url = config.get("QBITTORRENT_URL")
    qb_user = config.get("QBITTORRENT_USERNAME")
    qb_pass = config.get("QBITTORRENT_PASSWORD")

    if not (qb_url and qb_user and qb_pass):
        return False, "Configurazione qBittorrent incompleta."

    if not link:
        return False, "Link torrent mancante."

    # Validazione base del link
    link = _normalize_download_url(link.strip())
    is_magnet = link.startswith("magnet:?")
    is_url = link.startswith("http://") or link.startswith("https://")

    if not (is_magnet or is_url):
        return False, "Link non valido: deve essere un magnet link o URL HTTP(S)."

    print(f"   -> [QB] Invio torrent a qBittorrent: {sanitize_download_reference_for_log(link)}")

    session = requests.Session()
    base_url = qb_url.rstrip('/')

    for attempt in range(max_retries + 1):
        try:
            # Login a qBittorrent
            print(f"   -> [QB] Login qBittorrent (tentativo {attempt + 1}/{max_retries + 1})...")
            login_resp = session.post(
                f"{base_url}/api/v2/auth/login",
                data={"username": qb_user, "password": qb_pass},
                allow_redirects=False,
                timeout=15,  # Aumentato da 10 a 15 secondi
                stream=True,
            )

            if login_resp.status_code != 200:
                close_response_safely(login_resp)
                error_msg = f"Login fallito: HTTP {login_resp.status_code}"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg

            login_text = read_bounded_text_response(login_resp, require_success=False).strip()
            if login_text != "Ok.":
                error_msg = "Login fallito: risposta inattesa"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg

            print("   -> [QB] Login OK, invio torrent...")

            # Aggiunta torrent
            add_resp = session.post(
                f"{base_url}/api/v2/torrents/add",
                data={"urls": link},
                allow_redirects=False,
                timeout=20,  # Aumentato da 10 a 20 secondi per torrent grandi
                stream=True,
            )

            add_text = read_bounded_text_response(add_resp, require_success=False).strip()

            # FIX CRITICO: Parentesi corrette per la condizione logica
            if add_resp.status_code == 200 and (add_text == "Ok." or add_text == ""):
                # Verifica che il torrent sia stato effettivamente aggiunto
                time.sleep(1)  # Attendi che qBittorrent processi il torrent

                # Ottieni lista torrent per verificare
                torrents_resp = session.get(
                    f"{base_url}/api/v2/torrents/info",
                    params={"limit": 10, "sort": "added_on", "reverse": "true"},
                    allow_redirects=False,
                    timeout=10,
                    stream=True,
                )

                if torrents_resp.status_code == 200:
                    try:
                        torrents = read_bounded_json_response(torrents_resp)
                        if torrents and len(torrents) > 0:
                            latest_torrent = torrents[0]
                            torrent_name = sanitize_diagnostic_text(latest_torrent.get("name", ""))
                            torrent_state = sanitize_diagnostic_text(latest_torrent.get("state", ""))
                            print(f"   -> [QB] ✓ Torrent aggiunto: '{torrent_name}' (stato: {torrent_state})")
                            return True, f"Torrent aggiunto: {torrent_name}"
                    except Exception:
                        pass
                else:
                    close_response_safely(torrents_resp)

                print("   -> [QB] ⚠️ qBittorrent ha accettato il link, ma nessun torrent trovato nella lista")
                print(f"   -> [QB] Link inviato: {sanitize_download_reference_for_log(link)}")
                return True, "Link inviato a qBittorrent (verificare manualmente)"

            # Errore nell'aggiunta
            error_msg = f"Errore aggiunta (HTTP {add_resp.status_code})"

            # Retry solo per errori server (5xx) o timeout
            if add_resp.status_code >= 500 and attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento...")
                time.sleep(2)
                continue

            print(f"   -> [QB] ✗ {error_msg}")
            return False, error_msg

        except requests.exceptions.Timeout:
            error_msg = "Timeout connessione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(1)
                continue
            print(f"   -> [QB] ✗ {error_msg} dopo {max_retries + 1} tentativi")
            return False, error_msg

        except requests.exceptions.ConnectionError:
            error_msg = (
                "Impossibile connettersi a qBittorrent "
                f"({sanitize_diagnostic_text(sanitize_url_for_log(qb_url))})"
            )
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento...")
                time.sleep(2)
                continue
            print(f"   -> [QB] ✗ {error_msg}")
            return False, error_msg

        except requests.exceptions.RequestException as exc:
            error_msg = "Errore comunicazione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg} ({type(exc).__name__}), ritento...")
                time.sleep(1)
                continue
            print(
                f"   -> [QB] ✗ {error_msg}: {type(exc).__name__} - "
                f"{sanitize_diagnostic_text(exc)}"
            )
            return False, error_msg

    return False, f"Fallito dopo {max_retries + 1} tentativi"


def send_to_qbittorrent_batch(links, config, max_retries=2):
    """
    Invia una lista di torrent (magnet link o URL .torrent) a qBittorrent usando
    una singola sessione/login.

    Args:
        links: Lista di magnet link o URL del file .torrent
        config: Configurazione con credenziali qBittorrent
        max_retries: Numero massimo di tentativi in caso di errore (default: 2)

    Returns:
        Tupla (success: bool, message: str, details: dict)
        details: { "sent": int, "failed": list[dict], "total": int }
    """
    qb_url = config.get("QBITTORRENT_URL")
    qb_user = config.get("QBITTORRENT_USERNAME")
    qb_pass = config.get("QBITTORRENT_PASSWORD")

    if not (qb_url and qb_user and qb_pass):
        return False, "Configurazione qBittorrent incompleta.", {"sent": 0, "failed": [], "total": 0}

    if not links or not isinstance(links, list):
        return False, "Lista link mancante.", {"sent": 0, "failed": [], "total": 0}

    valid_links = []
    failed = []
    for raw_link in links:
        if not raw_link:
            continue
        link = str(raw_link).strip()
        if not link:
            continue
        is_magnet = link.startswith("magnet:?")
        is_url = link.startswith("http://") or link.startswith("https://")
        if not (is_magnet or is_url):
            failed.append({
                "link": sanitize_download_reference_for_log(link),
                "error": "Link non valido (solo magnet o URL HTTP/S).",
            })
            continue
        if is_url:
            link = _normalize_download_url(link)
        valid_links.append(link)

    if not valid_links:
        message = "Nessun link valido da inviare."
        return False, message, {"sent": 0, "failed": failed, "total": len(links)}

    session = requests.Session()
    base_url = qb_url.rstrip('/')

    for attempt in range(max_retries + 1):
        try:
            print(f"   -> [QB] Login qBittorrent (batch) (tentativo {attempt + 1}/{max_retries + 1})...")
            login_resp = session.post(
                f"{base_url}/api/v2/auth/login",
                data={"username": qb_user, "password": qb_pass},
                allow_redirects=False,
                timeout=15,
                stream=True,
            )
            if login_resp.status_code != 200:
                close_response_safely(login_resp)
                error_msg = f"Login fallito: HTTP {login_resp.status_code}"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg, {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}

            login_text = read_bounded_text_response(login_resp, require_success=False).strip()
            if login_text != "Ok.":
                error_msg = "Login fallito: risposta inattesa"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg, {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}

            print("   -> [QB] Login OK, invio batch torrent...")
            add_resp = session.post(
                f"{base_url}/api/v2/torrents/add",
                data={"urls": "\n".join(valid_links)},
                allow_redirects=False,
                timeout=30,
                stream=True,
            )
            add_text = read_bounded_text_response(add_resp, require_success=False).strip()
            if add_resp.status_code == 200 and (add_text == "Ok." or add_text == ""):
                sent = len(valid_links)
                message = f"Inviati {sent} elementi a qBittorrent"
                return True, message, {"sent": sent, "failed": failed, "total": sent + len(failed)}

            print(f"   -> [QB] Batch fallito: HTTP {add_resp.status_code}")
            # Fallback: invio uno per uno per isolare errori
            sent = 0
            for link in valid_links:
                try:
                    resp = session.post(
                        f"{base_url}/api/v2/torrents/add",
                        data={"urls": link},
                        allow_redirects=False,
                        timeout=20,
                        stream=True,
                    )
                    text = read_bounded_text_response(resp, require_success=False).strip()
                    if resp.status_code == 200 and (text == "Ok." or text == ""):
                        sent += 1
                    else:
                        failed.append({
                            "link": sanitize_download_reference_for_log(link),
                            "error": f"Errore aggiunta (HTTP {resp.status_code})",
                        })
                except requests.exceptions.RequestException as exc:
                    failed.append({
                        "link": sanitize_download_reference_for_log(link),
                        "error": f"Errore comunicazione: {type(exc).__name__}",
                    })
                time.sleep(0.2)
            success = sent > 0
            message = f"Inviati {sent} elementi a qBittorrent" if success else "Nessun elemento inviato a qBittorrent"
            return success, message, {"sent": sent, "failed": failed, "total": sent + len(failed)}

        except requests.exceptions.Timeout:
            error_msg = "Timeout connessione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(1)
                continue
            return False, error_msg, {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}

        except requests.exceptions.ConnectionError:
            error_msg = (
                "Impossibile connettersi a qBittorrent "
                f"({sanitize_diagnostic_text(sanitize_url_for_log(qb_url))})"
            )
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento...")
                time.sleep(2)
                continue
            return False, error_msg, {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}

        except requests.exceptions.RequestException as exc:
            error_msg = "Errore comunicazione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg} ({type(exc).__name__}), ritento...")
                time.sleep(1)
                continue
            return False, error_msg, {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}

    return False, f"Fallito dopo {max_retries + 1} tentativi", {"sent": 0, "failed": failed, "total": len(valid_links) + len(failed)}
