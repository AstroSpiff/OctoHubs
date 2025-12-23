# api_clients.py
import requests
import copy
import time
import re
from datetime import datetime, timezone
from typing import Any, Tuple, Dict, cast, Optional

# Nota: Le funzioni che dipendono da variabili globali o da TraktClient
# rimangono in checker.py per evitare dipendenze circolari

from utils import _normalize_media_type

# --- COSTANTI ---
EMBY_REQUEST_TIMEOUT = 6

EMBY_ACTIONS = {
    "refresh_libraries": {
        "label": "Aggiorna librerie",
        "method": "POST",
        "path": "Library/Refresh",
        "params": {"Recursive": "true"}
    },
    "refresh_metadata": {
        "label": "Aggiorna metadati",
        "method": "POST",
        "path": "Items/Refresh",
        "params": {"Recursive": "true"}
    },
    "strm_extract": {
        "label": "Avvia STRM Extract",
        "method": "POST",
        "path": "Plugins/strm-extract/Scan"
    },
    "restart_server": {
        "label": "Riavvia server",
        "method": "POST",
        "path": "System/Restart"
    }
}


# --- FUNZIONI EMBY ---

def _emby_has_credentials(server):
    if not server:
        return False
    url = (server.get("url") or "").strip()
    token = (server.get("api_key") or "").strip()
    return bool(url and token)


def _emby_base_url(server):
    if not server:
        return None
    url = (server.get("url") or "").strip()
    if not url:
        return None
    return url.rstrip('/')


