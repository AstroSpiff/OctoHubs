"""Execution lifecycle for individual Emby probe queue items."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable
import logging
import threading

from core.log_sanitization import format_exception_for_log

from .constants import PROBE_SCOPE_LIBRARIES
from .display import _format_display_name_from_queue
from .queue_leases import (
    ProbeClaimLost,
    commit_claimed_result,
    complete_claim,
    release_claim,
    renew_claim,
    run_with_claim_renewal,
)


logger = logging.getLogger(__name__)


@dataclass
class _ProbeResult:
    status: str
    error_details: str | None
    should_requeue: bool
    duration_ms: int
    retry_count: int


class LibraryProbeExecutionMixin:
    """Probe, persist, and publish one claimed queue batch."""

    manager: Any
    server: dict[str, Any]
    server_id: str
    mode: str
    stop_flag: Any
    scope: str
    status_key: str
    fetch_active_sessions: Callable[..., tuple[list[Any], Any]]
    sleep: Callable[[float], None]
    monotonic_time: Callable[[], float]
    db: Any
    db_write_lock: threading.Lock
    probe_parallelism: int

    def _retry_count(self, item: dict[str, Any]) -> int:
        raise NotImplementedError

    def _wait_if_paused(self) -> bool:
        raise NotImplementedError

    def _handle_queue_item(self, queue_item: dict[str, Any]) -> bool:
        claim_finished = threading.Event()
        try:
            return run_with_claim_renewal(
                self.db,
                queue_item,
                lambda: self._handle_claimed_queue_item(queue_item, claim_finished),
                on_claim_lost=self.stop_flag.set,
                claim_finished=claim_finished,
                renew_lock=self.db_write_lock,
            )
        except ProbeClaimLost:
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log="Processing interrotto: lease della coda non più valida",
            )
            return False
        finally:
            if not claim_finished.is_set():
                try:
                    self._release_claim(queue_item, claim_finished)
                except Exception as exc:
                    logger.error(
                        "Rilascio finale lease Probe non riuscito:\n%s",
                        format_exception_for_log(exc),
                    )

    def _handle_claimed_queue_item(
        self,
        queue_item: dict[str, Any],
        claim_finished: threading.Event | None = None,
    ) -> bool:
        if self.stop_flag.is_set() or self._wait_if_paused():
            return False
        if not self._wait_until_server_available():
            return False
        self._publish_item_start(queue_item)
        result = self._probe(queue_item)
        if result is None:
            self._release_claim(queue_item, claim_finished)
            return False
        try:
            renewed = self._renew_claim(queue_item)
        except Exception as exc:
            self.stop_flag.set()
            raise ProbeClaimLost("Rinnovo finale della lease Probe non riuscito") from exc
        if not renewed:
            self.stop_flag.set()
            return False
        committed_atomically = self._commit_result_atomically(
            queue_item,
            result,
            claim_finished,
        )
        if not committed_atomically:
            result = self._record_result(queue_item, result)
        self._publish_item_result(queue_item, result)
        if not committed_atomically:
            self._finish_claim(queue_item, result.should_requeue, claim_finished)
        return not self.stop_flag.wait(1)

    def _wait_until_server_available(self) -> bool:
        if self.mode != "smart":
            return True
        while not self.stop_flag.is_set():
            if self._wait_if_paused():
                return False
            sessions, error = self.fetch_active_sessions(self.server)
            if error or not sessions:
                break
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log=f"In pausa: {len(sessions)} stream attivi sul server...",
            )
            if self.stop_flag.wait(10):
                break
        return not self.stop_flag.is_set()

    def _publish_item_start(self, queue_item: dict[str, Any]) -> None:
        display_name = _format_display_name_from_queue(queue_item)
        self.manager._update_status(
            self.server_id,
            self.status_key,
            current_item=display_name,
            current_library_id=queue_item.get("library_id"),
            current_library_name=queue_item.get("library_name"),
            last_log=f"Analisi: {display_name}",
        )

    def _probe(self, queue_item: dict[str, Any]) -> _ProbeResult | None:
        item_id = queue_item["item_id"]
        media_source_id = queue_item.get("media_source_id")
        display_name = _format_display_name_from_queue(queue_item)
        retry_count = self._retry_count(queue_item)
        started_at = self.monotonic_time()
        success = self.manager._probe_item(
            self.server,
            item_id,
            display_name,
            media_source_id,
        )
        duration_ms = int((self.monotonic_time() - started_at) * 1000)
        if self.stop_flag.is_set():
            return None
        if not success:
            return _ProbeResult(
                "ERROR",
                "Timeout o errore API",
                True,
                duration_ms,
                retry_count,
            )
        metadata_ok, metadata_error = self._poll_metadata(item_id, media_source_id)
        if metadata_ok:
            return _ProbeResult("SUCCESS", None, False, duration_ms, retry_count)
        return _ProbeResult(
            "INCOMPLETE",
            metadata_error or "Mediainfo non scritto dopo polling",
            True,
            duration_ms,
            retry_count,
        )

    def _poll_metadata(
        self,
        item_id: str,
        media_source_id: str | None,
    ) -> tuple[bool, str | None]:
        self.sleep(1)
        metadata_error = None
        for attempt in range(15):
            if self.stop_flag.is_set():
                break
            metadata_ok, metadata_error = self.manager._verify_probe_metadata(
                self.server,
                item_id,
                media_source_id,
            )
            if metadata_ok:
                return True, metadata_error
            if attempt < 14:
                self.sleep(1)
        return False, metadata_error

    def _renew_claim(self, queue_item: dict[str, Any]) -> bool:
        with self.db_write_lock:
            return renew_claim(self.db, queue_item)

    def _release_claim(
        self,
        queue_item: dict[str, Any],
        claim_finished: threading.Event | None = None,
    ) -> None:
        with self.db_write_lock:
            release_claim(
                self.db,
                queue_item,
                server_id=self.server_id,
                scope=self.scope,
            )
            if claim_finished is not None:
                claim_finished.set()

    def _record_result(
        self,
        queue_item: dict[str, Any],
        result: _ProbeResult,
    ) -> _ProbeResult:
        if result.status == "SUCCESS":
            with self.db_write_lock:
                self.db.remove_from_probe_blacklist(
                    self.server_id,
                    queue_item["item_id"],
                    queue_item.get("media_source_id"),
                    scope=self.scope,
                )
        else:
            retry_count = self._record_failure(queue_item, result)
            result.should_requeue = retry_count < 3
        with self.db_write_lock:
            self.db.add_probe_history(self._history_payload(queue_item, result))
        return result

    def _commit_result_atomically(
        self,
        queue_item: dict[str, Any],
        result: _ProbeResult,
        claim_finished: threading.Event | None = None,
    ) -> bool:
        """Use the token-fenced storage transaction when the backend supports it."""
        failure = None
        if result.status != "SUCCESS":
            failure = {
                "reason": result.error_details or "Errore probe",
                "error_type": (
                    "INCOMPLETE" if result.status == "INCOMPLETE" else "ERROR"
                ),
                "library_id": queue_item.get("library_id"),
            }
        try:
            outcome = commit_claimed_result(
                self.db,
                queue_item,
                self._history_payload(queue_item, result),
                failure=failure,
                max_retries=3,
                allow_requeue=not self.stop_flag.is_set(),
                claim_finished=claim_finished,
                coordination_lock=self.db_write_lock,
            )
        except ProbeClaimLost:
            self.stop_flag.set()
            raise
        if outcome is None:
            return False
        result.should_requeue = bool(outcome.get("requeued"))
        return True

    def _record_failure(
        self,
        queue_item: dict[str, Any],
        result: _ProbeResult,
    ) -> int:
        error_type = "INCOMPLETE" if result.status == "INCOMPLETE" else "ERROR"
        with self.db_write_lock:
            return self.db.update_probe_blacklist(
                self.server_id,
                queue_item["item_id"],
                _format_display_name_from_queue(queue_item),
                result.error_details or "Errore probe",
                media_source_id=queue_item.get("media_source_id"),
                increment_retry=True,
                error_type=error_type,
                scope=self.scope,
                library_id=queue_item.get("library_id"),
                library_name=queue_item.get("library_name"),
            )

    def _history_payload(
        self,
        queue_item: dict[str, Any],
        result: _ProbeResult,
    ) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "item_id": queue_item["item_id"],
            "media_source_id": queue_item.get("media_source_id"),
            "scope": self.scope,
            "name": _format_display_name_from_queue(queue_item),
            "library_name": queue_item.get("library_name"),
            "status": result.status,
            "error_details": result.error_details,
            "duration_ms": result.duration_ms,
        }

    def _publish_item_result(
        self,
        queue_item: dict[str, Any],
        result: _ProbeResult,
    ) -> None:
        display_name = _format_display_name_from_queue(queue_item)
        label, counter, library_counter = self._result_labels(result)
        retry_label = f" (retry {result.retry_count})" if result.retry_count > 0 else ""
        self.manager._update_status(
            self.server_id,
            self.status_key,
            last_log=f"{label}{retry_label}: {display_name}",
            **{counter: 1},
        )
        library_id = queue_item.get("library_id")
        if (
            not result.should_requeue
            and self.scope == PROBE_SCOPE_LIBRARIES
            and library_id
        ):
            self.manager._increment_processing_library_result(
                self.server_id,
                self.status_key,
                str(library_id),
                library_counter,
            )

    @staticmethod
    def _result_labels(result: _ProbeResult) -> tuple[str, str, str]:
        is_retry = result.retry_count > 0
        if result.status == "SUCCESS":
            return (
                "Completato",
                ("increment_processed_retry" if is_retry else "increment_processed"),
                "processed",
            )
        if result.status == "INCOMPLETE":
            return (
                "Incompleto",
                ("increment_incomplete_retry" if is_retry else "increment_incomplete"),
                "incomplete",
            )
        return (
            "Errore",
            ("increment_errors_retry" if is_retry else "increment_errors"),
            "errors",
        )

    def _finish_claim(
        self,
        queue_item: dict[str, Any],
        should_requeue: bool,
        claim_finished: threading.Event | None = None,
    ) -> None:
        with self.db_write_lock:
            if should_requeue and not self.stop_flag.is_set():
                release_claim(
                    self.db,
                    queue_item,
                    server_id=self.server_id,
                    scope=self.scope,
                )
            else:
                complete_claim(
                    self.db,
                    queue_item,
                    server_id=self.server_id,
                    scope=self.scope,
                )
            if claim_finished is not None:
                claim_finished.set()

    def _handle_queue_items(self, queue_items: list[dict[str, Any]]) -> bool:
        if self.probe_parallelism > 1:
            return self._handle_queue_items_parallel(queue_items)
        for index, queue_item in enumerate(queue_items):
            if not self._handle_queue_item(queue_item):
                self._release_unstarted_claims(queue_items[index + 1 :])
                return False
        return True

    def _release_unstarted_claims(self, queue_items: list[dict[str, Any]]) -> None:
        for queue_item in queue_items:
            try:
                self._release_claim(queue_item)
            except Exception as exc:
                logger.error(
                    "Rilascio lease Probe non avviata non riuscito:\n%s",
                    format_exception_for_log(exc),
                )

    def _handle_queue_items_parallel(
        self,
        queue_items: list[dict[str, Any]],
    ) -> bool:
        next_index = 0
        active_names: dict[Future[bool], str] = {}
        futures: dict[Future[bool], dict[str, Any]] = {}
        pool_ok = True
        with ThreadPoolExecutor(max_workers=self.probe_parallelism) as executor:
            next_index = self._fill_slots(
                executor,
                futures,
                active_names,
                queue_items,
                next_index,
            )
            while futures and not self.stop_flag.is_set() and pool_ok:
                pool_ok, next_index = self._consume_completed(
                    executor,
                    futures,
                    active_names,
                    queue_items,
                    next_index,
                )
        self._release_unstarted_claims(queue_items[next_index:])
        self.manager._update_status(self.server_id, self.status_key, active_slots=0)
        return pool_ok and not self.stop_flag.is_set()

    def _fill_slots(
        self,
        executor: ThreadPoolExecutor,
        futures: dict[Future[bool], dict[str, Any]],
        active_names: dict[Future[bool], str],
        queue_items: list[dict[str, Any]],
        next_index: int,
    ) -> int:
        while len(futures) < self.probe_parallelism and next_index < len(queue_items):
            if self.stop_flag.is_set():
                break
            queue_item = queue_items[next_index]
            next_index += 1
            future = executor.submit(self._handle_queue_item, queue_item)
            futures[future] = queue_item
            active_names[future] = _format_display_name_from_queue(queue_item)
            self._publish_active_slots(active_names, include_log=True)
        return next_index

    def _consume_completed(
        self,
        executor: ThreadPoolExecutor,
        futures: dict[Future[bool], dict[str, Any]],
        active_names: dict[Future[bool], str],
        queue_items: list[dict[str, Any]],
        next_index: int,
    ) -> tuple[bool, int]:
        for future in as_completed(list(futures)):
            queue_item = futures.pop(future)
            active_names.pop(future, None)
            if not self._future_succeeded(future, queue_item):
                self._publish_active_slots(active_names)
                return False, next_index
            next_index = self._fill_slots(
                executor,
                futures,
                active_names,
                queue_items,
                next_index,
            )
            self._publish_active_slots(active_names)
        return True, next_index

    def _future_succeeded(
        self,
        future: Future[bool],
        queue_item: dict[str, Any],
    ) -> bool:
        try:
            return future.result()
        except Exception as exc:
            item_name = _format_display_name_from_queue(queue_item)
            self.manager._update_status(
                self.server_id,
                self.status_key,
                last_log=f"Errore analisi parallela: {item_name} ({exc})",
                increment_errors=1,
            )
            return False

    def _publish_active_slots(
        self,
        active_names: dict[Future[bool], str],
        *,
        include_log: bool = False,
    ) -> None:
        names = list(active_names.values())
        updates: dict[str, Any] = {
            "current_item": ", ".join(names[:3]) if names else None,
            "active_slots": len(active_names),
            "probe_parallelism": self.probe_parallelism,
        }
        if include_log:
            updates["last_log"] = (
                f"Analisi parallela: {len(active_names)}/{self.probe_parallelism} "
                "slot attivi"
            )
        self.manager._update_status(self.server_id, self.status_key, **updates)
