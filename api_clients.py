# api_clients.py
import requests
import copy
import time
import re
from datetime import datetime, timezone
from typing import Any, Tuple, Dict, cast, Optional

print("[API_CLIENTS] Module loaded - VERSION 2026-01-08-21:40 with metadata fix")

# Nota: Le funzioni che dipendono da variabili globali o da TraktClient
# rimangono in checker.py per evitare dipendenze circolari

from utils import _normalize_media_type

# --- COSTANTI ---
EMBY_REQUEST_TIMEOUT = 30

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

__all__ = [
    "EMBY_ACTIONS",
    "_emby_has_credentials",
    "_emby_base_url",
    "_call_emby_api",
    "_fetch_emby_scheduled_tasks",
    "_fetch_emby_virtual_folders",
    "_fetch_emby_status",
    "_fetch_emby_libraries",
    "_format_ticks",
    "_fetch_emby_active_sessions",
    "_trigger_library_scan",
    "_stop_emby_task",
    "_run_emby_scheduled_task",
    "_autodetect_emby_strm_task_id",
    "_autodetect_emby_task_id_by_key",
    "_execute_emby_action",
    "_prepare_emby_servers_for_view",
    "get_jellyseerr_requests",
    "send_to_qbittorrent",
    "_ping_api_service",
    "_ping_jellyseerr",
    "_ping_prowlarr",
    "_ping_qbittorrent",
    "_extract_tmdb_id",
    "_fetch_tmdb_payload",
    "fetch_request_details",
    "fetch_media_info",
    "search_jellyseerr",
    "submit_jellyseerr_request",
    "search_prowlarr",
    "search_jackett",
    "search_tmdb",
    "get_tmdb_tv_details",
    "check_emby_availability",
    "check_jellyseerr_availability",
    "_fetch_emby_users_list",
    "_fetch_emby_user_details",
    "_update_emby_user_policy",
    "_update_emby_user_configuration",
    "_update_emby_user_password",
    "_rename_emby_user",
    "_create_emby_user",
    "_fetch_emby_user_items_for_sync",
    "_fetch_emby_user_last_playback",
    "_mark_emby_item_played",
    "_mark_emby_item_played",
    "_mark_emby_item_unplayed"
]



