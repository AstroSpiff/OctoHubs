import logging
from typing import Any, Dict, Tuple, Optional, Callable

from emby_runtime.api_clients import _fetch_emby_libraries
from emby_libraries.grouping import group_libraries
from core.log_sanitization import format_exception_for_log
from core.utils import get_emby_servers

logger = logging.getLogger(__name__)


class EmbyLibrariesManager:
    def __init__(
        self,
        load_config: Callable[[], Tuple[Optional[Dict[str, Any]], bool]],
        ensure_db_backend: Callable[[], Any],
        json_error: Callable[[str, int], Tuple[Dict[str, Any], int]],
        storage_error_cls: Any
    ):
        self._load_config = load_config
        self._ensure_db_backend = ensure_db_backend
        self._json_error = json_error
        self._storage_error_cls = storage_error_cls

    def _storage_error(self, context: str, exc: BaseException):
        logger.error("%s:\n%s", context, format_exception_for_log(exc))
        return self._json_error("Dati librerie temporaneamente non disponibili", 500)

    def build_grouped_libraries_snapshot(self):
        config, is_valid = self._load_config()
        if not is_valid or not config:
            return self._json_error("Config non valida", 400)
        servers = get_emby_servers(config)
        all_libraries: Dict[str, Any] = {}
        for server in servers:
            if not server.get("enabled"):
                continue
            server_id = server.get("id")
            server_icon = server.get("icon") or "fa-server"
            server_icon_style = server.get("icon_style") or "solid"
            server_icon_color = server.get("icon_color") or "#3b82f6"
            libraries, error = _fetch_emby_libraries(server)
            all_libraries[server_id] = {
                "ok": error is None,
                "libraries": libraries,
                "error": error,
                "name": server.get("name"),
                "alias": server.get("alias"),
                "original_name": server.get("original_name"),
                "icon": server_icon,
                "icon_style": server_icon_style,
                "icon_color": server_icon_color
            }
        try:
            backend = self._ensure_db_backend()
            associations = backend.load_library_associations()
            order_map = backend.load_library_group_order()
        except self._storage_error_cls as exc:
            return self._storage_error("Caricamento librerie non riuscito", exc)
        grouped = group_libraries(all_libraries, associations)
        def _group_key(entry):
            ctype = entry.get("collection_type") or ""
            gname = entry.get("group_name") or ""
            pos = order_map.get((ctype, gname))
            if pos is None:
                pos = order_map.get(("", gname)) or order_map.get((None, gname))
            return (pos is None, pos or 0, gname)
        grouped.sort(key=_group_key)
        return {"success": True, "groups": grouped}, 200

    def build_associations_get_snapshot(self):
        try:
            backend = self._ensure_db_backend()
            associations = backend.load_library_associations()
        except self._storage_error_cls as exc:
            return self._storage_error("Caricamento associazioni non riuscito", exc)
        payload = [
            {
                "server_id": server_id,
                "library_id": library_id,
                "group_name": group_name
            }
            for (server_id, library_id), group_name in associations.items()
        ]
        return {"success": True, "associations": payload}, 200

    def build_associations_post_snapshot(self, payload):
        if not isinstance(payload, list):
            return self._json_error("Formato non valido", 400)
        associations = {}
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            server_id = entry.get("server_id")
            library_id = entry.get("library_id")
            group_name = entry.get("group_name")
            if not (server_id and library_id and group_name):
                continue
            associations[(str(server_id), str(library_id))] = str(group_name)
        try:
            backend = self._ensure_db_backend()
            backend.save_library_associations(associations)
        except ValueError as exc:
            return self._json_error(str(exc), 400)
        except self._storage_error_cls as exc:
            return self._storage_error("Salvataggio associazioni non riuscito", exc)
        payload = [
            {
                "server_id": server_id,
                "library_id": library_id,
                "group_name": group_name
            }
            for (server_id, library_id), group_name in associations.items()
        ]
        return {"success": True, "associations": payload}, 200