def _call_emby_api(server, path, method="GET", params=None, json_payload=None) -> Tuple[bool, Any]:
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        return False, "Credenziali Emby mancanti"
    target = f"{base_url}/{path.lstrip('/')}"
    headers = {
        "X-Emby-Token": token,
        "Accept": "application/json"
    }
    try:
        if method.upper() == "GET":
            response = requests.get(target, headers=headers, params=params or {}, timeout=EMBY_REQUEST_TIMEOUT)
        else:
            response = requests.request(
                method.upper(),
                target,
                headers=headers,
                params=params or {},
                json=json_payload,
                timeout=EMBY_REQUEST_TIMEOUT
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return True, payload
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None:
            body = (response.text or "").strip()
            if len(body) > 400:
                body = body[:400] + "…"
            return False, f"{response.status_code} {response.reason}: {body}" if body else f"{response.status_code} {response.reason}"
        return False, str(exc)
    except requests.RequestException as exc:
        return False, str(exc)


def _fetch_emby_scheduled_tasks(server):
    success, payload = _call_emby_api(server, "ScheduledTasks")
    if not success:
        return [], payload
    tasks = []
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return [], "Risposta ScheduledTasks inattesa"
    for entry in items:
        raw_progress = entry.get("CurrentProgressPercentage")
        if raw_progress is None:
            raw_progress = entry.get("Progress") or entry.get("ProgressPercent")
        progress = raw_progress if isinstance(raw_progress, (int, float)) else 0
        state = entry.get("State")
        is_running = entry.get("IsRunning")
        if not isinstance(is_running, bool):
            is_running = False
        if not is_running and isinstance(state, str) and state.lower() == "running":
            is_running = True
        if not is_running and isinstance(progress, (int, float)) and progress > 0:
            is_running = True
        tasks.append({
            "id": entry.get("Id"),
            "key": entry.get("Key"),
            "name": entry.get("Name") or entry.get("DisplayName") or entry.get("TaskName"),
            "last_run": entry.get("LastRun"),
            "last_run_duration": entry.get("LastRunDurationMs"),
            "status": "enabled" if entry.get("IsEnabled") else "disabilitato",
            "next_run": entry.get("NextRun"),
            "state": state,
            "progress": progress,
            "is_running": is_running,
            "last_execution_result": entry.get("LastExecutionResult"),
            "end_time": entry.get("EndTimeUtc")
        })
    return tasks, None


def _fetch_emby_status(server):
    if not _emby_has_credentials(server):
        return {"ok": False, "error": "API key o URL non corretti"}
    success, payload = _call_emby_api(server, "System/Info")
    if not success:
        return {"ok": False, "error": payload}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Risposta Emby inattesa (payload non JSON)."}
    payload_dict = cast(Dict[str, Any], payload)
    server_id = payload_dict.get("Id") or payload_dict.get("ServerId")
    return {
        "ok": True,
        "version": payload_dict.get("Version"),
        "name": payload_dict.get("ServerName") or payload_dict.get("Name"),
        "last_check": datetime.now(timezone.utc).astimezone().isoformat(),
        "server_id": server_id
    }


def _fetch_emby_libraries(server):
    success, payload = _call_emby_api(server, "Library/VirtualFolders")
    if not success:
        return [], payload
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return [], "Risposta VirtualFolders inattesa"
    libraries = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        collection_type = entry.get("CollectionType")
        if isinstance(collection_type, str):
            collection_type = collection_type.lower().strip()
        if not collection_type:
            collection_type = "folder"
        if collection_type in ("mixed", "homevideos"):
            collection_type = "folder"
        if collection_type not in ("movies", "tvshows", "folder"):
            continue
        libraries.append({
            "id": entry.get("Id") or entry.get("ItemId"),
            "name": entry.get("Name"),
            "collection_type": collection_type
        })
    return libraries, None


def _format_ticks(ticks):
    if not isinstance(ticks, (int, float)):
        return ""
    total_seconds = int(ticks / 10_000_000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _pick_stream(streams, stream_type, default_only=False):
    if not isinstance(streams, list):
        return None
    candidates = [s for s in streams if isinstance(s, dict) and s.get("Type") == stream_type]
    if default_only:
        defaults = [s for s in candidates if s.get("IsDefault")]
        if defaults:
            return defaults[0]
    return candidates[0] if candidates else None


def _fetch_emby_active_sessions(server):
    success, payload = _call_emby_api(server, "Sessions")
    if not success:
        return [], payload
    if not isinstance(payload, list):
        return [], "Risposta Sessions inattesa"
    sessions = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        now_playing_raw = entry.get("NowPlayingItem")
        if not isinstance(now_playing_raw, dict):
            continue
        play_state = entry.get("PlayState") or {}
        if not isinstance(play_state, dict):
            continue
        has_position = play_state.get("PositionTicks") is not None
        is_paused = play_state.get("IsPaused")
        if not has_position and is_paused is None:
            continue
        position_ticks = play_state.get("PositionTicks") or 0
        now_playing = now_playing_raw
        title = now_playing.get("Name") or now_playing.get("SeriesName") or "Titolo"
        year = now_playing.get("ProductionYear")
        media_type = (now_playing.get("Type") or "").lower()
        series_name = now_playing.get("SeriesName") or ""
        season = now_playing.get("ParentIndexNumber")
        episode = now_playing.get("IndexNumber")
        episode_title = now_playing.get("EpisodeTitle") or now_playing.get("Name") or ""
        if media_type in ("episode", "series"):
            base_title = series_name or title
            if season is not None and episode is not None:
                title = f"{base_title} S{int(season)}:E{int(episode)}"
            else:
                title = base_title or title
            if episode_title:
                title = f"{title} - {episode_title}"
        user = entry.get("UserName") or (entry.get("User") or {}).get("Name") or "Utente"
        device = entry.get("DeviceName") or entry.get("Client") or "Client"
        app_version = entry.get("ApplicationVersion") or ""
        app_icon = entry.get("AppIconUrl") or ""
        client = entry.get("Client") or ""
        remote_ip = entry.get("RemoteEndPoint") or ""
        protocol = entry.get("Protocol") or ""
        state = "In pausa" if is_paused else "In riproduzione" if is_paused is not None else ""
        transcoding = entry.get("TranscodingInfo") or {}
        play_method = play_state.get("PlayMethod") or ""
        video_direct = transcoding.get("IsVideoDirect")
        audio_direct = transcoding.get("IsAudioDirect")
        if video_direct is None and audio_direct is None:
            is_transcoding = bool(transcoding) or str(play_method).lower() == "transcode"
            video_direct = not is_transcoding
            audio_direct = not is_transcoding
        video_mode = "diretta" if video_direct else "transcodifica"
        audio_mode = "diretta" if audio_direct else "transcodifica"
        streams = now_playing.get("MediaStreams") or []
        video_stream = _pick_stream(streams, "Video")
        audio_stream = _pick_stream(streams, "Audio", default_only=True) or _pick_stream(streams, "Audio")
        container_stream = _pick_stream(streams, "Video")
        video_label = ""
        if video_stream:
            width = video_stream.get("Width")
            height = video_stream.get("Height")
            codec = video_stream.get("Codec") or ""
            if width and height:
                video_label = f"{height}p {codec}".strip()
            else:
                video_label = f"{codec}".strip()
        audio_label = ""
        if audio_stream:
            audio_label = audio_stream.get("DisplayTitle") or audio_stream.get("Codec") or ""
        stream_container = now_playing.get("Container") or ""
        if container_stream and container_stream.get("Container"):
            stream_container = container_stream.get("Container")
        container = now_playing.get("Container") or ""
        bitrate = now_playing.get("Bitrate") or 0
        runtime_ticks = now_playing.get("RunTimeTicks") or 0
        play_pos = _format_ticks(position_ticks)
        play_total = _format_ticks(runtime_ticks)
        playback_percent = None
        if position_ticks and runtime_ticks:
            playback_percent = max(0, min(100, (position_ticks / runtime_ticks) * 100))
        transcode_container = transcoding.get("Container") or transcoding.get("SubProtocol") or ""
        transcode_bitrate = transcoding.get("Bitrate") or 0
        transcode_reasons = transcoding.get("TranscodeReasons") or []
        transcode_percent = transcoding.get("CompletionPercentage")
        if isinstance(transcode_percent, (int, float)):
            transcode_percent = max(0, min(100, float(transcode_percent)))
        else:
            transcode_percent = None
        sessions.append({
            "session_id": entry.get("Id") or "",
            "media_type": media_type,
            "series_name": series_name,
            "season_number": season,
            "episode_number": episode,
            "episode_title": episode_title,
            "title": title,
            "year": year,
            "playback_percent": playback_percent,
            "transcode_percent": transcode_percent,
            "user": user,
            "device": device,
            "client": client,
            "ip": remote_ip,
            "protocol": protocol,
            "app_version": app_version,
            "app_icon": app_icon,
            "state": state,
            "video_mode": video_mode,
            "audio_mode": audio_mode,
            "video_label": video_label,
            "audio_label": audio_label,
            "container": container,
            "stream_container": stream_container,
            "bitrate": bitrate,
            "play_method": play_method,
            "transcode_container": transcode_container,
            "transcode_bitrate": transcode_bitrate,
            "transcode_reasons": transcode_reasons,
            "position": play_pos,
            "duration": play_total,
            "paused": bool(is_paused)
        })
    return sessions, None


def _trigger_library_scan(server: Dict[str, Any], library_id: str):
    if not library_id:
        return False, "ID libreria mancante"
    return _call_emby_api(server, f"Items/{library_id}/Refresh", method="POST")


def _stop_emby_task(server: Dict[str, Any], task_id: str):
    if not task_id:
        return False, "ID task mancante"
    # Prova diversi endpoint e metodi
    attempts = [
        (f"ScheduledTasks/Running/{task_id}", "DELETE"),
        (f"ScheduledTasks/Running/{task_id}/Stop", "POST"),
        (f"ScheduledTasks/Running/{task_id}/Cancel", "POST"),
        (f"ScheduledTasks/{task_id}/Cancel", "POST"),
        (f"ScheduledTasks/Running/{task_id}", "POST")
    ]
    last_payload = "Operazione non supportata"
    for path, method in attempts:
        print(f"[STOP_TASK] Provo {method} {path}")
        success, payload = _call_emby_api(server, path, method=method)
        print(f"[STOP_TASK] Risultato: success={success}, payload={payload}")
        if success:
            return success, payload
        last_payload = payload
    return False, last_payload


def _run_emby_scheduled_task(server, task_id):
    server_uuid = server.get("server_id") or server.get("status", {}).get("server_id")
    params = {}
    if server_uuid:
        params["serverId"] = server_uuid
    paths = [
        f"ScheduledTasks/{task_id}/Run",
        f"ScheduledTasks/{server_uuid}/{task_id}/Run" if server_uuid else "",
        f"ScheduledTasks/Run/{task_id}",
        f"ScheduledTasks/Run/{server_uuid}/{task_id}" if server_uuid else ""
    ]
    paths.extend([
        f"ScheduledTasks/Running/{task_id}",
        f"ScheduledTasks/Running/{server_uuid}/{task_id}" if server_uuid else ""
    ])
    for path in [p for p in paths if p]:
        success, payload = _call_emby_api(server, path, method="POST", params=params)
        if success:
            return True, payload
        if isinstance(payload, str) and any(code in payload for code in ("404", "405")):
            continue
        return success, payload
    return False, "Scheduled Task non disponibile"


def _autodetect_emby_strm_task_id(server):
    success, payload = _call_emby_api(server, "ScheduledTasks")
    if not success:
        return None
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return None
    # Priorità: Key esplicita del plugin
    for entry in items:
        if isinstance(entry, dict) and entry.get("Key") == "StrmExtractTask" and entry.get("Id"):
            return str(entry["Id"])
    # Fallback: nomi che contengono "strm" se ce n'è uno solo
    strm_candidates = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or entry.get("DisplayName") or "")
        if "strm" in name.lower() and entry.get("Id"):
            strm_candidates.append(str(entry["Id"]))
    if len(strm_candidates) == 1:
        return strm_candidates[0]
    return None


def _autodetect_emby_task_id_by_key(server, task_key):
    if not task_key:
        return None
    success, payload = _call_emby_api(server, "ScheduledTasks")
    if not success:
        return None
    items = payload if isinstance(payload, list) else (payload.get("Items") if isinstance(payload, dict) else [])
    if not isinstance(items, list):
        return None
    for entry in items:
        if isinstance(entry, dict) and entry.get("Key") == task_key and entry.get("Id"):
            return str(entry["Id"])
    return None


def _execute_emby_action(server, action_key):
    action = EMBY_ACTIONS.get(action_key)
    if not action:
        return False, f"Azione '{action_key}' non supportata"
    if action_key == "strm_extract":
        task_id = (server.get("strm_task_id") or "").strip()
        if not task_id:
            task_id = _autodetect_emby_strm_task_id(server) or ""
        if not task_id:
            return False, "Task STRM non configurato (usa l'ID di 'Process Strm targets')"
        return _run_emby_scheduled_task(server, task_id)
    if action_key == "refresh_metadata":
        task_id = _autodetect_emby_task_id_by_key(server, "ScanInternalMetadataFolderTask") or ""
        if not task_id:
            # Fallback: alcune installazioni espongono solo "Scan media library"
            task_id = _autodetect_emby_task_id_by_key(server, "RefreshLibrary") or ""
        if not task_id:
            return False, "Task metadati non disponibile (manca Scheduled Task 'Scan Metadata Folder')."
        return _run_emby_scheduled_task(server, task_id)
    return _call_emby_api(
        server,
        action["path"],
        method=action.get("method", "POST"),
        params=action.get("params")
    )


def _prepare_emby_servers_for_view(servers, lazy=False):
    prepared = []
    for server in servers or []:
        decorated = copy.deepcopy(server)
        if lazy:
            decorated["status"] = {
                "ok": None,
                "version": None,
                "name": decorated.get("name") or "Server Emby",
                "last_check": None,
                "server_id": decorated.get("server_id")
            }
            decorated["scheduled_tasks"] = []
            decorated["scheduled_tasks_error"] = None
        else:
            decorated["status"] = _fetch_emby_status(server)
            decorated["server_id"] = decorated["status"].get("server_id")
            tasks, error = _fetch_emby_scheduled_tasks(server)
            decorated["scheduled_tasks"] = tasks
            decorated["scheduled_tasks_error"] = error
        prepared.append(decorated)
    return prepared


# --- FUNZIONI JELLYSEERR ---

def get_jellyseerr_requests(config, silent=False):
    """Recupera le richieste in sospeso da Jellyseerr."""
    if not silent:
        print("1. Recupero le richieste da Jellyseerr...")
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    try:
        all_results = []
        # Recupera sia le richieste in attesa (pending) che quelle approvate (approved)
        for status in ["pending", "approved"]:
            if not silent:
                print(f"   - Stato interrogato: {status}")
            params = {"take": 100, "skip": 0, "filter": status, "sort": "added"}
            response = requests.get(f"{config['JELLYSEERR_URL']}/api/v1/request", headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            all_results.extend(data.get("results", []))
        if not silent:
            print(f"   -> Recuperate {len(all_results)} richieste (pendenti + approvate).")
        return all_results
    except requests.exceptions.RequestException as e:
        if not silent:
            print(f"   -> Impossibile contattare Jellyseerr: {e}")
        return []


# --- FUNZIONI QBITTORRENT ---

def send_to_qbittorrent(link, config):
    qb_url = config.get("QBITTORRENT_URL")
    qb_user = config.get("QBITTORRENT_USERNAME")
    qb_pass = config.get("QBITTORRENT_PASSWORD")

    if not (qb_url and qb_user and qb_pass and link):
        return False, "Configurazione qBittorrent incompleta."

    session = requests.Session()
    try:
        login_resp = session.post(
            f"{qb_url.rstrip('/')}/api/v2/auth/login",
            data={"username": qb_user, "password": qb_pass},
            timeout=10
        )
        if login_resp.status_code != 200 or login_resp.text.strip() != "Ok.":
            return False, "Login qBittorrent fallito."
        add_resp = session.post(
            f"{qb_url.rstrip('/')}/api/v2/torrents/add",
            data={"urls": link},
            timeout=10
        )
        if add_resp.status_code == 200 and add_resp.text.strip() == "Ok." or add_resp.text.strip() == "":
            return True, "Torrent aggiunto."
        return False, f"Errore aggiunta torrent: {add_resp.text}"
    except requests.exceptions.RequestException as exc:
        return False, f"Errore qBittorrent: {exc}"


# --- FUNZIONI DI PING GENERICHE ---

def _ping_api_service(url, headers=None, params=None, timeout=10):
    """
    Funzione generica per fare ping a un servizio API.

    Args:
        url: URL completo dell'endpoint
        headers: Dizionario degli header HTTP (opzionale)
        params: Parametri query string (opzionale)
        timeout: Timeout in secondi (default: 10)

    Returns:
        Tupla (success: bool, message: str)
    """
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        return True, "Connessione OK"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


def _ping_jellyseerr(config):
    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    params = {"take": 1, "skip": 0, "filter": "pending", "sort": "added"}
    url = f"{config['JELLYSEERR_URL']}/api/v1/request"
    return _ping_api_service(url, headers=headers, params=params)


def _ping_prowlarr(config):
    headers = {"X-Api-Key": config["PROWLARR_API_KEY"]}
    url = f"{config['PROWLARR_URL']}/api/v1/system/status"
    return _ping_api_service(url, headers=headers)


def _ping_qbittorrent(config):
    qb_url = config.get("QBITTORRENT_URL")
    qb_user = config.get("QBITTORRENT_USERNAME")
    qb_pass = config.get("QBITTORRENT_PASSWORD")

    if not (qb_url and qb_user and qb_pass):
        return False, "Configurazione incompleta"

    session = requests.Session()
    try:
        login_resp = session.post(
            f"{qb_url.rstrip('/')}/api/v2/auth/login",
            data={"username": qb_user, "password": qb_pass},
            timeout=10
        )
        if login_resp.status_code == 200 and login_resp.text.strip() == "Ok.":
            return True, "Connessione OK"
        return False, login_resp.text.strip() or "Login fallito"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


# Nota: _ping_jackett, _ping_trakt, _ping_database e le funzioni _check_*_connection
# rimangono in checker.py perché dipendono da funzioni helper (_jackett_configured,
# _merge_trakt_settings, _get_trakt_client, _db_enabled, _get_db_backend) che
# richiedono accesso alle variabili globali e alla configurazione attiva


# --- FUNZIONI HELPER PER JELLYSEERR E TMDB ---

def _try_parse_int(value):
    """Parse value to integer if possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_tmdb_id(*sources):
    """Extract TMDB ID from multiple sources."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tmdbId", "tmdb_id", "tmdbid", "mediaId", "media_id"):
            value = source.get(key)
            parsed = _try_parse_int(value)
            if parsed:
                return parsed
    return None


def _fetch_tmdb_payload(tmdb_id, media_type_candidates, config, cache):
    """Fetch TMDB payload from Jellyseerr API."""
    if not tmdb_id:
        return None, None

    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    tried = set()
    candidates = list(media_type_candidates or []) + ["movie", "tv"]

    for candidate in candidates:
        normalized = _normalize_media_type(candidate)
        if not normalized or normalized in tried:
            continue
        tried.add(normalized)
        cache_key = f"tmdb:{normalized}:{tmdb_id}"
        if cache_key in cache:
            return cache[cache_key], normalized
        endpoint = f"/api/v1/{normalized}/{tmdb_id}"
        try:
            response = requests.get(
                f"{config['JELLYSEERR_URL']}{endpoint}",
                headers=headers,
                timeout=15
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            cache[cache_key] = data
            return data, normalized
        except requests.exceptions.RequestException:
            continue

    return None, None


# --- FUNZIONI JELLYSEERR ESTESE ---

def fetch_request_details(request_id, config, cache):
    """Recupera dettagli aggiuntivi di una richiesta se non presenti nella raccolta principale."""
    if not request_id:
        return None
    if request_id in cache:
        return cache[request_id]

    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    try:
        response = requests.get(
            f"{config['JELLYSEERR_URL']}/api/v1/request/{request_id}",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        cache[request_id] = data
        return data
    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile ottenere dettagli per la richiesta {request_id}: {exc}")
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


# --- FUNZIONI DI RICERCA INDEXER ---

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
        return data
    except requests.exceptions.RequestException as e:
        print(f"   -> Impossibile contattare Prowlarr: {e}")
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
        for item in results:
            if not isinstance(item, dict):
                continue
            title = item.get("Title")
            magnet_link = item.get("MagnetUri")
            download_link = item.get("Link")
            info_link = item.get("Details") or item.get("Guid")
            normalized.append({
                "title": title,
                "guid": item.get("Guid") or magnet_link or download_link,
                "downloadUrl": download_link if isinstance(download_link, str) else None,
                "infoUrl": info_link if isinstance(info_link, str) else None,
                "indexer": item.get("Indexer") or "Jackett",
                "seeders": item.get("Seeders") or 0,
                "size": item.get("Size") or 0,
                "magnetUri": magnet_link
            })
        return normalized
    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare Jackett: {exc}")
        return []