def _call_emby_api(server, path, method="GET", params=None, json_payload=None) -> Tuple[bool, Any]:
    base_url = _emby_base_url(server)
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        return False, "Credenziali Emby mancanti"
    target = f"{base_url}/{path.lstrip('/')}"
    merged_params = dict(params or {})
    if "api_key" not in merged_params:
        merged_params["api_key"] = token
    headers = {
        "X-Emby-Token": token,
        "Accept": "application/json"
    }
    try:
        if method.upper() == "GET":
            response = requests.get(target, headers=headers, params=merged_params, timeout=EMBY_REQUEST_TIMEOUT)
        else:
            response = requests.request(
                method.upper(),
                target,
                headers=headers,
                params=merged_params,
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


def _fetch_emby_virtual_folders(server):
    success, payload = _call_emby_api(server, "Library/VirtualFolders/Query")
    if not success:
        return [], payload
    if isinstance(payload, dict):
        items = payload.get("Items") or payload.get("items") or []
    else:
        items = payload if isinstance(payload, list) else []
    if not isinstance(items, list):
        return [], "Risposta VirtualFolders inattesa"
    return items, None


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
    success, payload = _call_emby_api(server, "Library/VirtualFolders/Query")
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

        # Include RefreshStatus and RefreshProgress as per Gemini's implementation
        libraries.append({
            "id": entry.get("Id") or entry.get("ItemId"),
            "name": entry.get("Name"),
            "collection_type": collection_type,
            "refresh_status": entry.get("RefreshStatus"),      # Will be None if not present
            "refresh_progress": entry.get("RefreshProgress")   # Will be None if not present
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
        play_method_label = str(play_method).lower()
        video_direct = transcoding.get("IsVideoDirect")
        audio_direct = transcoding.get("IsAudioDirect")
        if play_method_label in ("directplay", "directstream"):
            video_direct = True
            audio_direct = True
        elif play_method_label == "transcode":
            if video_direct is None:
                video_direct = False
            if audio_direct is None:
                audio_direct = False
        elif video_direct is None and audio_direct is None:
            is_transcoding = bool(transcoding)
            video_direct = not is_transcoding
            audio_direct = not is_transcoding
        else:
            if video_direct is None:
                video_direct = not bool(transcoding)
            if audio_direct is None:
                audio_direct = not bool(transcoding)
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


def _trigger_library_scan(server: Dict[str, Any], library_id: str, scan_type: str = "content"):
    """
    Trigger a library operation on a single library.

    scan_type:
    - "content": Scans filesystem for new/changed files
    - "metadata": Refreshes metadata for existing items without scanning filesystem

    Both use POST /Items/{Id}/Refresh but with different parameters:
    - File scan: Recursive=true only
    - Metadata refresh: Recursive=true + MetadataRefreshMode + other metadata params
    """
    if not library_id:
        return False, "ID libreria mancante"

    if scan_type == "metadata":
        # Metadata refresh only - refreshes metadata without scanning filesystem
        # Uses EXACT same parameters as Emby Web UI for metadata refresh
        # Verified from actual Emby Web UI network capture
        params = {
            "Recursive": "true",
            "ImageRefreshMode": "FullRefresh",
            "MetadataRefreshMode": "FullRefresh",
            "ReplaceAllImages": "true",
            "ReplaceThumbnailImages": "true",
            "ReplaceAllMetadata": "true"
        }
    else:
        # Content scan - scans filesystem for new/changed files
        # Uses Items endpoint with Recursive parameter only
        params = {"Recursive": "true"}

    # Debug log to file
    endpoint = f"Items/{library_id}/Refresh"
    import os
    log_file = os.path.join(os.path.dirname(__file__), "debug_scan.log")

    # Construct full URL for logging
    base_url = _emby_base_url(server)
    test_params = dict(params or {})
    test_params["api_key"] = "***"
    from urllib.parse import urlencode
    full_url = f"{base_url}/{endpoint}?{urlencode(test_params)}"

    try:
        with open(log_file, "a") as f:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] TRIGGER_SCAN: scan_type={scan_type}, library_id={library_id}\n")
            f.write(f"[{timestamp}] URL: {full_url}\n")
            f.write(f"[{timestamp}] PARAMS: {params}\n")
            f.flush()
    except:
        pass

    result = _call_emby_api(server, endpoint, method="POST", params=params)

    try:
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] RESULT: success={result[0]}\n")
            f.flush()
    except:
        pass

    return result


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
        print(f"[PREPARE VIEW] Server {server.get('id', 'unknown')[:6]}: icon={server.get('icon')}, icon_color={server.get('icon_color')}")
        if lazy:
            decorated["status"] = {
                "ok": None,
                "version": None,
                "name": decorated.get("alias") or decorated.get("original_name") or decorated.get("name") or "Server Emby",
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
    link = link.strip()
    is_magnet = link.startswith("magnet:?")
    is_url = link.startswith("http://") or link.startswith("https://")

    if not (is_magnet or is_url):
        return False, f"Link non valido: deve essere un magnet link o URL HTTP(S). Ricevuto: {link[:50]}..."

    print(f"   -> [QB] Invio torrent a qBittorrent: {link[:80]}...")

    session = requests.Session()
    base_url = qb_url.rstrip('/')

    for attempt in range(max_retries + 1):
        try:
            # Login a qBittorrent
            print(f"   -> [QB] Login qBittorrent (tentativo {attempt + 1}/{max_retries + 1})...")
            login_resp = session.post(
                f"{base_url}/api/v2/auth/login",
                data={"username": qb_user, "password": qb_pass},
                timeout=15  # Aumentato da 10 a 15 secondi
            )

            if login_resp.status_code != 200:
                error_msg = f"Login fallito: HTTP {login_resp.status_code}"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg

            login_text = login_resp.text.strip()
            if login_text != "Ok.":
                error_msg = f"Login fallito: risposta inattesa '{login_text}'"
                if attempt < max_retries:
                    print(f"   -> [QB] {error_msg}, ritento...")
                    time.sleep(1)
                    continue
                return False, error_msg

            print(f"   -> [QB] Login OK, invio torrent...")

            # Aggiunta torrent
            add_resp = session.post(
                f"{base_url}/api/v2/torrents/add",
                data={"urls": link},
                timeout=20  # Aumentato da 10 a 20 secondi per torrent grandi
            )

            add_text = add_resp.text.strip()

            # FIX CRITICO: Parentesi corrette per la condizione logica
            if add_resp.status_code == 200 and (add_text == "Ok." or add_text == ""):
                print(f"   -> [QB] ✓ Torrent aggiunto con successo!")
                return True, "Torrent aggiunto con successo."

            # Errore nell'aggiunta
            error_msg = f"Errore aggiunta (HTTP {add_resp.status_code}): {add_text}"

            # Retry solo per errori server (5xx) o timeout
            if add_resp.status_code >= 500 and attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento...")
                time.sleep(2)
                continue

            print(f"   -> [QB] ✗ {error_msg}")
            return False, error_msg

        except requests.exceptions.Timeout as exc:
            error_msg = f"Timeout connessione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento... (tentativo {attempt + 1}/{max_retries + 1})")
                time.sleep(1)
                continue
            print(f"   -> [QB] ✗ {error_msg} dopo {max_retries + 1} tentativi")
            return False, f"{error_msg}: {exc}"

        except requests.exceptions.ConnectionError as exc:
            error_msg = f"Impossibile connettersi a qBittorrent ({qb_url})"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg}, ritento...")
                time.sleep(2)
                continue
            print(f"   -> [QB] ✗ {error_msg}")
            return False, f"{error_msg}: {exc}"

        except requests.exceptions.RequestException as exc:
            error_msg = f"Errore comunicazione qBittorrent"
            if attempt < max_retries:
                print(f"   -> [QB] {error_msg} ({type(exc).__name__}), ritento...")
                time.sleep(1)
                continue
            print(f"   -> [QB] ✗ {error_msg}: {type(exc).__name__} - {exc}")
            return False, f"{error_msg}: {exc}"

    return False, f"Fallito dopo {max_retries + 1} tentativi"


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
    url = f"{config['JELLYSEERR_URL']}/api/v1/request/{request_id}"

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=15  # Aumentato timeout da 10 a 15 secondi
            )
            response.raise_for_status()
            data = response.json()
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
                print(f"   -> [ERRORE] Timeout definitivo per richiesta {request_id} dopo {max_retries + 1} tentativi: {exc}")
                return None

        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else "unknown"
            print(f"   -> [ERRORE] HTTP {status_code} recuperando dettagli richiesta {request_id}: {exc}")
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
            print(f"   -> [ERRORE] Impossibile ottenere dettagli per la richiesta {request_id}: {type(exc).__name__} - {exc}")
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
        url = f"{config['JELLYSEERR_URL']}/api/v1/search"
        response = requests.get(url, headers=headers, params={"query": query}, timeout=10)
        response.raise_for_status()
        data = response.json()
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
            f"{config['JELLYSEERR_URL']}/api/v1/request",
            headers=headers,
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return True, "Richiesta inviata", data
    except requests.exceptions.RequestException as exc:
        return False, f"Errore Jellyseerr: {exc}", None


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


