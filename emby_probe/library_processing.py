"""Focused queue processor for Emby library probing."""

from __future__ import annotations

from typing import Any, Callable, cast
import threading

from .constants import PROBE_SCOPE_LIBRARIES, PROBE_SCOPE_RECENT
from .library_probe_execution import LibraryProbeExecutionMixin


class LibraryProcessingWorker(LibraryProbeExecutionMixin):
    """Consume bounded queue batches for one server and scope."""

    def __init__(
        self,
        manager: Any,
        server: dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: Any,
        target_libraries: list[str] | None,
        scope: str,
        status_key: str,
        *,
        fetch_active_sessions: Callable[..., tuple[list[Any], Any]],
        sleep: Callable[[float], None],
        monotonic_time: Callable[[], float],
    ) -> None:
        self.manager = manager
        self.server = server
        self.server_id = server_id
        self.mode = mode
        self.stop_flag = stop_flag
        self.target_libraries = target_libraries
        self.scope = scope
        self.status_key = status_key
        self.fetch_active_sessions = fetch_active_sessions
        self.sleep = sleep
        self.monotonic_time = monotonic_time
        self.db: Any = None
        self.pause_flag: Any = None
        self.db_write_lock = threading.Lock()
        self.probe_parallelism = 1
        self.queue_batch_size = 100
        self.blacklist: dict[str, Any] = {}

    def run(self) -> None:
        """Run processing and always release pause/status state."""
        try:
            self._run()
        except Exception as exc:
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log=f"Errore critico: {exc}",
            )
        finally:
            self._finalize_worker_state()

    def _run(self) -> None:
        if not self.manager._db_getter:
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log="Errore: database non configurato",
                running=False,
            )
            return
        self._initialize()
        while not self.stop_flag.is_set() and self._run_cycle():
            pass
        self._publish_completion()

    def _initialize(self) -> None:
        self.db = self.manager._db_getter()
        if self.scope == PROBE_SCOPE_LIBRARIES:
            self.pause_flag = self.manager._get_libraries_pause_flag(self.server_id)
        self.probe_parallelism = self.manager._get_probe_parallelism(
            self.server,
            self.server_id,
        )
        self.queue_batch_size = max(100, self.probe_parallelism * 4)

    def _run_cycle(self) -> bool:
        if self._wait_if_paused() or not self._wait_for_recent_discovery():
            return False
        prepared = self._prepare_cycle()
        if prepared is None:
            return False
        processable, library_totals = prepared
        self._announce_retries(processable)
        if self.scope == PROBE_SCOPE_LIBRARIES:
            return self._process_libraries(processable, library_totals)
        return self._handle_queue_items(processable)

    def _wait_if_paused(self) -> bool:
        if not self.pause_flag or not self.pause_flag.is_set():
            return False
        self.manager._update_status(
            self.server_id,
            self.status_key,
            last_log="In pausa: priorità Ultimi aggiunti",
        )
        while self.pause_flag.is_set() and not self.stop_flag.is_set():
            if self.stop_flag.wait(1):
                break
        return self.stop_flag.is_set()

    def _wait_for_recent_discovery(self) -> bool:
        if self.scope != PROBE_SCOPE_RECENT:
            return True
        while not self.stop_flag.is_set():
            with self.manager._lock:
                worker = self.manager._workers.get(self.server_id, {}).get(
                    "recent_discovery"
                )
            if not worker or not worker.is_alive():
                break
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log="In attesa: discovery in corso...",
            )
            if self.stop_flag.wait(1):
                break
        return not self.stop_flag.is_set()

    def _prepare_cycle(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
        queue_items, library_totals = self._load_queue_summary()
        if not queue_items:
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log="Coda vuota, nessun file da processare",
            )
            return None
        self.blacklist = self.db.load_probe_blacklist(self.server_id, scope=self.scope)
        queue_items, processable = self._load_processable_batch(self.target_libraries)
        if not processable:
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log=(
                    "Nessun file processabile: "
                    f"{len(queue_items)} file hanno raggiunto 3+ errori"
                ),
            )
            return None
        if self.scope != PROBE_SCOPE_LIBRARIES:
            queue_items, processable = self._claim_next_processable(
                self.target_libraries
            )
        return (processable, library_totals) if processable else None

    def _load_queue_summary(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        self.manager._update_status(
            self.server_id,
            self.status_key,
            last_log="Caricamento coda dal database...",
        )
        queue_items = self._load_queue_batch(library_ids=self.target_libraries)
        queue_total = self._count_queue(queue_items)
        library_totals = self._count_libraries(queue_items)
        if library_totals:
            self.manager._merge_processing_library_totals(
                self.server_id,
                self.status_key,
                library_totals,
            )
        self.manager._update_status(
            self.server_id,
            self.status_key,
            total=queue_total,
            probe_parallelism=self.probe_parallelism,
            active_slots=0,
            last_log=f"Trovati {queue_total} file da processare",
        )
        return queue_items, library_totals

    def _load_queue_batch(
        self,
        *,
        library_ids: list[str] | None = None,
        cursor_id: int = 0,
    ) -> list[dict[str, Any]]:
        try:
            return self.db.get_probe_queue(
                self.server_id,
                library_ids=library_ids,
                scope=self.scope,
                limit=self.queue_batch_size,
                cursor_id=cursor_id,
            )
        except TypeError as exc:
            if not any(keyword in str(exc) for keyword in ("limit", "cursor_id")):
                raise
            return self.db.get_probe_queue(
                self.server_id,
                library_ids=library_ids,
                scope=self.scope,
            )[: self.queue_batch_size]

    def _count_queue(self, queue_items: list[dict[str, Any]]) -> int:
        count_queue = getattr(self.db, "count_probe_queue", None)
        if not callable(count_queue):
            return len(queue_items)
        return int(
            cast(
                Any,
                count_queue(
                    self.server_id,
                    library_ids=self.target_libraries,
                    scope=self.scope,
                ),
            )
        )

    def _count_libraries(
        self,
        queue_items: list[dict[str, Any]],
    ) -> dict[str, int]:
        if self.scope != PROBE_SCOPE_LIBRARIES:
            return {}
        totals = {
            str(library_id): 0
            for library_id in self.target_libraries or []
            if library_id
        }
        count_by_library = getattr(self.db, "count_probe_queue_by_library", None)
        if callable(count_by_library):
            totals.update(
                cast(
                    dict[str, int],
                    count_by_library(
                        self.server_id,
                        library_ids=self.target_libraries,
                        scope=self.scope,
                    ),
                )
            )
            return totals
        for item in queue_items:
            library_id = item.get("library_id")
            if library_id:
                key = str(library_id)
                totals[key] = totals.get(key, 0) + 1
        return totals

    def _load_processable_batch(
        self,
        library_ids: list[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cursor_id = 0
        while True:
            page = self._load_queue_batch(
                library_ids=library_ids,
                cursor_id=cursor_id,
            )
            candidates = [item for item in page if self._retry_count(item) < 3]
            if candidates or len(page) < self.queue_batch_size:
                return page, candidates
            next_cursor = int(page[-1].get("id") or 0)
            if next_cursor <= cursor_id:
                return page, []
            cursor_id = next_cursor

    def _retry_count(self, item: dict[str, Any]) -> int:
        key = f"{item.get('item_id')}:{item.get('media_source_id') or ''}"
        entry = self.blacklist.get(key)
        return int(entry.get("retry_count") or 0) if entry else 0

    def _claim_processable(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        claim = getattr(self.db, "claim_probe_queue_items", None)
        if not callable(claim):
            return items
        batch_size = max(1, self.probe_parallelism * 2)
        for offset in range(0, len(items), batch_size):
            batch = items[offset : offset + batch_size]
            claimed = cast(
                list[dict[str, Any]],
                claim([int(item["id"]) for item in batch if item.get("id") is not None]),
            )
            if claimed:
                return claimed
        return []

    def _claim_next_processable(
        self,
        library_ids: list[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cursor_id = 0
        last_page: list[dict[str, Any]] = []
        while not self.stop_flag.is_set():
            page = self._load_queue_batch(
                library_ids=library_ids,
                cursor_id=cursor_id,
            )
            last_page = page
            if not page:
                return last_page, []
            candidates = [item for item in page if self._retry_count(item) < 3]
            claimed = self._claim_processable(candidates)
            if claimed:
                return page, claimed
            if len(page) < self.queue_batch_size:
                return page, []
            next_cursor = int(page[-1].get("id") or 0)
            if next_cursor <= cursor_id:
                return page, []
            cursor_id = next_cursor
        return last_page, []

    def _announce_retries(self, processable: list[dict[str, Any]]) -> None:
        retry_count = sum(self._retry_count(item) > 0 for item in processable)
        if not retry_count:
            return
        self.manager._update_status(
            self.server_id,
            self.status_key,
            last_log=(
                f"Processing: {len(processable) - retry_count} primi tentativi + "
                f"{retry_count} retry"
            ),
        )

    def _process_libraries(
        self,
        processable: list[dict[str, Any]],
        library_totals: dict[str, int],
    ) -> bool:
        for library_id in self._library_order(processable, library_totals):
            if self.stop_flag.is_set():
                return False
            if not self._process_library(library_id):
                return False
        return not self.stop_flag.is_set()

    def _library_order(
        self,
        processable: list[dict[str, Any]],
        library_totals: dict[str, int],
    ) -> list[str]:
        selected = [
            str(library_id) for library_id in self.target_libraries or [] if library_id
        ]
        if selected:
            return selected
        names = {
            str(item["library_id"]): str(item.get("library_name") or item["library_id"])
            for item in processable
            if item.get("library_id")
        }
        return sorted(
            library_totals or names,
            key=lambda library_id: names.get(library_id, library_id).lower(),
        )

    def _process_library(self, library_id: str) -> bool:
        while not self.stop_flag.is_set():
            self.blacklist = self.db.load_probe_blacklist(
                self.server_id,
                scope=self.scope,
            )
            queue, claimed = self._claim_next_processable([library_id])
            if not queue:
                return True
            if not claimed:
                return True
            self._publish_library_start(library_id, queue, claimed)
            if not self._handle_queue_items(claimed):
                return not self.stop_flag.is_set()
        return False

    def _publish_library_start(
        self,
        library_id: str,
        queue: list[dict[str, Any]],
        claimed: list[dict[str, Any]],
    ) -> None:
        library_name = claimed[0].get("library_name") or queue[0].get("library_name")
        self.manager._update_status(
            self.server_id,
            self.status_key,
            current_library_id=library_id,
            current_library_name=library_name,
        )

    def _publish_completion(self) -> None:
        if self.stop_flag.is_set():
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log="Processing interrotto dall'utente",
            )
            return
        status = self.manager._status.get(self.server_id, {}).get(self.status_key, {})
        processed = status.get("processed", 0)
        incomplete = status.get("incomplete", 0)
        errors = status.get("errors", 0)
        if processed + incomplete + errors == 0:
            return
        parts = [f"Successi: {processed}"]
        if incomplete > 0:
            parts.append(f"Incompleti: {incomplete}")
        if errors > 0:
            parts.append(f"Errori: {errors}")
        self.manager._update_status(
            self.server_id,
            self.status_key,
            last_log=f"Processing completato. {', '.join(parts)}",
        )

    def _finalize_worker_state(self) -> None:
        if self.scope == PROBE_SCOPE_RECENT:
            self.manager._set_libraries_pause(self.server_id, False)
        with self.manager._lock:
            status = self.manager._status.get(self.server_id, {}).get(self.status_key)
            if status is not None:
                status["running"] = False
                status["current_library_id"] = None
                status["current_library_name"] = None
                status["active_slots"] = 0
            self._finalize_combo_status()

    def _finalize_combo_status(self) -> None:
        if self.scope != PROBE_SCOPE_LIBRARIES or self.status_key != "processing":
            return
        combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
        combo_status = self.manager._status.get(self.server_id, {}).get(combo_key, {})
        if not combo_status or combo_status.get("running"):
            return
        if combo_status.get("board_mode") != "processing":
            return
        library_ids = (
            self.manager._status.get(self.server_id, {})
            .get(self.status_key, {})
            .get("target_library_ids")
            or []
        )
        combo_status["last_run"] = self.manager._build_combo_last_run(
            [self.server],
            PROBE_SCOPE_LIBRARIES,
            self.stop_flag.is_set(),
            library_ids=library_ids,
            task_types=["processing"],
        )
        combo_status["board_reset"] = True
