import logging
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Dict

from core import config_manager
from core.config import DEFAULT_CONFIG
from core.log_sanitization import format_exception_for_log
from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread,
)
from .manager import list_collection_definitions, run_collection_sync

logger = logging.getLogger(__name__)


class CollectionAutoRefresher(threading.Thread):
    def __init__(self):
        super().__init__(name="CollectionAutoRefresher", daemon=True)
        self._stop_event = threading.Event()
        self._next_run = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                settings = self._get_collection_settings()
                if not settings.get("AUTO_REFRESH_ENABLED"):
                    self._next_run = None
                    self._stop_event.wait(60)
                    continue
                now = datetime.now()
                if self._next_run is None:
                    self._next_run = self._calculate_next_run(settings, now)
                if self._next_run and now >= self._next_run:
                    self._run_cycle(settings)
                    self._next_run = self._calculate_next_run(settings, datetime.now())
                    if self._next_run is None:
                        self._next_run = datetime.now() + timedelta(minutes=5)
                wait_seconds = self._calculate_wait_seconds(settings, self._next_run, now)
            except BaseException as exc:
                log_lifecycle_exception_safely(
                    logger, "Ciclo automatico collezioni non riuscito: %s", exc
                )
                wait_seconds = 1.0
            self._stop_event.wait(wait_seconds)

    def stop(self) -> None:
        self._stop_event.set()

    def _get_collection_settings(self) -> Dict[str, Any]:
        config = config_manager._ACTIVE_CONFIG or {}
        merged = dict(DEFAULT_CONFIG["COLLECTIONS"])
        merged.update((config.get("COLLECTIONS") or {}))
        return merged

    def _calculate_next_run(self, settings: Dict[str, Any], reference: datetime) -> datetime | None:
        mode = settings.get("AUTO_REFRESH_MODE") or "interval"
        if mode == "fixed":
            times = settings.get("AUTO_REFRESH_TIMES") or []
            if isinstance(times, str):
                times = [token.strip() for token in times.split(",") if token.strip()]
            if times:
                candidates = []
                for token in times:
                    try:
                        hour = int(token.split(":")[0])
                        minute = int(token.split(":")[1])
                    except (ValueError, IndexError):
                        continue
                    candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if candidate <= reference:
                        candidate += timedelta(days=1)
                    candidates.append(candidate)
                if candidates:
                    return min(candidates)
        interval_minutes = max(
            5,
            int(settings.get("AUTO_REFRESH_INTERVAL_MINUTES", DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"]))
        )
        return reference + timedelta(minutes=interval_minutes)

    def _calculate_wait_seconds(self, settings: Dict[str, Any], next_run: datetime | None, now: datetime) -> float:
        if next_run:
            delta = (next_run - now).total_seconds()
            return max(10, min(3600, delta))
        interval_minutes = max(
            5,
            int(settings.get("AUTO_REFRESH_INTERVAL_MINUTES", DEFAULT_CONFIG["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"]))
        )
        return float(interval_minutes * 60)

    def _run_cycle(self, settings: Dict[str, Any]) -> None:
        definitions = list_collection_definitions()
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
            except Exception as exc:
                logger.error("Sincronizzazione automatica fallita per %s:\n%s", definition_id, format_exception_for_log(exc))


_REFRESHER: CollectionAutoRefresher | None = None
_REFRESHER_LOCK = threading.Lock()


def start_collection_auto_refresher() -> CollectionAutoRefresher:
    global _REFRESHER
    with _REFRESHER_LOCK:
        if _REFRESHER is not None and _REFRESHER.is_alive():
            return _REFRESHER
        if _REFRESHER is not None:
            _REFRESHER.stop()
            join_owned_thread(_REFRESHER, 1.0)

        refresher = CollectionAutoRefresher()
        _REFRESHER = refresher

        def rollback_unstarted() -> None:
            global _REFRESHER
            refresher.stop()
            if _REFRESHER is refresher:
                _REFRESHER = None

        start_owned_thread(
            refresher,
            rollback_unstarted=rollback_unstarted,
            context="collection auto refresher",
        )
        return refresher


def shutdown_collection_auto_refresher(timeout_seconds: float = 5.0) -> bool:
    """Stop and release the process-owned collection refresher."""
    global _REFRESHER
    with _REFRESHER_LOCK:
        refresher = _REFRESHER
        if refresher is None:
            return True
        refresher.stop()
    stopped = join_owned_thread(refresher, max(0.0, timeout_seconds))
    if stopped:
        with _REFRESHER_LOCK:
            if _REFRESHER is refresher:
                _REFRESHER = None
    return stopped