def search_tmdb(api_key: str, query: str, language: str = "it-IT", page: int = 1) -> tuple:
    """
    Search TMDB for movies and TV shows with pagination support.

    Args:
        api_key: TMDB API key
        query: Search query
        language: Language code (e.g., 'it-IT', 'en-US')
        page: Page number (1-indexed)

    Returns:
        Tuple of (results_list, total_pages)
    """
    if not api_key or not query:
        return [], 0

    try:
        # TMDB multi search endpoint
        url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": api_key,
            "query": query,
            "language": language,
            "include_adult": "false",
            "page": page
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            print(f"   -> TMDB API error: {response.status_code}")
            return [], 0

        data = response.json()
        results = data.get("results", [])
        total_pages = data.get("total_pages", 0)

        normalized = []
        for item in results:
            media_type = item.get("media_type")

            # Only include movies and TV shows
            if media_type not in ["movie", "tv"]:
                continue

            # Get title (different field for movies vs TV)
            title = item.get("title") if media_type == "movie" else item.get("name")

            # Get year from release_date or first_air_date
            date_field = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
            year = None
            if date_field:
                try:
                    year = int(date_field.split("-")[0])
                except (ValueError, IndexError):
                    pass

            normalized.append({
                "title": title,
                "media_type": media_type,
                "tmdb_id": item.get("id"),
                "year": year,
                "overview": item.get("overview", ""),
                "poster_path": item.get("poster_path"),
                "original_title": item.get("original_title") if media_type == "movie" else item.get("original_name")
            })

        return normalized, total_pages

    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare TMDB: {exc}")
        return [], 0


