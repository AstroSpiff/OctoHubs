from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional, Protocol


class ProbeManagerProtocol(Protocol):
    _lock: threading.Lock
    _workers: Dict[str, Dict[str, threading.Thread]]
    _status: Dict[str, Dict[str, Any]]
    _stop_flags: Dict[str, Dict[str, threading.Event]]
    _global_workers: Dict[str, threading.Thread]
    _global_stop_flags: Dict[str, threading.Event]
    _libraries_pause_flags: Dict[str, threading.Event]
    _db_getter: Optional[Callable[[], Any]]

    def _update_status(self, server_id: str, worker_type: str, **kwargs: Any) -> None: ...
    def _set_libraries_pause(self, server_id: str, paused: bool) -> None: ...
    def _get_libraries_pause_flag(self, server_id: str) -> threading.Event: ...
    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]],
        scope: str,
        status_key: str,
    ) -> None: ...
    def _wait_for_worker(self, worker: Optional[threading.Thread], stop_flag: threading.Event) -> None: ...
    def _build_combo_queue(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None,
    ) -> list[Dict[str, Any]]: ...
    def _build_combo_last_run(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        interrupted: bool,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None,
    ) -> Dict[str, Any]: ...
    def _merge_processing_library_totals(self, server_id: str, status_key: str, totals: Dict[str, int]) -> None: ...
    def _mark_library_error(self, server_id: str, library_id: str) -> None: ...
    def _set_library_total(self, server_id: str, library_id: str, total_count: int) -> None: ...
    def _increment_library_scanned(self, server_id: str, library_id: str, count: int) -> None: ...
    def _mark_library_completed(self, server_id: str, library_id: str) -> None: ...
    def _increment_processing_library_result(
        self,
        server_id: str,
        status_key: str,
        library_id: str,
        field: str,
        amount: int = 1,
    ) -> None: ...
    def _probe_item(
        self,
        server: Dict[str, Any],
        item_id: str,
        item_name: str,
        media_source_id: str | None = None,
    ) -> bool: ...
    def _verify_probe_metadata(
        self,
        server: Dict[str, Any],
        item_id: str,
        media_source_id: str | None = None,
        max_retries: int = 2,
    ) -> tuple[bool, str | None]: ...
    def _get_retry_count(self, blacklist: dict, item_id: str, media_source_id: str | None = None) -> int: ...

    def start_recent_discovery(self, server: Dict[str, Any], server_id: str, limit: int = 200) -> bool: ...
    def start_recent_discovery_sequence(self, servers: list[Dict[str, Any]], limit: int = 200) -> bool: ...
    def start_recent_processing(self, server: Dict[str, Any], server_id: str, mode: str = "smart") -> bool: ...
    def start_recent_processing_sequence(self, servers: list[Dict[str, Any]], mode: str = "smart") -> bool: ...
    def stop_recent_discovery(self, server_id: str) -> bool: ...
    def stop_recent_processing(self, server_id: str) -> bool: ...

    def start_discovery(
        self,
        server: Dict[str, Any],
        server_id: str,
        target_libraries: Optional[list[str]] = None,
    ) -> bool: ...
    def start_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        target_libraries: Optional[list[str]] = None,
    ) -> bool: ...
    def stop_discovery(self, server_id: str) -> bool: ...
    def stop_processing(self, server_id: str) -> bool: ...
