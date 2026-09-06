import logging

import requests
from datetime import datetime, timezone
from typing import Any, Tuple, Dict, cast, Optional

from core.emby_identifiers import quote_emby_identifier
from core.http_response_limits import close_response_safely, read_bounded_json_response
from core.outbound_redirects import response_is_redirect
from core.utils import _normalize_media_type

EMBY_REQUEST_TIMEOUT = 30
logger = logging.getLogger(__name__)


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
    merged_params = dict(params or {})
    headers = {
        "X-Emby-Token": token,
        "Accept": "application/json"
    }
    try:
        if method.upper() == "GET":
            response = requests.get(
                target,
                headers=headers,
                params=merged_params,
                allow_redirects=False,
                timeout=EMBY_REQUEST_TIMEOUT,
                stream=True,
            )
        else:
            response = requests.request(
                method.upper(),
                target,
                headers=headers,
                params=merged_params,
                json=json_payload,
                allow_redirects=False,
                timeout=EMBY_REQUEST_TIMEOUT,
                stream=True,
            )
        if response_is_redirect(response):
            close_response_safely(response)
            return False, "Redirect Emby rifiutato"
        try:
            payload = read_bounded_json_response(response)
        except requests.HTTPError as exc:
            failed_response = exc.response
            if failed_response is not None:
                return False, f"Errore Emby HTTP {failed_response.status_code}"
            return False, "Errore richiesta Emby"
        except requests.RequestException:
            return False, "Risposta Emby non valida"
        return True, payload
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None:
            return False, f"Errore Emby HTTP {response.status_code}"
        return False, "Errore richiesta Emby"
    except requests.RequestException:
        return False, "Errore richiesta Emby"


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
    def _normalize_collection_type(raw_type, default_if_missing=False):
        collection_type = raw_type
        if isinstance(collection_type, str):
            collection_type = collection_type.lower().strip()
        if not collection_type:
            return "folder" if default_if_missing else None
        if collection_type in ("mixed", "homevideos"):
            collection_type = "folder"
        if collection_type not in ("movies", "tvshows", "folder"):
            return None
        return collection_type

    def _normalize_name(value):
        if not isinstance(value, str):
            return ""
        return value.strip().lower()

    selectable_success, selectable_payload = _call_emby_api(server, "Library/SelectableMediaFolders")
    selectable_items = (
        selectable_payload if isinstance(selectable_payload, list)
        else (selectable_payload.get("Items") if isinstance(selectable_payload, dict) else [])
    )

    virtual_success, virtual_payload = _call_emby_api(server, "Library/VirtualFolders/Query")
    virtual_items = (
        virtual_payload if isinstance(virtual_payload, list)
        else (virtual_payload.get("Items") if isinstance(virtual_payload, dict) else [])
    )

    if not selectable_success and not virtual_success:
        return [], selectable_payload

    type_by_name = {}
    type_by_id = {}
    meta_by_name = {}
    if isinstance(virtual_items, list):
        for entry in virtual_items:
            if not isinstance(entry, dict):
                continue
            collection_type = _normalize_collection_type(entry.get("CollectionType"), default_if_missing=True)
            if not collection_type:
                continue
            name = entry.get("Name")
            name_key = _normalize_name(name)
            if name_key:
                type_by_name[name_key] = collection_type
                meta = meta_by_name.setdefault(name_key, {
                    "refresh_status": entry.get("RefreshStatus"),
                    "refresh_progress": entry.get("RefreshProgress"),
                    "view_ids": []
                })
                for key in ("Id", "ItemId", "LibraryId", "Guid"):
                    value = entry.get(key)
                    if value and str(value) not in meta["view_ids"]:
                        meta["view_ids"].append(str(value))
            for key in ("Id", "ItemId", "Guid"):
                value = entry.get(key)
                if value:
                    type_by_id[str(value)] = collection_type

    libraries = []
    source_items = selectable_items if isinstance(selectable_items, list) and selectable_items else virtual_items
    if not isinstance(source_items, list):
        return [], "Risposta librerie inattesa"

    for entry in source_items:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        lib_id = entry.get("Id") or entry.get("ItemId") or entry.get("LibraryId")
        if not lib_id:
            continue
        name_key = _normalize_name(name)
        collection_type = _normalize_collection_type(entry.get("CollectionType"), default_if_missing=False)
        if not collection_type:
            collection_type = type_by_id.get(str(lib_id))
        if not collection_type and entry.get("Guid"):
            collection_type = type_by_id.get(str(entry.get("Guid")))
        if not collection_type and name_key:
            collection_type = type_by_name.get(name_key)
        if not collection_type:
            collection_type = "folder"
        meta = meta_by_name.get(name_key, {})

        libraries.append({
            "id": lib_id,
            "folder_id": entry.get("Id"),
            "item_id": entry.get("ItemId") or entry.get("LibraryId"),
            "guid": entry.get("Guid"),
            "view_ids": meta.get("view_ids") or [],
            "name": name,
            "collection_type": collection_type,
            "refresh_status": meta.get("refresh_status"),
            "refresh_progress": meta.get("refresh_progress")
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
        video_width = None
        video_height = None
        video_codec = ""
        if video_stream:
            width = video_stream.get("Width")
            height = video_stream.get("Height")
            codec = video_stream.get("Codec") or ""
            video_width = width if isinstance(width, int) else None
            video_height = height if isinstance(height, int) else None
            video_codec = codec
            if width and height:
                video_label = f"{height}p {codec}".strip()
            else:
                video_label = f"{codec}".strip()
        audio_label = ""
        audio_codec = ""
        if audio_stream:
            audio_codec = audio_stream.get("Codec") or ""
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
            "play_session_id": (
                entry.get("PlaySessionId")
                or play_state.get("PlaySessionId")
                or transcoding.get("PlaySessionId")
                or ""
            ),
            "media_source_id": (
                now_playing.get("MediaSourceId")
                or play_state.get("MediaSourceId")
                or transcoding.get("MediaSourceId")
                or ""
            ),
            "audio_stream_index": play_state.get("AudioStreamIndex"),
            "subtitle_stream_index": play_state.get("SubtitleStreamIndex"),
            "playback_event_name": play_state.get("EventName") or entry.get("EventName") or "",
            "item_id": now_playing.get("Id") or "",
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
            "device_id": entry.get("DeviceId") or "",
            "client": client,
            "ip": remote_ip,
            "protocol": protocol,
            "app_version": app_version,
            "app_icon": app_icon,
            "state": state,
            "video_mode": video_mode,
            "audio_mode": audio_mode,
            "video_label": video_label,
            "video_width": video_width,
            "video_height": video_height,
            "video_codec": video_codec,
            "audio_label": audio_label,
            "audio_codec": audio_codec,
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
    quoted_library_id = quote_emby_identifier(library_id)
    if quoted_library_id is None:
        return False, "ID libreria non valido"

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

    endpoint = f"Items/{quoted_library_id}/Refresh"
    logger.debug(
        "Trigger Emby library scan: server=%s library=%s type=%s",
        server.get("id") or "configured-server",
        library_id,
        scan_type,
    )

    result = _call_emby_api(server, endpoint, method="POST", params=params)
    logger.debug(
        "Emby library scan trigger completed: server=%s library=%s success=%s",
        server.get("id") or "configured-server",
        library_id,
        result[0],
    )

    return result


def _stop_emby_task(server: Dict[str, Any], task_id: str):
    quoted_task_id = quote_emby_identifier(task_id)
    if quoted_task_id is None:
        return False, "ID task non valido"
    # Prova diversi endpoint e metodi
    attempts = [
        (f"ScheduledTasks/Running/{quoted_task_id}", "DELETE"),
        (f"ScheduledTasks/Running/{quoted_task_id}/Stop", "POST"),
        (f"ScheduledTasks/Running/{quoted_task_id}/Cancel", "POST"),
        (f"ScheduledTasks/{quoted_task_id}/Cancel", "POST"),
        (f"ScheduledTasks/Running/{quoted_task_id}", "POST")
    ]
    last_payload = "Operazione non supportata"
    server_id = server.get("id") or "configured-server"
    for attempt_number, (path, method) in enumerate(attempts, start=1):
        success, payload = _call_emby_api(server, path, method=method)
        logger.debug(
            "Emby task stop attempt: server=%s task=%s method=%s attempt=%d success=%s",
            server_id,
            task_id,
            method,
            attempt_number,
            success,
        )
        if success:
            return success, payload
        last_payload = payload
    return False, last_payload


def _send_emby_session_message(
    server: Dict[str, Any],
    session_id: str,
    header: str,
    text: str,
    timeout_ms: Optional[int] = 45000,
):
    if not session_id:
        return False, "ID sessione mancante"
    params = {
        "Header": header or "OctoHubs",
        "Text": text or "",
    }
    if timeout_ms is not None:
        params["TimeoutMs"] = max(1000, int(timeout_ms or 45000))
    return _call_emby_api(server, f"Sessions/{session_id}/Message", method="POST", params=params)


def _stop_emby_playback_session(server: Dict[str, Any], session_id: str):
    if not session_id:
        return False, "ID sessione mancante"
    return _call_emby_api(server, f"Sessions/{session_id}/Playing/Stop", method="POST")


def _pause_emby_playback_session(server: Dict[str, Any], session_id: str):
    if not session_id:
        return False, "ID sessione mancante"
    return _call_emby_api(server, f"Sessions/{session_id}/Playing/Pause", method="POST")


def _run_emby_scheduled_task(server, task_id):
    quoted_task_id = quote_emby_identifier(task_id)
    if quoted_task_id is None:
        return False, "ID task non valido"
    server_uuid = server.get("server_id") or server.get("status", {}).get("server_id")
    params = {}
    if server_uuid:
        params["serverId"] = server_uuid
    paths = [
        f"ScheduledTasks/{quoted_task_id}/Run",
        f"ScheduledTasks/{server_uuid}/{quoted_task_id}/Run" if server_uuid else "",
        f"ScheduledTasks/Run/{quoted_task_id}",
        f"ScheduledTasks/Run/{server_uuid}/{quoted_task_id}" if server_uuid else ""
    ]
    paths.extend([
        f"ScheduledTasks/Running/{quoted_task_id}",
        f"ScheduledTasks/Running/{server_uuid}/{quoted_task_id}" if server_uuid else ""
    ])
    for path in [p for p in paths if p]:
        success, payload = _call_emby_api(server, path, method="POST", params=params)
        if success:
            return True, payload
        if isinstance(payload, str) and any(code in payload for code in ("404", "405")):
            continue
        return success, payload
    return False, "Scheduled Task non disponibile"


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
            server_name = (server.get("alias") or "").strip()
            if not server_name:
                server_name = server.get("original_name") or server.get("name") or server.get("url") or "Emby Server"
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
            }
            if include_types:
                params["IncludeItemTypes"] = include_types

            response = requests.get(
                search_url,
                headers={"X-Emby-Token": api_key},
                params=params,
                allow_redirects=False,
                timeout=5,
                stream=True,
            )

            if response.status_code != 200:
                close_response_safely(response)
                continue

            data = read_bounded_json_response(response)
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
