import logging
import random
import threading
from typing import Any, Dict, Set, Tuple

from app import _ACTIVE_CONFIG
from config import DEFAULT_CONFIG
from emby_collection_sources import list_mdblist_user_lists
from emby_collections import list_collection_definitions, run_collection_sync, save_collection_definition

logger = logging.getLogger(__name__)


class CollectionAutoRefresher(threading.Thread):
    def __init__(self):
        super().__init__(name="CollectionAutoRefresher", daemon=True)
        self._stop_event = threading.Event()
        self.start()

    def run(self) -> None:
        while not self._stop_event.is_set():
            settings = self._get_collection_settings()
            interval_hours = max(1, int(settings.get("AUTO_REFRESH_INTERVAL_HOURS", DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_HOURS"])))
            if settings.get("AUTO_REFRESH_ENABLED"):
                try:
                    self._run_cycle(settings)
                except Exception as exc:
                    logger.exception("Errore nella sincronizzazione automatica collezioni: %s", exc)
            wait_seconds = interval_hours * 3600
            self._stop_event.wait(wait_seconds)

    def stop(self) -> None:
        self._stop_event.set()

    def _get_collection_settings(self) -> Dict[str, Any]:
        config = _ACTIVE_CONFIG or {}
        merged = dict(DEFAULT_CONFIG["COLLECTIONS"])
        merged.update((config.get("COLLECTIONS") or {}))
        return merged

    def _run_cycle(self, settings: Dict[str, Any]) -> None:
        definitions = list_collection_definitions()
        source_keys: Set[Tuple[str, str]] = {
            (entry.get("source_type"), entry.get("source_value")) for entry in definitions
        }
        if settings.get("DOWNLOAD_MY_MDBLIST_LISTS"):
            self._ensure_my_mdblist_definitions(source_keys)
        for definition in definitions:
            if not definition.get("enabled") or not definition.get("auto_enabled"):
                continue
            frequency = int(definition.get("auto_frequency", 100))
            if frequency < 100 and random.randint(1, 100) > frequency:
                continue
            definition_id = definition.get("id")
            if not definition_id:
                continue
            try:
                logger.info("Sincronizzazione automatica collezione %s (%s)", definition.get("name"), definition_id)
                run_collection_sync(definition_id)
            except Exception:
                logger.exception("Sincronizzazione automatica fallita per %s", definition_id)

    def _ensure_my_mdblist_definitions(self, existing_keys: Set[Tuple[str, str]]) -> None:
        try:
            user_lists = list_mdblist_user_lists()
        except RuntimeError as exc:
            logger.warning("Impossibile scaricare le liste MDBList personali: %s", exc)
            return
        for entry in user_lists:
            source_value = entry.get("source_value")
            if not source_value:
                continue
            key = ("mdblist", source_value)
            if key in existing_keys:
                continue
            payload = {
                "name": entry.get("name") or f"MDBList {source_value}",
                "sort_name": entry.get("name") or f"MDBList {source_value}",
                "source_type": "mdblist",
                "source_value": source_value,
                "enabled": True,
                "auto_enabled": True,
                "auto_frequency": 100,
                "collection_description": entry.get("description") or "",
                "use_source_description": False
            }
            try:
                definition = save_collection_definition(payload)
                logger.info("Aggiunta automatica collezione MDBList %s (%s)", payload["name"], definition.get("id"))
                existing_keys.add(key)
            except Exception:
                logger.exception("Errore creazione collezione MDBList %s", payload["name"])


_REFRESHER: CollectionAutoRefresher | None = None


def start_collection_auto_refresher() -> CollectionAutoRefresher:
    global _REFRESHER
    if _REFRESHER is None:
        _REFRESHER = CollectionAutoRefresher()
    return _REFRESHER
