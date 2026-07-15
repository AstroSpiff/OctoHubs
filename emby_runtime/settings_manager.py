# emby_runtime/settings_manager.py
from typing import Any, Dict

from core.config import _merge_emby_settings
from services.manager import _load_app_settings_snapshot, _save_app_settings_snapshot


def _load_emby_settings_from_db() -> Dict[str, Any]:
    settings = _load_app_settings_snapshot()
    return _merge_emby_settings(settings.get("EMBY"))


def _save_emby_settings_to_db(emby_settings: Dict[str, Any]) -> None:
    settings = _load_app_settings_snapshot()
    settings["EMBY"] = emby_settings
    _save_app_settings_snapshot(settings)


def _purge_emby_server_settings(server_id: str) -> None:
    if not server_id:
        return
    from emby_latest import settings as latest_settings_api

    latest_settings_api._prune_emby_latest_settings_for_server(server_id)
