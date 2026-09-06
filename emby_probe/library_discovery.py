"""Focused worker for discovering Emby items that need probing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.pagination import MAX_EMBY_ITEMS, MAX_EMBY_PAGES, PaginationGuard, pagination_error

from .constants import PROBE_SCOPE_LIBRARIES
from .display import _format_probe_display_name
from .media_policy import (
    is_probe_media_candidate,
    load_probe_config,
    normalize_media_policy,
)


class LibraryDiscoveryWorker:
    """Run one library discovery while keeping orchestration out of the mixin."""

    _PAGE_SIZE = 50
    _BATCH_SIZE = 20

    def __init__(
        self,
        manager: Any,
        server: dict[str, Any],
        server_id: str,
        stop_flag: Any,
        target_libraries: list[str] | None,
        *,
        call_emby_api: Callable[..., tuple[bool, Any]],
        fetch_libraries: Callable[..., tuple[list[dict[str, Any]], Any]],
    ) -> None:
        self.manager = manager
        self.server = server
        self.server_id = server_id
        self.stop_flag = stop_flag
        self.target_libraries = target_libraries
        self.call_emby_api = call_emby_api
        self.fetch_libraries = fetch_libraries
        self.db: Any = None
        self.media_policy: Any = None
        self.items_batch: list[dict[str, Any]] = []
        self.page_error: Any = None

    def run(self) -> None:
        """Run discovery and always publish terminal worker state."""
        primary_error = None
        try:
            self._run()
        except BaseException as exc:
            primary_error = exc
            self.manager._update_status(
                self.server_id,
                "discovery",
                last_log="Errore critico: worker discovery non riuscito",
            )
        finally:
            self._finalize_worker_state()
        if primary_error is not None and not isinstance(primary_error, Exception):
            raise primary_error

    def _run(self) -> None:
        if not self.manager._db_getter:
            self.manager._update_status(
                self.server_id,
                "discovery",
                last_log="Errore: database non configurato",
                running=False,
            )
            return
        self.db = self.manager._db_getter()
        self.media_policy = self._load_media_policy()
        libraries = self._load_libraries()
        if not libraries:
            return
        for library in libraries:
            if self.stop_flag.is_set():
                break
            self._scan_library(library)
        added = self._flush_batch()
        if added:
            self.manager._update_status(
                self.server_id,
                "discovery",
                increment_found=added,
            )
        self._publish_completion()

    def _load_media_policy(self) -> Any:
        probe_config = load_probe_config(self.db, self.server_id)
        return normalize_media_policy(probe_config.get("media_policy"))

    def _load_libraries(self) -> list[dict[str, Any]]:
        self.manager._update_status(
            self.server_id,
            "discovery",
            last_log="Recupero librerie dal server...",
        )
        libraries, error = self.fetch_libraries(self.server)
        if error or not libraries:
            self.manager._update_status(
                self.server_id,
                "discovery",
                last_log=f"Errore recupero librerie: {error or 'Nessuna libreria trovata'}",
            )
            return []
        if self.target_libraries:
            libraries = [
                library
                for library in libraries
                if library.get("id") in self.target_libraries
            ]
        if not libraries:
            self.manager._update_status(
                self.server_id,
                "discovery",
                last_log="Nessuna libreria da scansionare",
            )
        return libraries

    def _scan_library(self, library: dict[str, Any]) -> None:
        library_id = library.get("id")
        if not library_id:
            return
        library_name = library.get("name", "Sconosciuto")
        self._publish_library_start(str(library_id), library_name)
        start_index = 0
        library_error = False
        guard = PaginationGuard(MAX_EMBY_PAGES, MAX_EMBY_ITEMS)
        while not self.stop_flag.is_set():
            page = self._fetch_page(library_id, start_index)
            if page is None:
                self._publish_library_error(str(library_id), library_name)
                library_error = True
                break
            items, total_count = page
            if pagination_error(guard, items):
                self._publish_library_error(str(library_id), library_name)
                library_error = True
                break
            self.manager._set_library_total(self.server_id, library_id, total_count)
            if not items:
                break
            self._queue_page(items, library_id, library_name)
            self._publish_page_progress(
                str(library_id), library_name, start_index, items, total_count
            )
            start_index += self._PAGE_SIZE
            if start_index >= total_count:
                break
        if not self.stop_flag.is_set() and not library_error:
            self.manager._mark_library_completed(self.server_id, str(library_id))

    def _publish_library_start(self, library_id: str, library_name: str) -> None:
        self.manager._update_status(
            self.server_id,
            "discovery",
            current_library_id=library_id,
            current_library_name=library_name,
        )
        self.manager._update_status(
            self.server_id,
            "discovery",
            last_log=f"Scansione libreria: {library_name}",
        )

    def _fetch_page(
        self,
        library_id: str,
        start_index: int,
    ) -> tuple[list[Any], int] | None:
        success, payload = self.call_emby_api(
            self.server,
            "Items",
            method="GET",
            params={
                "ParentId": library_id,
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                "Fields": (
                    "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,"
                    "SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,"
                    "SeriesProductionYear,Type"
                ),
                "StartIndex": start_index,
                "Limit": self._PAGE_SIZE,
            },
        )
        if not success or not isinstance(payload, dict):
            self.page_error = payload
            return None
        items = payload.get("Items", [])
        return (items if isinstance(items, list) else []), int(
            payload.get("TotalRecordCount", 0) or 0
        )

    def _publish_library_error(self, library_id: str, library_name: str) -> None:
        self.manager._update_status(
            self.server_id,
            "discovery",
            last_log=f"Errore recupero item da {library_name}: {self.page_error}",
        )
        self.manager._mark_library_error(self.server_id, library_id)

    def _queue_page(
        self,
        items: list[Any],
        library_id: str,
        library_name: str,
    ) -> None:
        blacklist = self.db.load_probe_blacklist(
            self.server_id,
            scope=PROBE_SCOPE_LIBRARIES,
        )
        for item in items:
            if self.stop_flag.is_set():
                break
            self.items_batch.extend(
                self._queue_entries(item, library_id, library_name, blacklist)
            )
            if len(self.items_batch) >= self._BATCH_SIZE:
                added = self._flush_batch()
                self.manager._update_status(
                    self.server_id,
                    "discovery",
                    increment_found=added,
                    last_log=f"Aggiunti {added} file alla coda da {library_name}",
                )

    def _queue_entries(
        self,
        item: Any,
        library_id: str,
        library_name: str,
        blacklist: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not isinstance(item, dict) or not item.get("Id"):
            return []
        item_path = item.get("Path", "")
        if not is_probe_media_candidate(item_path, self.media_policy):
            return []
        return [
            self._queue_entry(item, source, library_id, library_name, item_path)
            for source in self._media_sources(item)
            if self._source_needs_probe(item, source)
            and not self._is_blacklisted(blacklist, item["Id"], self._source_id(source))
        ]

    @staticmethod
    def _media_sources(item: dict[str, Any]) -> list[dict[str, Any] | None]:
        sources = item.get("MediaSources")
        if not isinstance(sources, list) or not sources:
            return [None]
        return [
            source for source in sources if source is None or isinstance(source, dict)
        ]

    @staticmethod
    def _source_id(source: dict[str, Any] | None) -> Any:
        return source.get("Id") if source else None

    @staticmethod
    def _source_needs_probe(
        item: dict[str, Any],
        source: dict[str, Any] | None,
    ) -> bool:
        streams = (
            source.get("MediaStreams", []) if source else item.get("MediaStreams", [])
        )
        runtime = source.get("RunTimeTicks") if source else item.get("RunTimeTicks")
        return not (runtime and streams)

    @staticmethod
    def _is_blacklisted(
        blacklist: dict[str, Any],
        item_id: str,
        media_source_id: str | None,
    ) -> bool:
        entry = blacklist.get(f"{item_id}:{media_source_id or ''}")
        return bool(entry and int(entry.get("retry_count") or 0) >= 3)

    def _queue_entry(
        self,
        item: dict[str, Any],
        source: dict[str, Any] | None,
        library_id: str,
        library_name: str,
        item_path: str,
    ) -> dict[str, Any]:
        item_type = item.get("Type", "")
        item_name = item.get("Name", "Sconosciuto")
        series_name = item.get("SeriesName")
        season_number = item.get("ParentIndexNumber")
        episode_number = item.get("IndexNumber")
        year = item.get("SeriesProductionYear") or item.get("ProductionYear")
        source_id = self._source_id(source)
        source_name = source.get("Name") if source else None
        return {
            "server_id": self.server_id,
            "item_id": item["Id"],
            "scope": PROBE_SCOPE_LIBRARIES,
            "media_source_id": source_id,
            "library_id": library_id,
            "library_name": library_name,
            "name": _format_probe_display_name(
                item_type,
                item_name,
                year,
                series_name,
                season_number,
                episode_number,
                item_path,
                source_name,
            ),
            "series_name": series_name,
            "season_number": season_number,
            "episode_number": episode_number,
            "year": year,
            "media_type": item_type,
            "path": item_path,
        }

    def _flush_batch(self) -> int:
        if not self.items_batch or self.stop_flag.is_set():
            return 0
        batch = self.items_batch
        self.items_batch = []
        self.db.add_to_probe_queue(batch)
        return len(batch)

    def _publish_page_progress(
        self,
        library_id: str,
        library_name: str,
        start_index: int,
        items: list[Any],
        total_count: int,
    ) -> None:
        self.manager._update_status(
            self.server_id,
            "discovery",
            increment_total_scanned=len(items),
            last_log=(
                f"Scansionati {start_index + len(items)}/{total_count} item "
                f"in {library_name}"
            ),
        )
        self.manager._increment_library_scanned(
            self.server_id,
            library_id,
            len(items),
        )

    def _publish_completion(self) -> None:
        if self.stop_flag.is_set():
            message = "Discovery interrotta dall'utente"
        else:
            found = (
                self.manager._status.get(self.server_id, {})
                .get("discovery", {})
                .get("found", 0)
            )
            message = f"Discovery completata. Trovati {found} file da analizzare."
        self.manager._update_status(
            self.server_id,
            "discovery",
            last_log=message,
        )

    def _finalize_worker_state(self) -> None:
        with self.manager._lock:
            status = self.manager._status.get(self.server_id, {}).get("discovery")
            if status is not None:
                status["running"] = False
                status["current_library_id"] = None
                status["current_library_name"] = None
            self._finalize_combo_status()

    def _finalize_combo_status(self) -> None:
        combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
        combo_status = self.manager._status.get(self.server_id, {}).get(combo_key, {})
        if not combo_status or combo_status.get("running"):
            return
        if combo_status.get("board_mode") != "discovery":
            return
        library_ids = (
            self.manager._status.get(self.server_id, {})
            .get("discovery", {})
            .get("target_library_ids")
            or []
        )
        combo_status["last_run"] = self.manager._build_combo_last_run(
            [self.server],
            PROBE_SCOPE_LIBRARIES,
            self.stop_flag.is_set(),
            library_ids=library_ids,
            task_types=["discovery"],
        )
        combo_status["board_reset"] = True
