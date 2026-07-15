# emby_runtime/api_clients.py

from emby_runtime.api_clients_emby import (
    EMBY_REQUEST_TIMEOUT,
    _emby_has_credentials,
    _emby_base_url,
    _call_emby_api,
    _fetch_emby_scheduled_tasks,
    _fetch_emby_virtual_folders,
    _fetch_emby_status,
    _fetch_emby_libraries,
    _format_ticks,
    _fetch_emby_active_sessions,
    _trigger_library_scan,
    _stop_emby_task,
    _run_emby_scheduled_task,
    check_emby_availability,
)
from emby_runtime.api_clients_jellyseerr import (
    get_jellyseerr_requests,
    fetch_request_details,
    fetch_media_info,
    search_jellyseerr,
    submit_jellyseerr_request,
    check_jellyseerr_availability,
)
from emby_runtime.api_clients_qbittorrent import (
    send_to_qbittorrent,
    send_to_qbittorrent_batch,
)
from emby_runtime.api_clients_ping import (
    _ping_api_service,
    _ping_jellyseerr,
    _ping_prowlarr,
    _ping_qbittorrent,
)
from emby_runtime.api_clients_tmdb import (
    _try_parse_int,
    _extract_tmdb_id,
    _fetch_tmdb_payload,
    search_tmdb,
    get_tmdb_tv_details,
)
from emby_runtime.api_clients_indexers import (
    search_prowlarr,
    search_jackett,
)

print("[API_CLIENTS] Module loaded - VERSION 2026-01-08-21:40 with metadata fix")

__all__ = [
    "_emby_has_credentials",
    "_emby_base_url",
    "_call_emby_api",
    "EMBY_REQUEST_TIMEOUT",
    "_fetch_emby_scheduled_tasks",
    "_fetch_emby_virtual_folders",
    "_fetch_emby_status",
    "_fetch_emby_libraries",
    "_format_ticks",
    "_fetch_emby_active_sessions",
    "_trigger_library_scan",
    "_stop_emby_task",
    "_run_emby_scheduled_task",
    "get_jellyseerr_requests",
    "send_to_qbittorrent",
    "send_to_qbittorrent_batch",
    "_ping_api_service",
    "_ping_jellyseerr",
    "_ping_prowlarr",
    "_ping_qbittorrent",
    "_try_parse_int",
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
]