def get_tmdb_tv_details(api_key: str, tv_id: int, language: str = "it-IT") -> dict:
    """
    Get TV show details from TMDB including seasons.

    Args:
        api_key: TMDB API key
        tv_id: TMDB TV show ID
        language: Language code (e.g., 'it-IT', 'en-US')

    Returns:
        Dictionary with TV show details including seasons list
    """
    if not api_key or not tv_id:
        return {}

    try:
        url = f"https://api.themoviedb.org/3/tv/{tv_id}"
        params = {
            "api_key": api_key,
            "language": language
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            print(f"   -> TMDB API error: {response.status_code}")
            return {}

        data = response.json()

        # Extract season information
        seasons = []
        for season in data.get("seasons", []):
            season_num = season.get("season_number")
            # Skip season 0 (specials) if desired, or include it
            if season_num is not None:
                seasons.append({
                    "season_number": season_num,
                    "name": season.get("name", f"Season {season_num}"),
                    "episode_count": season.get("episode_count", 0),
                    "air_date": season.get("air_date")
                })

        return {
            "tmdb_id": data.get("id"),
            "name": data.get("name"),
            "seasons": seasons,
            "number_of_seasons": data.get("number_of_seasons", 0),
            "poster_path": data.get("poster_path")
        }

    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare TMDB: {exc}")
        return {}


def check_emby_availability(
    emby_servers: list,
    provider_id: Any,
    media_type: Optional[str] = None,
    provider_key: str = "Tmdb"
) -> list:
    """
    Check if content is available on any Emby server using a provider ID.

    Args:
        emby_servers: List of Emby server configurations
        provider_id: Provider identifier (TMDB, IMDb, etc.)
        media_type: Optional media type ("movie" or "tv") to refine search
        provider_key: Provider key used in Emby (e.g., "Tmdb" or "Imdb")

    Returns:
        List of server info dicts where content is found, with keys:
        - server_id: Server ID
        - server_name: Server name
        - server_icon: Server icon (Font Awesome class)
        - server_icon_color: Server icon color
        - server_icon_style: Server icon style (solid/regular)
        - item_id: Emby item ID
        - item_name: Item name
    """
    if not emby_servers or not provider_id:
        return []

    found_servers = []
    provider_id_key = provider_key
    normalized_type = _normalize_media_type(media_type)
    include_types = None
    if normalized_type == "tv":
        include_types = "Series"
    elif normalized_type == "movie":
        include_types = "Movie"

    for server in emby_servers:
        try:
            url = server.get("url", "").rstrip("/")
            api_key = server.get("api_key", "")
            server_name = server.get("name", "Emby Server")
            server_id = server.get("id", "")
            server_icon = server.get("icon") or "fa-server"
            server_icon_color = server.get("icon_color") or "#3b82f6"
            server_icon_style = server.get("icon_style") or "solid"

            if not url or not api_key:
                continue

            # Search by provider ID (TMDB)
            search_url = f"{url}/Items"
            params = {
                "AnyProviderIdEquals": f"{provider_id_key}.{provider_id}",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "api_key": api_key
            }
            if include_types:
                params["IncludeItemTypes"] = include_types

            response = requests.get(search_url, params=params, timeout=5)

            if response.status_code != 200:
                continue

            data = response.json()
            items = data.get("Items", [])

            if items:
                # Content found on this server
                item = items[0]  # Take first match
                found_servers.append({
                    "server_id": server_id,
                    "server_name": server_name,
                    "server_icon": server_icon,
                    "server_icon_color": server_icon_color,
                    "server_icon_style": server_icon_style,
                    "item_id": item.get("Id"),
                    "item_name": item.get("Name", "")
                })

        except requests.exceptions.RequestException:
            # Skip servers that fail
            continue
        except Exception:
            # Skip any other errors
            continue

    return found_servers


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


# --- FUNZIONI GESTIONE UTENTI EMBY ---

def _fetch_emby_users_list(server):
    """
    Recupera la lista di tutti gli utenti dal server Emby.
    """
    success, payload = _call_emby_api(server, "Users")
    if not success:
        return [], payload
    # Emby restituisce una lista diretta di oggetti User
    if isinstance(payload, list):
        return payload, None
    return [], "Formato risposta inatteso"


def _fetch_emby_user_details(server, user_id):
    """
    Recupera i dettagli completi di un utente, incluse Policy e Configuration.
    """
    if not user_id:
        return None, "User ID mancante"
    success, payload = _call_emby_api(server, f"Users/{user_id}")
    if success:
        return payload, None
    return None, payload


def _update_emby_user_policy(server, user_id, policy):
    """
    Aggiorna la policy di un utente (es. permessi, accessi).
    """
    if not user_id or not isinstance(policy, dict):
        return False, "Dati non validi"
    
    # Emby richiede una POST su /Users/{Id}/Policy
    success, payload = _call_emby_api(
        server, 
        f"Users/{user_id}/Policy", 
        method="POST", 
        json_payload=policy
    )
    return success, payload


def _update_emby_user_configuration(server, user_id, configuration):
    """
    Aggiorna la configurazione utente (es. preferenze UI, lingua).
    """
    if not user_id or not isinstance(configuration, dict):
        return False, "Dati non validi"
        
    # Emby richiede una POST su /Users/{Id}/Configuration
    success, payload = _call_emby_api(
        server, 
        f"Users/{user_id}/Configuration", 
        method="POST", 
        json_payload=configuration
    )
    return success, payload


def _rename_emby_user(server, user_id, new_name):
    """
    Rinomina un utente sul server Emby.
    """
    if not user_id or not new_name:
        return False, "Dati mancanti"
    
    # 1. Fetch current user details
    user_dto, err = _fetch_emby_user_details(server, user_id)
    if err or not user_dto:
        return False, f"Impossibile recuperare utente: {err}"
    
    # 2. Update Name
    user_dto["Name"] = new_name
    
    # CRITICAL: Remove Password fields to prevent accidental reset!
    # Emby API /Users/{Id} POST update might clear password if these are present but empty/null.
    # We strip them to be safe.
    keys_to_remove = ["Password", "OriginalPassword", "EasyPassword", "Salt", "PasswordSalt", "ConnectPassword"]
    for k in keys_to_remove:
        user_dto.pop(k, None)
    
    # 3. Post update
    # Endpoint: /Users/{Id}
    success, payload = _call_emby_api(
        server, 
        f"Users/{user_id}", 
        method="POST", 
        json_payload=user_dto
    )
    return success, payload


def _update_emby_user_password(server, user_id, new_password):
    """
    Aggiorna la password dell'utente.
    Richiede privilegi amministrativi (API Key) per ignorare la password corrente.
    """
    if not user_id:
        return False, "User ID mancante"
    
    # Endpoint: /Users/{Id}/Password
    payload = {
        "Id": user_id,
        "NewPw": new_password
        # "CurrentPassword": "" # Admin can typically omit this
    }
    
    success, resp = _call_emby_api(
        server, 
        f"Users/{user_id}/Password", 
        method="POST", 
        json_payload=payload
    )
    return success, resp


def _fetch_emby_user_last_playback(server, user_id):
    """
    Recupera l'ultimo elemento riprodotto dall'utente.
    """
    if not user_id:
        return None
        
    params = {
        "Recursive": "true",
        "Limit": 1,
        "SortBy": "DatePlayed",
        "SortOrder": "Descending",
        "Filters": "IsPlayed",
        "IncludeItemTypes": "Movie,Episode",
        "Fields": "DatePlayed,Name,SeriesName"
    }
    
    success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
    if not success or not isinstance(payload, dict):
        return None
        
    items = payload.get("Items", [])
    if items:
        return items[0]
    return None


def _create_emby_user(server, name, copy_from_user_id=None):
    """
    Creates a new user on the Emby server.
    """
    params = {"Name": name}
    if copy_from_user_id:
        params["CopyFromUserId"] = copy_from_user_id
    
    success, payload = _call_emby_api(
        server, 
        "Users/New", 
        method="POST", 
        json_payload=params
    )
    return success, payload


def _fetch_emby_user_items_for_sync(server, user_id):
    """
    Scarica tutti gli elementi (Film/Episodi) visti o in corso per l'utente,
    con ProviderIds per il matching.
    """
    if not user_id:
        return [], "User ID mancante"

    # Filtriamo per Items ricorsivi, solo Video (Movie, Episode),
    # richiediamo ProviderIds e UserData.
    # Utile filtrare anche "IsPlayed=true" o "IsResumable=true" per ridurre il carico,
    # ma se vogliamo sincronizzare tutto lo storico (anche play count > 0), meglio prendere tutto
    # ciò che ha UserData != null. Emby non ha un filtro "HasUserData", ma possiamo usare
    # "Recursive=true" e poi filtrare lato client, oppure filtrare per "IsPlayed=true,IsResumable=true"
    # in due chiamate o OR se supportato. 
    # Per semplicità di sync (copiare esattamente lo stato), prendiamo tutto ciò che è Played o ha resume.
    
    params = {
        "Recursive": "true",
        "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
        "IncludeItemTypes": "Movie,Episode",
        "IsPlayed": "true" 
    }
    
    # 1. Recupera elementi visti
    success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
    if not success:
        return [], payload
        
    items = payload.get("Items", []) if isinstance(payload, dict) else []
    
    # 2. Recupera elementi parzialmente visti (Resumable) se non già inclusi
    # Nota: IsPlayed=true include spesso anche quelli parziali se PlayCount > 0, 
    # ma controlliamo esplicitamente i Resumable.
    params_resume = {
        "Recursive": "true",
        "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
        "IncludeItemTypes": "Movie,Episode",
        "IsResumable": "true"
    }
    
    success_res, payload_res = _call_emby_api(server, f"Users/{user_id}/Items", params=params_resume)
    if success_res:
        items_res = payload_res.get("Items", []) if isinstance(payload_res, dict) else []
        # Merge by Id to avoid duplicates
        seen_ids = set(i["Id"] for i in items)
        for it in items_res:
            if it["Id"] not in seen_ids:
                items.append(it)
                
    return items, None


def _mark_emby_item_played(server, user_id, item_id, date_played=None):
    """
    Segna un elemento come visto (Played).
    """
    if not user_id or not item_id:
        return False, "ID mancanti"
    
    params = {}
    if date_played:
        params["DatePlayed"] = date_played
        
    success, payload = _call_emby_api(
        server, 
        f"Users/{user_id}/PlayedItems/{item_id}", 
        method="POST",
        json_payload=params
    )
    return success, payload


def _mark_emby_item_unplayed(server, user_id, item_id):
    """
    Rimuove lo stato 'visto' da un elemento.
    """
    if not user_id or not item_id:
        return False, "ID mancanti"
        
    success, payload = _call_emby_api(
        server, 
        f"Users/{user_id}/PlayedItems/{item_id}", 
        method="DELETE"
    )
    return success, payload
