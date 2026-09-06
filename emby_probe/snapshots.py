"""Snapshot builders for Emby probe workflows."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, cast

from core.config import _coerce_request_int
from core.config_manager import _ensure_db_backend, load_config
from core.log_sanitization import format_exception_for_log
from core.storage import StorageError
from core.utils import get_emby_servers, get_nested, json_error
from emby_probe import get_probe_manager, _format_display_name_from_queue


logger = logging.getLogger(__name__)

PROBE_PAGE_DEFAULT = 200
PROBE_PAGE_MAX = 500


def _probe_page_window(
    limit: Any,
    offset: Any,
    *,
    default_limit: int = PROBE_PAGE_DEFAULT,
):
    try:
        parsed_limit = int(default_limit if limit in (None, "") else limit)
        parsed_offset = int(0 if offset in (None, "") else offset)
    except (TypeError, ValueError):
        return None, json_error("limit e offset devono essere numeri interi", 422)
    if not 1 <= parsed_limit <= PROBE_PAGE_MAX:
        return None, json_error(
            f"limit deve essere compreso tra 1 e {PROBE_PAGE_MAX}", 422
        )
    if parsed_offset < 0:
        return None, json_error("offset non può essere negativo", 422)
    return (parsed_limit, parsed_offset), None


def _probe_page_payload(items: list[Dict[str, Any]], limit: int, offset: int):
    has_more = len(items) > limit
    visible = items[:limit]
    return visible, has_more, offset + len(visible) if has_more else None


def _probe_cursor_id(value: Any):
    if value is None:
        return None, None
    try:
        cursor_id = int(value)
    except (TypeError, ValueError):
        return None, json_error("cursor deve essere un numero intero", 422)
    if cursor_id < 0:
        return None, json_error("cursor non può essere negativo", 422)
    return cursor_id, None


def _probe_next_cursor(items: list[Dict[str, Any]], has_more: bool):
    if not has_more or not items:
        return None
    value = items[-1].get("id")
    return int(value) if isinstance(value, int) else None


def _probe_internal_error(context: str, exc: BaseException):
    logger.error("%s:\n%s", context, format_exception_for_log(exc))
    return json_error("Operazione Probe non disponibile", 500)

def _probe_load_config_servers():
    config, is_valid = load_config()
    if not is_valid or not config:
        return None, None, ({"success": False, "message": "Config non valida"}, 400)
    servers = get_emby_servers(config)
    return config, servers, None


def _probe_select_server(servers, server_id):
    target_server = None
    for server in servers:
        if server.get("id") == server_id:
            target_server = server
            break
    if target_server is None:
        return None, ({"success": False, "message": "Server non trovato"}, 404)
    if not target_server.get("enabled"):
        return None, ({"success": False, "message": "Server disabilitato"}, 400)
    return target_server, None


_PROBE_CONFIG_DEFAULTS = {
    "window_size": 500,
    "window_threshold": 0.90,
    "max_days": 60,
    "max_items": 2000,
    "safety_margin_days": 7,
    "probe_parallelism": 1,
    "media_policy": "strm_only",
}


def _parse_recent_window_threshold(value: Any, default: float) -> float:
    if value is None:
        return default
    text = str(value).strip().replace("%", "")
    if not text:
        return default
    try:
        threshold = float(text)
    except ValueError:
        return default
    if threshold > 1:
        threshold = threshold / 100.0
    threshold = max(0.5, min(1.0, threshold))
    return threshold


def _normalize_probe_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    defaults = _PROBE_CONFIG_DEFAULTS
    return {
        "window_size": _coerce_request_int(payload.get("window_size"), defaults["window_size"], 100, 2000),
        "window_threshold": _parse_recent_window_threshold(payload.get("window_threshold"), defaults["window_threshold"]),
        "max_days": _coerce_request_int(payload.get("max_days"), defaults["max_days"], 7, 365),
        "max_items": _coerce_request_int(payload.get("max_items"), defaults["max_items"], 500, 10000),
        "safety_margin_days": _coerce_request_int(payload.get("safety_margin_days"), defaults["safety_margin_days"], 1, 30),
        "probe_parallelism": _coerce_request_int(payload.get("probe_parallelism"), defaults["probe_parallelism"], 1, 8),
        "media_policy": (
            "missing_media_info"
            if str(payload.get("media_policy") or "").strip().lower() == "missing_media_info"
            else "strm_only"
        ),
    }


def _probe_config_get_snapshot(server_id: Optional[str]):
    if not server_id:
        return json_error("server_id mancante")
    if server_id == "all":
        return json_error("server_id non valido")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    _, error = _probe_select_server(servers, server_id)
    if error:
        return error
    try:
        backend = _ensure_db_backend()
        config = backend.get_probe_config(server_id)
    except StorageError as exc:
        return _probe_internal_error("Lettura configurazione Probe non riuscita", exc)
    normalized = _normalize_probe_config(config or {})
    return {"success": True, "config": normalized}, 200


def _save_probe_configuration(backend: Any, server_id: str, config: Dict[str, Any]) -> bool:
    save_if_owned = getattr(backend, "save_probe_config_if_server_exists", None)
    if callable(save_if_owned):
        return bool(save_if_owned(server_id, config))
    backend.save_probe_config(server_id, config)
    return True


def _probe_config_save_snapshot(payload: Dict[str, Any]):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    if server_id == "all":
        return json_error("server_id non valido")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    _, error = _probe_select_server(servers, server_id)
    if error:
        return error
    raw_config = payload.get("config")
    if raw_config is None:
        raw_config = payload
    if not isinstance(raw_config, dict):
        return json_error("Config non valida")
    normalized = _normalize_probe_config(raw_config)
    try:
        backend = _ensure_db_backend()
        if not _save_probe_configuration(backend, server_id, normalized):
            return json_error("Server non trovato", 404)
    except StorageError as exc:
        return _probe_internal_error("Salvataggio configurazione Probe non riuscito", exc)
    return {"success": True, "config": normalized}, 200


def _probe_discovery_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    libraries = payload.get("libraries")
    started = get_probe_manager().start_discovery(target_server, server_id, target_libraries=libraries)
    if started:
        return {"success": True, "message": "Discovery avviato"}, 200
    return json_error("Discovery già in esecuzione")


def _probe_discovery_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    stopped = get_probe_manager().stop_discovery(server_id)
    if stopped:
        return {"success": True, "message": "Discovery arrestato"}, 200
    return json_error("Discovery non in esecuzione")


def _probe_recent_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    limit = _coerce_request_int(payload.get("limit"), 200, 1, 1000)
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_recent_discovery(target_server, server_id, limit)
    if started:
        return {"success": True, "message": "Discovery ultimi aggiunti avviata"}, 200
    return json_error("Discovery ultimi aggiunti già in esecuzione")


def _probe_recent_start_all_snapshot(payload):
    if payload is None:
        payload = {}
    if payload and not isinstance(payload, dict):
        return json_error("Formato non valido")
    limit = _coerce_request_int((payload or {}).get("limit"), 200, 1, 1000)
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [server for server in (servers or []) if server.get("enabled")]
    if not servers:
        return json_error("Nessun server Emby abilitato")
    server_ids = [server.get("id") for server in servers if server.get("id")]
    started = get_probe_manager().start_recent_discovery_sequence(servers, limit)
    if not started:
        return {
            "success": True,
            "message": f"Discovery ultimi aggiunti già in esecuzione su {len(server_ids)} server",
            "started": server_ids,
            "already_running": True
        }, 200
    return {
        "success": True,
        "message": f"Discovery ultimi aggiunti avviata in sequenza su {len(server_ids)} server",
        "started": server_ids
    }, 200


def _probe_recent_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    stopped = get_probe_manager().stop_recent_discovery(server_id)
    if stopped:
        return {"success": True, "message": "Discovery ultimi aggiunti arrestata"}, 200
    return json_error("Discovery ultimi aggiunti non in esecuzione")


def _probe_recent_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    get_probe_manager().stop_recent_discovery_sequence()
    stopped_ids = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        if get_probe_manager().stop_recent_discovery(server_id):
            stopped_ids.append(server_id)
    return {
        "success": True,
        "message": f"Discovery ultimi aggiunti arrestata su {len(stopped_ids)} server",
        "stopped": stopped_ids
    }, 200


def _probe_recent_processing_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return json_error("server_id mancante")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_recent_processing(target_server, server_id, mode)
    if started:
        return {"success": True, "message": f"Processing recenti avviato in modalità {mode}"}, 200
    return json_error("Processing recenti già in esecuzione")


def _probe_recent_processing_start_all_snapshot(payload):
    if payload is None:
        payload = {}
    if payload and not isinstance(payload, dict):
        return json_error("Formato non valido")
    mode = (payload or {}).get("mode", "smart")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [server for server in (servers or []) if server.get("enabled")]
    if not servers:
        return json_error("Nessun server Emby abilitato")
    started = get_probe_manager().start_recent_processing_sequence(servers, mode)
    if not started:
        return json_error("Processing recenti già in esecuzione")
    server_ids = [server.get("id") for server in servers if server.get("id")]
    return {
        "success": True,
        "message": f"Processing recenti avviato in sequenza su {len(server_ids)} server",
        "started": server_ids
    }, 200


def _probe_recent_processing_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    get_probe_manager().stop_combo_workflow(server_id, scope="recent")
    stopped = get_probe_manager().stop_recent_processing(server_id)
    if stopped:
        return {"success": True, "message": "Processing recenti arrestato"}, 200
    return json_error("Processing recenti non in esecuzione")


def _probe_recent_processing_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    get_probe_manager().stop_combo_workflow_all_servers(scope="recent")
    get_probe_manager().stop_recent_processing_sequence()
    stopped_ids = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        get_probe_manager().stop_combo_workflow(server_id, scope="recent")
        if get_probe_manager().stop_recent_processing(server_id):
            stopped_ids.append(server_id)
    return {
        "success": True,
        "message": f"Processing recenti arrestato su {len(stopped_ids)} server",
        "stopped": stopped_ids
    }, 200


def _probe_recent_combo_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return json_error("server_id mancante")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_combo_workflow(target_server, server_id, mode, scope="recent")
    if started:
        return {"success": True, "message": f"Combo workflow avviato in modalità {mode}"}, 200
    return json_error("Combo workflow già in esecuzione")


def _probe_recent_combo_start_all_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    mode = payload.get("mode", "smart")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    servers = [s for s in (servers or []) if s and s.get("enabled")]
    if not servers:
        return json_error("Nessun server abilitato")
    started = get_probe_manager().start_combo_workflow_all_servers(servers, mode, scope="recent")
    if started:
        server_ids = [server.get("id") for server in servers if server.get("id")]
        return {
            "success": True,
            "message": f"Combo workflow avviato su {len(server_ids)} server in modalità {mode}",
            "started": server_ids
        }, 200
    return json_error("Combo workflow già in esecuzione")


def _probe_recent_combo_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    stopped_combo = get_probe_manager().stop_combo_workflow(server_id, scope="recent")
    stopped_discovery = get_probe_manager().stop_recent_discovery(server_id)
    stopped_processing = get_probe_manager().stop_recent_processing(server_id)
    if stopped_combo or stopped_discovery or stopped_processing:
        return {"success": True, "message": "Workflow ultimi aggiunti arrestato"}, 200
    return json_error("Workflow non in esecuzione")


def _probe_recent_combo_stop_all_snapshot():
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    stopped_combo = get_probe_manager().stop_combo_workflow_all_servers(scope="recent")
    stopped_discovery_all = get_probe_manager().stop_recent_discovery_sequence()
    stopped_processing_all = get_probe_manager().stop_recent_processing_sequence()
    stopped_discovery = []
    stopped_processing = []
    for server in servers or []:
        server_id = server.get("id")
        if not server_id:
            continue
        if get_probe_manager().stop_recent_discovery(server_id):
            stopped_discovery.append(server_id)
        if get_probe_manager().stop_recent_processing(server_id):
            stopped_processing.append(server_id)
    if stopped_combo or stopped_discovery_all or stopped_processing_all or stopped_discovery or stopped_processing:
        return {
            "success": True,
            "message": "Workflow ultimi aggiunti arrestato su tutti i server",
            "stopped_discovery": stopped_discovery,
            "stopped_processing": stopped_processing
        }, 200
    return json_error("Workflow non in esecuzione")


def _probe_libraries_combo_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    libraries = payload.get("libraries")
    if not server_id:
        return json_error("server_id mancante")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    started = get_probe_manager().start_combo_workflow(
        target_server,
        server_id,
        mode,
        scope="libraries",
        target_libraries=libraries
    )
    if started:
        return {"success": True, "message": f"Combo workflow avviato in modalità {mode}"}, 200
    return json_error("Combo workflow già in esecuzione")


def _probe_libraries_combo_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    stopped_combo = get_probe_manager().stop_combo_workflow(server_id, scope="libraries")
    stopped_discovery = get_probe_manager().stop_discovery(server_id)
    stopped_processing = get_probe_manager().stop_processing(server_id)
    if stopped_combo or stopped_discovery or stopped_processing:
        return {"success": True, "message": "Combo workflow arrestato"}, 200
    return json_error("Combo workflow non in esecuzione")


def _probe_processing_start_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    mode = payload.get("mode", "smart")
    if not server_id:
        return json_error("server_id mancante")
    if mode not in ("smart", "forced"):
        return json_error("mode deve essere 'smart' o 'forced'")
    _, servers, error = _probe_load_config_servers()
    if error:
        return error
    target_server, error = _probe_select_server(servers, server_id)
    if error:
        return error
    target_server = cast(Dict[str, Any], target_server)
    libraries = payload.get("libraries")
    started = get_probe_manager().start_processing(target_server, server_id, mode, target_libraries=libraries)
    if started:
        return {"success": True, "message": f"Processing avviato in modalità {mode}"}, 200
    return json_error("Processing già in esecuzione")


def _probe_processing_stop_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    if not server_id:
        return json_error("server_id mancante")
    stopped = get_probe_manager().stop_processing(server_id)
    if stopped:
        return {"success": True, "message": "Processing arrestato"}, 200
    return json_error("Processing non in esecuzione")


def _probe_queue_get_snapshot(
    server_id: Optional[str],
    scope: str,
    limit: Any = PROBE_PAGE_DEFAULT,
    offset: Any = 0,
    cursor: Any = None,
):
    page, error = _probe_page_window(limit, offset)
    if error:
        return error
    assert page is not None
    page_limit, page_offset = page
    cursor_id, cursor_error = _probe_cursor_id(cursor)
    if cursor_error:
        return cursor_error
    try:
        backend = _ensure_db_backend()
        queue_kwargs = {
            "scope": scope,
            "limit": page_limit + 1,
            "offset": page_offset,
        }
        if cursor_id is not None:
            queue_kwargs["cursor_id"] = cursor_id
        queue = backend.get_probe_queue(server_id, **queue_kwargs)
        queue, has_more, next_offset = _probe_page_payload(
            queue, page_limit, page_offset
        )
        for item in queue:
            item["display_name"] = _format_display_name_from_queue(item)
        library_totals = {}
        if server_id and scope == "libraries":
            probe_status = get_probe_manager().get_status(server_id)
            library_totals = get_nested(probe_status, "discovery", "library_totals", default={})
    except StorageError as exc:
        return _probe_internal_error("Lettura coda Probe non riuscita", exc)
    return {
        "success": True,
        "queue": queue,
        "library_totals": library_totals,
        "has_more": has_more,
        "next_offset": next_offset if cursor_id is None else None,
        "next_cursor": _probe_next_cursor(queue, has_more) if cursor_id is not None else None,
    }, 200


def _probe_queue_delete_snapshot(server_id, item_id, media_source_id, scope):
    if not server_id:
        return json_error("server_id mancante")
    try:
        backend = _ensure_db_backend()
        if item_id:
            removed = backend.remove_from_probe_queue(
                server_id,
                item_id,
                media_source_id,
                scope=scope,
            )
            if removed is False:
                return json_error("Item in elaborazione: interrompi il worker prima di rimuoverlo", 409)
            return {"success": True, "message": "Item rimosso dalla coda"}, 200
        removed = backend.clear_probe_queue(server_id, scope=scope)
        return {
            "success": True,
            "message": "Righe disponibili rimosse; gli item in elaborazione sono stati preservati",
            "removed": int(removed or 0),
        }, 200
    except StorageError as exc:
        return _probe_internal_error("Lettura storico Probe non riuscita", exc)


def _probe_history_get_snapshot(
    server_id,
    limit: Any,
    scope: str,
    offset: Any = 0,
    cursor: Any = None,
):
    if not server_id:
        return json_error("server_id mancante")
    page, error = _probe_page_window(limit, offset, default_limit=100)
    if error:
        return error
    assert page is not None
    page_limit, page_offset = page
    cursor_id, cursor_error = _probe_cursor_id(cursor)
    if cursor_error:
        return cursor_error
    try:
        backend = _ensure_db_backend()
        history_kwargs = {"scope": scope, "offset": page_offset}
        if cursor_id is not None:
            history_kwargs["cursor_id"] = cursor_id
        history = backend.get_probe_history(
            server_id,
            page_limit + 1,
            **history_kwargs,
        )
        history, has_more, next_offset = _probe_page_payload(
            history, page_limit, page_offset
        )
    except StorageError as exc:
        return _probe_internal_error("Rimozione coda Probe non riuscita", exc)
    return {
        "success": True,
        "history": history,
        "has_more": has_more,
        "next_offset": next_offset if cursor_id is None else None,
        "next_cursor": _probe_next_cursor(history, has_more) if cursor_id is not None else None,
    }, 200


def _probe_history_delete_snapshot(server_id, scope: str):
    if not server_id:
        return json_error("server_id mancante")
    try:
        backend = _ensure_db_backend()
        backend.clear_probe_history(server_id, scope=scope)
        return {"success": True, "message": "Storico svuotato"}, 200
    except StorageError as exc:
        return _probe_internal_error("Pulizia coda Probe non riuscita", exc)


def _probe_retry_snapshot(payload):
    if not isinstance(payload, dict):
        return json_error("Formato non valido")
    server_id = payload.get("server_id")
    item_id = payload.get("item_id")
    media_source_id = payload.get("media_source_id")
    scope = payload.get("scope") or "libraries"
    if not server_id or not item_id:
        return json_error("server_id o item_id mancante")

    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")

    servers = get_emby_servers(config)
    target_server = next((s for s in servers if s.get("id") == server_id), None)
    if not target_server:
        return json_error(f"Server {server_id} non trovato", 404)

    success, message = get_probe_manager().retry_item(target_server, server_id, item_id, media_source_id, scope=scope)
    if success:
        return {"success": True, "message": message}, 200
    return json_error(message, 500)


def _probe_blacklist_get_snapshot(
    server_id,
    min_retry: str,
    error_type: Optional[str],
    scope: str,
    limit: Any = PROBE_PAGE_DEFAULT,
    offset: Any = 0,
    cursor: Any = None,
):
    if not server_id:
        return json_error("server_id mancante")
    try:
        min_retry_int = int(min_retry)
    except ValueError:
        min_retry_int = 3
    page, error = _probe_page_window(limit, offset)
    if error:
        return error
    assert page is not None
    page_limit, page_offset = page
    cursor_id, cursor_error = _probe_cursor_id(cursor)
    if cursor_error:
        return cursor_error
    try:
        backend = _ensure_db_backend()
        blacklist_kwargs = {
            "min_retry_count": min_retry_int,
            "error_type": error_type,
            "scope": scope,
            "limit": page_limit + 1,
            "offset": page_offset,
        }
        if cursor_id is not None:
            blacklist_kwargs["cursor_id"] = cursor_id
        blacklist = backend.get_probe_blacklist(server_id, **blacklist_kwargs)
        blacklist, has_more, next_offset = _probe_page_payload(
            blacklist, page_limit, page_offset
        )
    except StorageError as exc:
        return _probe_internal_error("Lettura blacklist Probe non riuscita", exc)
    return {
        "success": True,
        "blacklist": blacklist,
        "has_more": has_more,
        "next_offset": next_offset if cursor_id is None else None,
        "next_cursor": _probe_next_cursor(blacklist, has_more) if cursor_id is not None else None,
    }, 200


def _probe_blacklist_delete_snapshot(server_id, item_id, media_source_id, error_type, scope):
    if not server_id:
        return json_error("server_id mancante")
    try:
        backend = _ensure_db_backend()
        if item_id:
            backend.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
            return {"success": True, "message": "Item rimosso dalla blacklist"}, 200
        backend.clear_probe_blacklist(server_id, error_type=error_type, scope=scope)
        return {"success": True, "message": "Blacklist svuotata"}, 200
    except StorageError as exc:
        return _probe_internal_error("Aggiornamento blacklist Probe non riuscito", exc)


def _probe_debug_recent_items_snapshot(server_id: Optional[str], limit: int):
    if not server_id:
        return json_error("server_id richiesto")
    try:
        config, is_valid = load_config()
        if not is_valid or not config:
            return json_error("Config non valida")

        servers = get_emby_servers(config)
        server = None
        for entry in servers:
            if entry.get("id") == server_id:
                server = entry
                break
        if not server:
            return json_error(f"Server non trovato. ID ricevuto: {server_id}", 404)

        from emby_runtime.api_clients import _call_emby_api

        success, payload = _call_emby_api(
            server,
            "Items",
            method="GET",
            params={
                "IncludeItemTypes": "Movie,Episode",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": str(limit),
                "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,Type,DateCreated,Container,Name"
            }
        )
        if not success:
            return json_error(f"Errore API Emby: {payload}", 500)

        items = payload.get("Items", []) if isinstance(payload, dict) else []
        debug_info = []
        for item in items:
            item_path = item.get("Path", "")
            container = item.get("Container", "")
            is_strm = item_path.lower().endswith(".strm") or container.lower() == "strm"

            media_sources = item.get("MediaSources", [])
            has_metadata = False
            if media_sources:
                for source in media_sources:
                    if isinstance(source, dict):
                        if source.get("RunTimeTicks") and source.get("MediaStreams"):
                            has_metadata = True
                            break

            media_sources_debug = []
            for source in media_sources:
                if isinstance(source, dict):
                    media_sources_debug.append({
                        "Path": "[REDACTED]" if source.get("Path") else None,
                        "Container": source.get("Container"),
                        "RunTimeTicks": source.get("RunTimeTicks"),
                        "MediaStreams_count": len(source.get("MediaStreams", []))
                    })

            debug_info.append({
                "name": item.get("Name", "Unknown"),
                "series": item.get("SeriesName"),
                "season": item.get("ParentIndexNumber"),
                "episode": item.get("IndexNumber"),
                "date_created": item.get("DateCreated"),
                "path": "[REDACTED]" if item_path else "",
                "container": container,
                "is_strm": is_strm,
                "has_metadata": has_metadata,
                "media_sources_count": len(media_sources),
                "media_sources": media_sources_debug
            })

        return {
            "success": True,
            "server_id": server_id,
            "server_name": server.get("name"),
            "total_items": len(items),
            "items": debug_info
        }, 200
    except Exception as exc:
        return _probe_internal_error("Debug elementi recenti Probe non riuscito", exc)
