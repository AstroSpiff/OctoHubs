# emby_runtime/settings_manager.py
import copy
from typing import Any, Callable, Dict

from core.config import _merge_emby_settings
from services.manager import _load_app_settings_snapshot, _save_app_settings_snapshot


_EVENT_BRIDGE_CREDENTIALS_SECTION = "EVENT_BRIDGE_CREDENTIALS"


def _load_emby_settings_from_db() -> Dict[str, Any]:
    settings = _load_app_settings_snapshot()
    return _merge_emby_settings(settings.get("EMBY"))


def _save_emby_settings_to_db(emby_settings: Dict[str, Any]) -> None:
    settings = _load_app_settings_snapshot()
    settings["EMBY"] = emby_settings
    _save_app_settings_snapshot(settings)


def _mutate_emby_settings_in_db(
    updater: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Transform EMBY against the row-locked current AppSettings document."""
    from core import config_manager

    def update(settings: Dict[str, Any]) -> Dict[str, Any]:
        current = _merge_emby_settings(settings.get("EMBY"))
        result = updater(copy.deepcopy(current))
        if not isinstance(result, dict):
            raise ValueError("Configurazione Emby non valida")
        settings["EMBY"] = copy.deepcopy(result)
        return settings

    persisted = config_manager._ensure_db_backend().mutate_app_settings(update)
    return _merge_emby_settings(persisted.get("EMBY"))


def _purge_emby_server_settings(server_id: str) -> None:
    if not server_id:
        return
    from emby_latest import settings as latest_settings_api

    latest_settings_api._prune_emby_latest_settings_for_server(server_id)


def _remove_emby_server_configuration(
    server_id: str,
    remaining_servers: list[dict[str, Any]],
) -> None:
    """Atomically remove server config, bridge overrides and its credential."""
    from core import config_manager as config_manager

    server_key = str(server_id or "").strip()

    def update(settings: Dict[str, Any]) -> Dict[str, Any]:
        emby = dict(settings.get("EMBY") or {})
        emby["SERVERS"] = remaining_servers
        settings["EMBY"] = emby

        bridge = dict(settings.get("EVENT_BRIDGE") or {})
        bridge_servers = dict(bridge.get("SERVERS") or {})
        bridge_servers.pop(server_key, None)
        bridge["SERVERS"] = bridge_servers
        settings["EVENT_BRIDGE"] = bridge

        credentials = dict(settings.get(_EVENT_BRIDGE_CREDENTIALS_SECTION) or {})
        credentials.pop(server_key, None)
        settings[_EVENT_BRIDGE_CREDENTIALS_SECTION] = credentials
        return settings

    config_manager._ensure_db_backend().mutate_app_settings(update)
