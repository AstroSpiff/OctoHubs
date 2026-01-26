"""Emby Probe Manager - Background worker for analyzing and repairing .strm files."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

import requests

from api_clients import _call_emby_api, _fetch_emby_active_sessions, _fetch_emby_libraries

PROBE_SCOPE_LIBRARIES = "libraries"
PROBE_SCOPE_RECENT = "recent"
RECENT_STOP_STREAK = 200
RECENT_MAX_AGE_DAYS = 60


def _parse_emby_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_int_range(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < min_value:
        return min_value
    if number > max_value:
        return max_value
    return number


def _coerce_threshold(value: Any, default: float) -> float:
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
    if threshold < 0.5:
        return 0.5
    if threshold > 1:
        return 1.0
    return threshold


def _extract_source_label(path: str | None, source_name: str | None) -> str:
    if source_name:
        return str(source_name).strip()
    if path:
        base = os.path.basename(path)
        if base.lower().endswith(".strm"):
            base = base[:-5]
        return base.strip()
    return ""


def _strip_wrapping_parens(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
        return cleaned[1:-1].strip()
    return cleaned


def _strip_leading_year(value: str, year: int | None) -> str:
    if not year or not value:
        return value
    cleaned = value.strip()
    year_str = str(year)
    while True:
        candidate = cleaned.strip()
        removed = False
        for prefix in (f"({year_str})", f"[{year_str}]", year_str):
            if candidate.startswith(prefix):
                cleaned = candidate[len(prefix):].lstrip()
                cleaned = cleaned.lstrip("-:").lstrip()
                removed = True
                break
        if not removed:
            break
    return cleaned


def _normalize_movie_display_name(name: str, year: int) -> str:
    year_tag = f"({year})"
    if year_tag not in name:
        return name
    prefix, _, remainder = name.partition(year_tag)
    title = prefix.strip()
    rest = remainder.strip()
    if rest.startswith("-"):
        rest = rest[1:].strip()
    rest = _strip_leading_year(rest, year)
    rest = _strip_wrapping_parens(rest)
    rest = _strip_leading_year(rest, year)
    if rest:
        return f"{title} {year_tag} - {rest}".strip()
    return f"{title} {year_tag}".strip()


def _movie_label_from_path(path: str | None, year: int | None) -> str | None:
    if not path:
        return None
    source_label = _extract_source_label(path, None)
    if not source_label or not year:
        return None
    year_tag = f"({year})"
    if f"{year_tag} -" in source_label:
        return _normalize_movie_display_name(source_label, year)
    return None


def _inject_year_into_series_name(name: str, series_name: str, year: int) -> str:
    if not name or not series_name:
        return name
    year_tag = f"({year})"
    if not name.lower().startswith(series_name.lower()):
        return name
    remainder = name[len(series_name):].lstrip()
    if remainder.startswith(year_tag):
        return name
    if remainder.startswith("-"):
        remainder = remainder[1:].lstrip()
        return f"{series_name} {year_tag} - {remainder}"
    if remainder:
        return f"{series_name} {year_tag} {remainder}"
    return f"{series_name} {year_tag}"


def _format_movie_name(title: str, year: int | None, source_label: str) -> str:
    base_title = title or "Titolo"
    if year:
        year_tag = f"({year})"
        if year_tag.lower() not in base_title.lower():
            base_title = f"{base_title} {year_tag}"
    info = ""
    if source_label:
        normalized = source_label.strip()
        if base_title and normalized.lower().startswith(base_title.lower()):
            remainder = normalized[len(base_title):].strip()
            if remainder.startswith("-"):
                remainder = remainder[1:].strip()
            info = remainder
        else:
            title_only = title or ""
            if title_only and normalized.lower().startswith(title_only.lower()):
                remainder = normalized[len(title_only):].strip()
                year_tag = f"({year})" if year else ""
                if year_tag and remainder.startswith(year_tag):
                    remainder = remainder[len(year_tag):].strip()
                if remainder.startswith("-"):
                    remainder = remainder[1:].strip()
                info = remainder
            elif " - " in normalized and title_only and title_only.lower() in normalized.lower():
                parts = [part.strip() for part in normalized.split(" - ") if part.strip()]
                if parts and title_only.lower() in parts[0].lower():
                    info = " - ".join(parts[1:])
    if info:
        info = _strip_wrapping_parens(info)
        info = _strip_leading_year(info, year)
    return f"{base_title} - {info}".strip(" -") if info else base_title


def _format_episode_name(
    series_name: str | None,
    season_number: int | None,
    episode_number: int | None,
    episode_title: str | None,
    source_label: str,
    year: int | None
) -> str:
    code = ""
    if season_number is not None and episode_number is not None:
        code = f"S{int(season_number):02d}E{int(episode_number):02d}"
    series_label = series_name
    if series_label and year:
        year_tag = f"({year})"
        if year_tag.lower() not in series_label.lower():
            series_label = f"{series_label} {year_tag}"
    info = ""
    if source_label:
        normalized = source_label.strip()
        match = re.search(r"S\d{1,2}E\d{1,2}", normalized, re.IGNORECASE)
        if match:
            remainder = normalized[match.end():].strip(" -")
            if episode_title and remainder.lower().startswith(str(episode_title).lower()):
                remainder = remainder[len(str(episode_title)):].strip(" -")
            info = remainder
        elif series_name and normalized.lower().startswith(series_name.lower()):
            remainder = normalized[len(series_name):].strip(" -")
            if year:
                year_tag = f"({year})"
                if remainder.startswith(year_tag):
                    remainder = remainder[len(year_tag):].strip(" -")
            if code and remainder.upper().startswith(code.upper()):
                remainder = remainder[len(code):].strip(" -")
            if episode_title and remainder.lower().startswith(str(episode_title).lower()):
                remainder = remainder[len(str(episode_title)):].strip(" -")
            info = remainder

    parts = [part for part in [series_label, code, episode_title] if part]
    label = " - ".join(parts)
    if info:
        info = _strip_wrapping_parens(info)
        if info:
            label = f"{label} - {info}" if label else info
    return label or (episode_title or "Episodio")


def _format_probe_display_name(
    media_type: str | None,
    item_name: str,
    year: int | None,
    series_name: str | None,
    season_number: int | None,
    episode_number: int | None,
    path: str | None,
    source_name: str | None
) -> str:
    source_label = _extract_source_label(path, source_name)
    media_kind = (media_type or "").lower()
    if series_name or media_kind == "episode":
        return _format_episode_name(series_name, season_number, episode_number, item_name, source_label, year)
    return _format_movie_name(item_name, year, source_label)


def _format_display_name_from_queue(queue_item: Dict[str, Any]) -> str:
    name = queue_item.get("name") or ""
    media_type = queue_item.get("media_type")
    series_name = queue_item.get("series_name")
    season_number = queue_item.get("season_number")
    episode_number = queue_item.get("episode_number")
    year = queue_item.get("year")
    path = queue_item.get("path")
    media_kind = str(media_type or "").lower()

    if media_kind == "movie":
        movie_from_path = _movie_label_from_path(path, year)
        if movie_from_path:
            return movie_from_path

    if series_name and year:
        name_with_year = _inject_year_into_series_name(name, series_name, year)
        if name_with_year != name:
            return name_with_year
    if series_name and season_number is not None and episode_number is not None:
        code = f"S{int(season_number):02d}E{int(episode_number):02d}"
        expected_prefix = f"{series_name} - {code}".lower()
        if year:
            expected_prefix = f"{series_name} ({year}) - {code}".lower()
        if name.lower().startswith(expected_prefix):
            return name
    if year and f"({year})" in name:
        if media_kind == "movie" and path:
            year_tag = f"({year})"
            if f"{year_tag} -" not in name:
                computed = _format_probe_display_name(
                    media_type,
                    name,
                    year,
                    series_name,
                    season_number,
                    episode_number,
                    path,
                    None
                )
                if computed != name:
                    return computed
        if " - " in name:
            return _normalize_movie_display_name(name, year)
    return _format_probe_display_name(
        media_type,
        name,
        year,
        series_name,
        season_number,
        episode_number,
        path,
        None
    )


class EmbyProbeManager:
    """Manages background workers for discovering and processing .strm files on Emby servers."""

    def __init__(self):
        self._workers: Dict[str, Dict[str, threading.Thread]] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._stop_flags: Dict[str, Dict[str, threading.Event]] = {}
        self._global_workers: Dict[str, threading.Thread] = {}
        self._global_stop_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._db_getter: Optional[Callable[[], Any]] = None

    def configure(self, db_getter: Callable[[], Any]) -> None:
        """Configure the database getter function."""
        self._db_getter = db_getter

    def start_discovery(self, server: Dict[str, Any], server_id: str, target_libraries: Optional[list[str]] = None) -> bool:
        """
        Start a discovery worker to find .strm files that need probing.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            target_libraries: Optional list of library IDs to scan (None = all libraries)

        Returns:
            True if worker started successfully, False if already running
        """
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "discovery" in self._workers[server_id] and self._workers[server_id]["discovery"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["discovery"] = stop_flag

            self._status[server_id]["discovery"] = {
                "running": True,
                "found": 0,
                "total_scanned": 0,
                "current_library_id": None,
                "current_library_name": None,
                "library_totals": {},
                "library_scanned": {},
                "completed_library_ids": [],
                "error_library_ids": [],
                "target_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                "last_log": "Avvio discovery...",
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["discovery"]
                )
                self._status[server_id][combo_key] = {
                    "running": False,
                    "phase": "discovery",
                    "last_log": "Avvio discovery...",
                    "mode": "discovery",
                    "scope": PROBE_SCOPE_LIBRARIES,
                    "queue": combo_queue,
                    "board_reset": False,
                    "board_mode": "discovery",
                    "board_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat()
                }

            worker = threading.Thread(
                target=self._discovery_worker,
                args=(server, server_id, stop_flag, target_libraries),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["discovery"] = worker

        return True

    def start_recent_discovery(
        self,
        server: Dict[str, Any],
        server_id: str,
        limit: int = 200
    ) -> bool:
        """
        Start a discovery worker for recent items missing mediainfo.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            limit: Max number of recent items to scan
        """
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "recent_discovery" in self._workers[server_id] and self._workers[server_id]["recent_discovery"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["recent_discovery"] = stop_flag

            self._status[server_id]["recent_discovery"] = {
                "running": True,
                "found": 0,
                "total_scanned": 0,
                "last_log": "Avvio discovery ultimi aggiunti...",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "limit": limit
            }

            worker = threading.Thread(
                target=self._recent_discovery_worker,
                args=(server, server_id, stop_flag, limit),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["recent_discovery"] = worker

        return True

    def start_recent_discovery_sequence(
        self,
        servers: list[Dict[str, Any]],
        limit: int = 200
    ) -> bool:
        with self._lock:
            worker = self._global_workers.get("recent_discovery_all")
            if worker and worker.is_alive():
                return False
            stop_flag = threading.Event()
            self._global_stop_flags["recent_discovery_all"] = stop_flag
            sequence = threading.Thread(
                target=self._recent_discovery_sequence_worker,
                args=(servers, stop_flag, limit),
                daemon=True
            )
            self._global_workers["recent_discovery_all"] = sequence
            sequence.start()
        return True

    def start_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        target_libraries: Optional[list[str]] = None
    ) -> bool:
        """
        Start a processing worker to probe files from the queue.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            mode: "smart" (pause when server is busy) or "forced" (always run)
            target_libraries: Optional list of library IDs to process (None = all libraries)

        Returns:
            True if worker started successfully, False if already running
        """
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "processing" in self._workers[server_id] and self._workers[server_id]["processing"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["processing"] = stop_flag

            self._status[server_id]["processing"] = {
                "running": True,
                "processed": 0,
                "errors": 0,
                "incomplete": 0,
                "processed_retry": 0,
                "errors_retry": 0,
                "incomplete_retry": 0,
                "total": 0,
                "current_item": None,
                "current_library_id": None,
                "current_library_name": None,
                "library_queue_totals": {},
                "library_queue_results": {},
                "target_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                "last_log": f"Avvio processing in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
            combo_status = self._status[server_id].get(combo_key, {})
            if not combo_status.get("running"):
                previous_last_run = combo_status.get("last_run")
                combo_queue = self._build_combo_queue(
                    [server],
                    PROBE_SCOPE_LIBRARIES,
                    library_ids=target_libraries,
                    task_types=["processing"]
                )
                self._status[server_id][combo_key] = {
                    "running": False,
                    "phase": "processing",
                    "last_log": f"Avvio processing in modalità {mode}...",
                    "mode": mode,
                    "scope": PROBE_SCOPE_LIBRARIES,
                    "queue": combo_queue,
                    "board_reset": False,
                    "board_mode": "processing",
                    "board_library_ids": [str(lib_id) for lib_id in (target_libraries or []) if lib_id],
                    "last_run": previous_last_run,
                    "started_at": datetime.now(timezone.utc).isoformat()
                }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, target_libraries, PROBE_SCOPE_LIBRARIES, "processing"),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["processing"] = worker

        return True

    def start_recent_processing(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart"
    ) -> bool:
        """Start a processing worker for recent discovery items."""
        with self._lock:
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            if "recent_processing" in self._workers[server_id] and self._workers[server_id]["recent_processing"].is_alive():
                return False

            stop_flag = threading.Event()
            self._stop_flags[server_id]["recent_processing"] = stop_flag

            self._status[server_id]["recent_processing"] = {
                "running": True,
                "processed": 0,
                "errors": 0,
                "incomplete": 0,
                "processed_retry": 0,
                "errors_retry": 0,
                "incomplete_retry": 0,
                "total": 0,
                "current_item": None,
                "last_log": f"Avvio processing recenti in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, None, PROBE_SCOPE_RECENT, "recent_processing"),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["recent_processing"] = worker

        return True

    def start_recent_processing_sequence(
        self,
        servers: list[Dict[str, Any]],
        mode: str = "smart"
    ) -> bool:
        with self._lock:
            worker = self._global_workers.get("recent_processing_all")
            if worker and worker.is_alive():
                return False
            stop_flag = threading.Event()
            self._global_stop_flags["recent_processing_all"] = stop_flag
            sequence = threading.Thread(
                target=self._recent_processing_sequence_worker,
                args=(servers, stop_flag, mode),
                daemon=True
            )
            self._global_workers["recent_processing_all"] = sequence
            sequence.start()
        return True

    def stop_discovery(self, server_id: str) -> bool:
        """Stop the discovery worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "discovery" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["discovery"].set()
        return True

    def stop_recent_discovery(self, server_id: str) -> bool:
        """Stop the recent discovery worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "recent_discovery" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["recent_discovery"].set()
        return True

    def stop_recent_discovery_sequence(self) -> bool:
        with self._lock:
            stop_flag = self._global_stop_flags.get("recent_discovery_all")
            if not stop_flag:
                return False
            stop_flag.set()
        return True

    def stop_processing(self, server_id: str) -> bool:
        """Stop the processing worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "processing" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["processing"].set()
        return True

    def stop_recent_processing(self, server_id: str) -> bool:
        """Stop the recent processing worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "recent_processing" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["recent_processing"].set()
        return True

    def stop_recent_processing_sequence(self) -> bool:
        with self._lock:
            stop_flag = self._global_stop_flags.get("recent_processing_all")
            if not stop_flag:
                return False
            stop_flag.set()
        return True

    def start_combo_workflow(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str = "smart",
        scope: str = PROBE_SCOPE_RECENT,
        target_libraries: Optional[list[str]] = None
    ) -> bool:
        """
        Start combo workflow: Discovery → Processing (single server).

        Args:
            server: Server configuration dict
            server_id: Unique server identifier
            mode: "smart" or "forced"
            scope: PROBE_SCOPE_RECENT or PROBE_SCOPE_LIBRARIES
            target_libraries: Optional list of library IDs (for libraries scope only)
        """
        with self._lock:
            worker_key = f"combo_{scope}"
            if server_id not in self._workers:
                self._workers[server_id] = {}
                self._status[server_id] = {}
                self._stop_flags[server_id] = {}

            # Verifica se c'è già un worker attivo
            existing_worker = self._workers[server_id].get(worker_key)
            if existing_worker and existing_worker.is_alive():
                print(f"[COMBO] Server {server_id}: worker {worker_key} già attivo, impossibile avviare")
                return False
            elif existing_worker:
                print(f"[COMBO] Server {server_id}: worker {worker_key} presente ma non attivo (thread morto)")
            else:
                print(f"[COMBO] Server {server_id}: nessun worker {worker_key} esistente, procedo con avvio")

            stop_flag = threading.Event()
            self._stop_flags[server_id][worker_key] = stop_flag

            combo_queue = self._build_combo_queue(
                [server],
                scope,
                library_ids=target_libraries if scope == PROBE_SCOPE_LIBRARIES else None
            )
            previous_last_run = self._status.get(server_id, {}).get(worker_key, {}).get("last_run")
            self._status[server_id][worker_key] = {
                "running": True,
                "phase": "discovery",
                "last_log": "Fase 1/2: Avvio Discovery...",
                "mode": mode,
                "scope": scope,
                "queue": combo_queue,
                "board_reset": False,
                "board_mode": "combo",
                "board_library_ids": [str(lib_id) for lib_id in (target_libraries or [])],
                "last_run": previous_last_run,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            worker = threading.Thread(
                target=self._combo_workflow_worker,
                args=(server, server_id, mode, scope, target_libraries, stop_flag),
                daemon=True
            )
            worker.start()
            self._workers[server_id][worker_key] = worker

        return True

    def start_combo_workflow_all_servers(
        self,
        servers: list[Dict[str, Any]],
        mode: str = "smart",
        scope: str = PROBE_SCOPE_RECENT
    ) -> bool:
        """
        Start combo workflow for all servers.

        Args:
            servers: List of server configuration dicts
            mode: "smart" or "forced"
            scope: PROBE_SCOPE_RECENT (libraries scope not supported for all servers)
        """
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        print(f"[COMBO_ALL] Avvio combo workflow per {len(enabled_servers)} server(s), scope={scope}, mode={mode}")
        if scope == PROBE_SCOPE_RECENT:
            any_started = False
            for idx, server in enumerate(enabled_servers, 1):
                server_id = server.get("id")
                if not server_id:
                    print(f"[COMBO_ALL] Server {idx}: ✗ ID mancante, skip")
                    continue
                server_name = server.get("name") or server.get("url") or server_id
                print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): tentativo avvio combo workflow...")
                started = self.start_combo_workflow(server, server_id, mode, scope=scope)
                if started:
                    print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): ✓ combo workflow avviato")
                    any_started = True
                else:
                    print(f"[COMBO_ALL] Server {idx}/{len(enabled_servers)} ({server_name}): ✗ combo workflow NON avviato (worker già attivo?)")
            print(f"[COMBO_ALL] Risultato finale: any_started={any_started}")
            return any_started

        with self._lock:
            worker_key = f"combo_all_{scope}"
            worker = self._global_workers.get(worker_key)
            if worker and worker.is_alive():
                return False

            stop_flag = threading.Event()
            self._global_stop_flags[worker_key] = stop_flag

            sequence = threading.Thread(
                target=self._combo_workflow_all_servers_worker,
                args=(servers, mode, scope, stop_flag),
                daemon=True
            )
            self._global_workers[worker_key] = sequence
            sequence.start()

        return True

    def stop_combo_workflow(self, server_id: str, scope: str = PROBE_SCOPE_RECENT) -> bool:
        """Stop combo workflow for a specific server."""
        with self._lock:
            worker_key = f"combo_{scope}"
            if server_id not in self._stop_flags or worker_key not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id][worker_key].set()
        return True

    def stop_combo_workflow_all_servers(self, scope: str = PROBE_SCOPE_RECENT) -> bool:
        """Stop combo workflow for all servers."""
        with self._lock:
            worker_key = f"combo_all_{scope}"
            stopped_any = False
            stop_flag = self._global_stop_flags.get(worker_key)
            if stop_flag:
                stop_flag.set()
                stopped_any = True
            for server_flags in self._stop_flags.values():
                combo_flag = server_flags.get(f"combo_{scope}")
                if combo_flag:
                    combo_flag.set()
                    stopped_any = True
        return stopped_any

    def _build_combo_queue(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None
    ) -> list[Dict[str, Any]]:
        queue: list[Dict[str, Any]] = []
        normalized_library_ids = [str(lib_id) for lib_id in (library_ids or []) if lib_id]
        normalized_task_types = task_types or ["discovery", "processing"]
        if scope == PROBE_SCOPE_LIBRARIES and normalized_library_ids:
            for task_type in normalized_task_types:
                for server in servers:
                    if not isinstance(server, dict):
                        continue
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    server_name = (
                        server.get("name")
                        or server.get("alias")
                        or server.get("original_name")
                        or server.get("url")
                        or server_id
                    )
                    for library_id in normalized_library_ids:
                        queue.append({
                            "id": f"{scope}:{task_type}:{server_id}:{library_id}",
                            "type": task_type,
                            "server_id": server_id,
                            "server_name": str(server_name),
                            "library_id": library_id
                        })
            return queue
        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = (
                server.get("name")
                or server.get("alias")
                or server.get("original_name")
                or server.get("url")
                or server_id
            )
            queue.append({
                "id": f"{scope}:discovery:{server_id}",
                "type": "discovery",
                "server_id": server_id,
                "server_name": str(server_name)
            })
        for server in servers:
            if not isinstance(server, dict):
                continue
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = (
                server.get("name")
                or server.get("alias")
                or server.get("original_name")
                or server.get("url")
                or server_id
            )
            queue.append({
                "id": f"{scope}:processing:{server_id}",
                "type": "processing",
                "server_id": server_id,
                "server_name": str(server_name)
            })
        return queue

    def _evaluate_combo_task_result(
        self,
        server_id: str,
        scope: str,
        task_type: str,
        library_id: Optional[str] = None
    ) -> tuple[str, str]:
        status_key = task_type
        if scope == PROBE_SCOPE_RECENT:
            status_key = "recent_discovery" if task_type == "discovery" else "recent_processing"
        else:
            status_key = "discovery" if task_type == "discovery" else "processing"
        status = self._status.get(server_id, {}).get(status_key, {}) if server_id else {}
        last_log = str(status.get("last_log") or "")
        lower_log = last_log.lower()

        if library_id is None:
            if "interrotto" in lower_log:
                return "warning", last_log or "Interrotto dall'utente"

            if "errore" in lower_log:
                return "error", last_log or "Errore"

        if task_type == "processing":
            if library_id:
                totals = status.get("library_queue_totals") if isinstance(status.get("library_queue_totals"), dict) else {}
                results = status.get("library_queue_results") if isinstance(status.get("library_queue_results"), dict) else {}
                key = str(library_id)
                total = int(totals.get(key, 0) if totals else 0)
                library_result_value = results.get(str(library_id)) if results else None
                library_result = library_result_value if isinstance(library_result_value, dict) else {}
                errors = int(library_result.get("errors", 0) if library_result else 0)
                incomplete = int(library_result.get("incomplete", 0) if library_result else 0)
                processed = int(library_result.get("processed", 0) if library_result else 0)
                done = processed + incomplete + errors
                if totals and key in totals and total == 0:
                    return "skipped", "Processing non necessario"
                if errors > 0:
                    return "error", f"Errori: {errors}"
                if incomplete > 0:
                    return "warning", f"Incompleti: {incomplete}"
                if done >= total:
                    return "success", "Completato"
                return "warning", "Interrotto"

            errors = int(status.get("errors") or 0) + int(status.get("errors_retry") or 0)
            incomplete = int(status.get("incomplete") or 0) + int(status.get("incomplete_retry") or 0)
            processed = int(status.get("processed") or 0) + int(status.get("processed_retry") or 0)

            if "coda vuota" in lower_log or "nessun file da processare" in lower_log:
                return "skipped", "Processing non necessario"
            if "nessun file processabile" in lower_log:
                return "error", last_log or "Nessun file processabile"
            if errors > 0:
                return "error", f"Errori: {errors}"
            if incomplete > 0:
                return "warning", f"Incompleti: {incomplete}"
            if processed > 0 or "completato" in lower_log:
                return "success", last_log or "Completato"
            return "success", last_log or "Completato"

        if library_id:
            completed_value = status.get("completed_library_ids")
            completed = completed_value if isinstance(completed_value, list) else []
            errors_value = status.get("error_library_ids")
            errors = errors_value if isinstance(errors_value, list) else []
            if errors and str(library_id) in errors:
                return "error", "Errore in libreria"
            if completed and str(library_id) in completed:
                return "success", "Completato"
            if "interrotto" in lower_log:
                return "warning", last_log or "Interrotto"
            return "warning", "Interrotto"

        if "fermato" in lower_log:
            return "warning", last_log or "Fermato in anticipo"
        if "completata" in lower_log or "completato" in lower_log or "scansionati" in lower_log:
            return "success", last_log or "Completato"
        return "success", last_log or "Completato"

    def _build_combo_last_run(
        self,
        servers: list[Dict[str, Any]],
        scope: str,
        interrupted: bool,
        library_ids: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None
    ) -> Dict[str, Any]:
        tasks = []
        queue = self._build_combo_queue(servers, scope, library_ids=library_ids, task_types=task_types)
        for entry in queue:
            server_id = entry.get("server_id")
            task_type = entry.get("type")
            if not server_id or task_type not in ("discovery", "processing"):
                continue
            result, note = self._evaluate_combo_task_result(
                server_id,
                scope,
                task_type,
                library_id=entry.get("library_id")
            )
            task_entry = dict(entry)
            task_entry["result"] = result
            task_entry["note"] = note
            tasks.append(task_entry)
        return {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "interrupted" if interrupted else "completed",
            "tasks": tasks
        }

    def get_status(self, server_id: str) -> Dict[str, Any]:
        """Get the status of both discovery and processing workers for a server."""
        with self._lock:
            return self._status.get(server_id, {})

    def _combo_workflow_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        scope: str,
        target_libraries: Optional[list[str]],
        stop_flag: threading.Event
        ) -> None:
        """Orchestrate Discovery → Processing for a single server."""
        try:
            worker_key = f"combo_{scope}"

            # Phase 1: Discovery
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["phase"] = "discovery"
                    self._status[server_id][worker_key]["last_log"] = "Fase 1/2: Discovery in corso..."

            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_discovery(server, server_id)
                discovery_worker = self._workers.get(server_id, {}).get("recent_discovery")
            else:
                self.start_discovery(server, server_id, target_libraries)
                discovery_worker = self._workers.get(server_id, {}).get("discovery")

            # Wait for discovery to complete
            self._wait_for_worker(discovery_worker, stop_flag)

            if stop_flag.is_set():
                with self._lock:
                    if server_id in self._status and worker_key in self._status[server_id]:
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow interrotto dall'utente"
                        self._status[server_id][worker_key]["running"] = False
                return

            # Phase 2: Processing
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["phase"] = "processing"
                    self._status[server_id][worker_key]["last_log"] = "Fase 2/2: Processing in corso..."

            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_processing(server, server_id, mode)
                processing_worker = self._workers.get(server_id, {}).get("recent_processing")
            else:
                self.start_processing(server, server_id, mode, target_libraries)
                processing_worker = self._workers.get(server_id, {}).get("processing")

            # Wait for processing to complete
            self._wait_for_worker(processing_worker, stop_flag)

            # Final status
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    if stop_flag.is_set():
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow interrotto dall'utente"
                    else:
                        self._status[server_id][worker_key]["last_log"] = "Combo workflow completato"
                    self._status[server_id][worker_key]["running"] = False

        except Exception as exc:
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    self._status[server_id][worker_key]["last_log"] = f"Errore critico: {exc}"
                    self._status[server_id][worker_key]["running"] = False
        finally:
            worker_key = f"combo_{scope}"
            interrupted = stop_flag.is_set()
            with self._lock:
                if server_id in self._status and worker_key in self._status[server_id]:
                    library_ids = target_libraries if scope == PROBE_SCOPE_LIBRARIES else None
                    self._status[server_id][worker_key]["last_run"] = self._build_combo_last_run(
                        [server],
                        scope,
                        interrupted,
                        library_ids=library_ids
                    )
                    self._status[server_id][worker_key]["board_reset"] = True

    def _combo_workflow_all_servers_worker(
        self,
        servers: list[Dict[str, Any]],
        mode: str,
        scope: str,
        stop_flag: threading.Event
    ) -> None:
        """Orchestrate Discovery (all servers sequential) → Processing (all servers sequential)."""
        try:
            enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
            total_servers = len(enabled_servers)
            worker_key = f"combo_{scope}"
            combo_queue = self._build_combo_queue(enabled_servers, scope)

            # Initialize combo status for all servers
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id:
                    with self._lock:
                        if srv_id not in self._workers:
                            self._workers[srv_id] = {}
                        if srv_id not in self._status:
                            self._status[srv_id] = {}
                        if srv_id not in self._stop_flags:
                            self._stop_flags[srv_id] = {}

                        previous_last_run = self._status.get(srv_id, {}).get(worker_key, {}).get("last_run")
                        self._status[srv_id][worker_key] = {
                            "running": True,
                            "phase": "discovery",
                            "last_log": "Avvio combo workflow...",
                            "mode": mode,
                            "scope": scope,
                            "queue": [dict(entry) for entry in combo_queue],
                            "board_reset": False,
                            "last_run": previous_last_run,
                            "started_at": datetime.now(timezone.utc).isoformat()
                        }

            # Phase 1: Discovery on all servers (sequential)
            for index, server in enumerate(enabled_servers, 1):
                if stop_flag.is_set():
                    break
                server_id = server.get("id")
                if not server_id:
                    continue
                server_name = server.get("name") or server.get("url") or server_id

                # Update all server combo statuses
                for srv in enabled_servers:
                    srv_id = srv.get("id")
                    if srv_id and srv_id in self._status:
                        worker_key = f"combo_{scope}"
                        with self._lock:
                            if worker_key in self._status[srv_id]:
                                self._status[srv_id][worker_key]["last_log"] = (
                                    f"Fase 1/2: Discovery [{index}/{total_servers}] su {server_name}"
                                )

                if scope == PROBE_SCOPE_RECENT:
                    self.start_recent_discovery(server, server_id)
                    worker = self._workers.get(server_id, {}).get("recent_discovery")
                else:
                    self.start_discovery(server, server_id)
                    worker = self._workers.get(server_id, {}).get("discovery")

                self._wait_for_worker(worker, stop_flag)

                if stop_flag.is_set():
                    if scope == PROBE_SCOPE_RECENT:
                        self.stop_recent_discovery(server_id)
                    else:
                        self.stop_discovery(server_id)
                    break

            if stop_flag.is_set():
                return

            # Update combo status: starting Phase 2
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    worker_key = f"combo_{scope}"
                    with self._lock:
                        if worker_key in self._status[srv_id]:
                            self._status[srv_id][worker_key]["phase"] = "processing"
                            self._status[srv_id][worker_key]["last_log"] = "Fase 2/2: Avvio Processing su tutti i server..."

            # Phase 2: Processing on all servers (sequential or smart)
            if scope == PROBE_SCOPE_RECENT:
                self.start_recent_processing_sequence(servers, mode)
                worker = self._global_workers.get("recent_processing_all")
            else:
                # For libraries scope, process each server sequentially
                for index, server in enumerate(enabled_servers, 1):
                    if stop_flag.is_set():
                        break
                    server_id = server.get("id")
                    if not server_id:
                        continue
                    server_name = server.get("name") or server.get("url") or server_id

                    # Update all server combo statuses
                    for srv in enabled_servers:
                        srv_id = srv.get("id")
                        if srv_id and srv_id in self._status:
                            worker_key = f"combo_{scope}"
                            with self._lock:
                                if worker_key in self._status[srv_id]:
                                    self._status[srv_id][worker_key]["last_log"] = (
                                        f"Fase 2/2: Processing [{index}/{total_servers}] su {server_name}"
                                    )

                    self.start_processing(server, server_id, mode)
                    worker = self._workers.get(server_id, {}).get("processing")
                    self._wait_for_worker(worker, stop_flag)

                    if stop_flag.is_set():
                        self.stop_processing(server_id)
                        break
                return  # No global worker to wait for in libraries scope

            # Wait for global processing worker to complete (recent scope only)
            self._wait_for_worker(worker, stop_flag)

        except Exception as exc:
            # Errors are logged by individual workers
            pass
        finally:
            # Mark combo workflow as completed for all servers
            worker_key = f"combo_{scope}"
            last_run = self._build_combo_last_run(enabled_servers, scope, stop_flag.is_set())
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    with self._lock:
                        if worker_key in self._status[srv_id]:
                            if stop_flag.is_set():
                                self._status[srv_id][worker_key]["last_log"] = "Combo workflow interrotto dall'utente"
                            else:
                                self._status[srv_id][worker_key]["last_log"] = "Combo workflow completato"
                            self._status[srv_id][worker_key]["running"] = False
                            self._status[srv_id][worker_key]["last_run"] = last_run
                            self._status[srv_id][worker_key]["board_reset"] = True

    def _wait_for_worker(self, worker: Optional[threading.Thread], stop_flag: threading.Event) -> None:
        while worker and worker.is_alive():
            if stop_flag.is_set():
                break
            time.sleep(1)

    def _recent_discovery_sequence_worker(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        limit: int
    ) -> None:
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        total_servers = len(enabled_servers)

        for index, server in enumerate(enabled_servers, 1):
            if stop_flag.is_set():
                break
            server_id = server.get("id")
            if not server_id:
                continue
            server_name = server.get("name") or server.get("url") or server_id

            # Update all server statuses with current progress
            for srv in enabled_servers:
                srv_id = srv.get("id")
                if srv_id and srv_id in self._status:
                    with self._lock:
                        if "recent_discovery" in self._status[srv_id]:
                            self._status[srv_id]["recent_discovery"]["last_log"] = (
                                f"[{index}/{total_servers}] Discovery su: {server_name}"
                            )

            self.start_recent_discovery(server, server_id, limit)
            worker = self._workers.get(server_id, {}).get("recent_discovery")
            self._wait_for_worker(worker, stop_flag)
            if stop_flag.is_set():
                self.stop_recent_discovery(server_id)
                break

    def _recent_processing_sequence_worker(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        mode: str
    ) -> None:
        if mode == "smart":
            # Smart mode: round-robin processing, skip servers with active streams
            self._smart_processing_all_servers(servers, stop_flag, "recent")
        else:
            # Forced mode: sequential processing
            enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
            total_servers = len(enabled_servers)

            for index, server in enumerate(enabled_servers, 1):
                if stop_flag.is_set():
                    break
                server_id = server.get("id")
                if not server_id:
                    continue
                server_name = server.get("name") or server.get("url") or server_id

                # Update all server statuses with current progress
                for srv in enabled_servers:
                    srv_id = srv.get("id")
                    if srv_id and srv_id in self._status:
                        with self._lock:
                            if "recent_processing" in self._status[srv_id]:
                                self._status[srv_id]["recent_processing"]["last_log"] = (
                                    f"[{index}/{total_servers}] Processing su: {server_name}"
                                )

                self.start_recent_processing(server, server_id, mode)
                worker = self._workers.get(server_id, {}).get("recent_processing")
                self._wait_for_worker(worker, stop_flag)
                if stop_flag.is_set():
                    self.stop_recent_processing(server_id)
                    break

    def _smart_processing_all_servers(
        self,
        servers: list[Dict[str, Any]],
        stop_flag: threading.Event,
        scope: str
    ) -> None:
        """
        Smart processing for all servers with round-robin approach.
        Processes files from servers without active streams, skips busy servers.
        """
        if not self._db_getter:
            return

        db = self._db_getter()
        status_key = "recent_processing" if scope == PROBE_SCOPE_RECENT else "processing"

        # Filter enabled servers
        enabled_servers = [s for s in servers if s and s.get("enabled") and s.get("id")]
        if not enabled_servers:
            return

        # Calculate initial total and filter servers with work
        initial_total = 0
        servers_with_work = []
        for server in enabled_servers:
            server_id = server.get("id")
            if not server_id:
                continue
            queue_items = db.get_probe_queue(server_id, scope=scope)
            blacklist = db.load_probe_blacklist(server_id, scope=scope)
            processable = [
                item for item in queue_items
                if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
            ]
            if len(processable) > 0:
                servers_with_work.append(server)
                initial_total += len(processable)

        # If no servers have work, exit
        if not servers_with_work:
            return

        # Initialize status ONLY for servers with work
        for server in servers_with_work:
            server_id = server.get("id")
            if not server_id:
                continue
            with self._lock:
                if server_id not in self._status:
                    self._status[server_id] = {}
                self._status[server_id][status_key] = {
                    "running": True,
                    "incomplete": 0,
                    "processed": 0,
                    "errors": 0,
                    "processed_retry": 0,
                    "errors_retry": 0,
                    "incomplete_retry": 0,
                    "total": initial_total,  # Set to global total
                    "current_item": None,
                    "last_log": "Modalità Smart multi-server: in attesa...",
                    "mode": "smart",
                    "started_at": datetime.now(timezone.utc).isoformat()
                }

        # Use servers_with_work instead of all enabled_servers
        enabled_servers = servers_with_work

        if not enabled_servers:
            return

        server_index = 0
        consecutive_skips = 0
        max_consecutive_skips = len(enabled_servers) * 2  # Allow 2 full rounds of all servers being busy

        while not stop_flag.is_set():
            # Check if all servers are done (no items in queue)
            total_remaining = 0
            for server in enabled_servers:
                server_id = server.get("id")
                if not server_id:
                    continue
                queue_items = db.get_probe_queue(server_id, scope=scope)
                # Filter out blacklisted items (3+ errors)
                blacklist = db.load_probe_blacklist(server_id, scope=scope)
                processable = [
                    item for item in queue_items
                    if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
                ]
                total_remaining += len(processable)

            if total_remaining == 0:
                # All servers done
                break

            # Get current server
            server = enabled_servers[server_index]
            server_id = server.get("id")
            if not server_id:
                server_index = (server_index + 1) % len(enabled_servers)
                continue

            # Check if server has items to process
            queue_items = db.get_probe_queue(server_id, scope=scope)
            blacklist = db.load_probe_blacklist(server_id, scope=scope)
            processable = [
                item for item in queue_items
                if self._get_retry_count(blacklist, item.get("item_id"), item.get("media_source_id")) < 3
            ]

            if len(processable) == 0:
                # Server has no items, move to next
                server_index = (server_index + 1) % len(enabled_servers)
                continue

            # Check if server has active streams
            server_name = server.get("name") or server.get("url") or server_id
            sessions, error = _fetch_emby_active_sessions(server)
            if not error and sessions:
                # Server is busy, skip to next
                self._update_status(
                    server_id,
                    status_key,
                    last_log=f"[{server_index + 1}/{len(enabled_servers)}] {server_name}: occupato ({len(sessions)} stream), passaggio al successivo..."
                )
                consecutive_skips += 1
                server_index = (server_index + 1) % len(enabled_servers)

                if consecutive_skips >= max_consecutive_skips:
                    # All servers busy for too long, wait a bit
                    for srv in enabled_servers:
                        srv_id = srv.get("id")
                        if srv_id:
                            self._update_status(
                                srv_id,
                                status_key,
                                last_log="Tutti i server occupati, attesa..."
                            )
                    if stop_flag.wait(10):
                        break
                    consecutive_skips = 0
                continue

            # Server is free, process one item
            consecutive_skips = 0
            queue_item = processable[0]

            item_id = queue_item["item_id"]
            item_display_name = _format_display_name_from_queue(queue_item)
            media_source_id = queue_item.get("media_source_id")
            library_name = queue_item.get("library_name")
            library_id = queue_item.get("library_id")

            # Check if this is a retry
            current_retry_count = self._get_retry_count(blacklist, item_id, media_source_id)
            is_retry = current_retry_count > 0

            # Update status
            retry_suffix = f" (retry {current_retry_count})" if is_retry else ""
            self._update_status(
                server_id,
                status_key,
                current_item=item_display_name,
                last_log=f"[{server_index + 1}/{len(enabled_servers)}] {server_name} - Analisi{retry_suffix}: {item_display_name}"
            )

            # Probe the item
            start_time = time.time()
            probe_success = self._probe_item(server, item_id, item_display_name, media_source_id)
            duration_ms = int((time.time() - start_time) * 1000)

            if stop_flag.is_set():
                break

            # Remove from queue
            db.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)

            # Handle result (same logic as _processing_worker)
            status = "ERROR"
            error_details = "Timeout o errore API"

            if probe_success:
                max_attempts = 15
                attempt = 0
                metadata_ok = False
                metadata_error = None
                time.sleep(1)

                while attempt < max_attempts and not stop_flag.is_set():
                    metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)
                    if metadata_ok:
                        break
                    attempt += 1
                    if attempt < max_attempts:
                        time.sleep(1)

                if metadata_ok:
                    status = "SUCCESS"
                    error_details = None
                    db.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
                else:
                    status = "INCOMPLETE"
                    error_details = metadata_error or "Mediainfo non scritto dopo polling"

            if status != "SUCCESS":
                error_type = "INCOMPLETE" if status == "INCOMPLETE" else "ERROR"
                db.update_probe_blacklist(
                    server_id,
                    item_id,
                    item_display_name,
                    error_details or "Errore probe",
                    media_source_id=media_source_id,
                    increment_retry=True,
                    error_type=error_type,
                    scope=scope,
                    library_id=library_id,
                    library_name=library_name
                )

            # Add to history
            db.add_probe_history({
                "server_id": server_id,
                "item_id": item_id,
                "media_source_id": media_source_id,
                "scope": scope,
                "name": item_display_name,
                "library_name": library_name,
                "status": status,
                "error_details": error_details,
                "duration_ms": duration_ms
            })

            # Update counters
            with self._lock:
                if server_id in self._status and status_key in self._status[server_id]:
                    if status == "SUCCESS":
                        if is_retry:
                            self._status[server_id][status_key]["processed_retry"] += 1
                        else:
                            self._status[server_id][status_key]["processed"] += 1
                    elif status == "INCOMPLETE":
                        if is_retry:
                            self._status[server_id][status_key]["incomplete_retry"] += 1
                        else:
                            self._status[server_id][status_key]["incomplete"] += 1
                    else:
                        if is_retry:
                            self._status[server_id][status_key]["errors_retry"] += 1
                        else:
                            self._status[server_id][status_key]["errors"] += 1
                    current_total = self._status[server_id][status_key].get("total") or 0
                    if current_total == 0:
                        self._status[server_id][status_key]["total"] = (
                            self._status[server_id][status_key]["processed"] +
                            self._status[server_id][status_key]["incomplete"] +
                            self._status[server_id][status_key]["errors"]
                        )

            # Rate limiting
            if stop_flag.wait(1):
                break

        # Cleanup: mark all servers as done
        for server in enabled_servers:
            srv_id = server.get("id")
            if not srv_id:
                continue
            with self._lock:
                if srv_id in self._status and status_key in self._status[srv_id]:
                    self._status[srv_id][status_key]["running"] = False
                    if stop_flag.is_set():
                        self._status[srv_id][status_key]["last_log"] = "Interrotto dall'utente"
                    else:
                        self._status[srv_id][status_key]["last_log"] = "Processing completato"
                    self._status[srv_id][status_key]["current_item"] = None

    def _get_retry_count(self, blacklist: dict, item_id: str, media_source_id: str | None = None) -> int:
        """Get retry count from blacklist."""
        key = f"{item_id}:{media_source_id or ''}"
        entry = blacklist.get(key)
        if not entry:
            return 0
        return int(entry.get("retry_count") or 0)

    def _update_status(
        self,
        server_id: str,
        worker_type: str,
        **kwargs
    ) -> None:
        """Update worker status atomically."""
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            if worker_type not in self._status[server_id]:
                self._status[server_id][worker_type] = {}

            for key, value in kwargs.items():
                if key.startswith("increment_"):
                    field = key.replace("increment_", "")
                    amount = value if isinstance(value, int) else 1
                    self._status[server_id][worker_type][field] = self._status[server_id][worker_type].get(field, 0) + amount
                else:
                    self._status[server_id][worker_type][key] = value

    def _set_library_total(self, server_id: str, library_id: str, total_count: int) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            totals = discovery.get("library_totals") or {}
            totals[str(library_id)] = total_count
            discovery["library_totals"] = totals

    def _increment_library_scanned(self, server_id: str, library_id: str, count: int) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            scanned = discovery.get("library_scanned") or {}
            key = str(library_id)
            scanned[key] = int(scanned.get(key) or 0) + int(count or 0)
            discovery["library_scanned"] = scanned

    def _mark_library_completed(self, server_id: str, library_id: str) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            completed = discovery.get("completed_library_ids") or []
            key = str(library_id)
            if key not in completed:
                completed.append(key)
            discovery["completed_library_ids"] = completed

    def _mark_library_error(self, server_id: str, library_id: str) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            discovery = self._status[server_id].setdefault("discovery", {})
            errors = discovery.get("error_library_ids") or []
            key = str(library_id)
            if key not in errors:
                errors.append(key)
            discovery["error_library_ids"] = errors

    def _merge_processing_library_totals(self, server_id: str, status_key: str, totals: Dict[str, int]) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            status = self._status[server_id].setdefault(status_key, {})
            existing = status.get("library_queue_totals") or {}
            for lib_id, total in totals.items():
                current = int(existing.get(lib_id) or 0)
                incoming = int(total or 0)
                existing[lib_id] = max(current, incoming)
            status["library_queue_totals"] = existing

            results = status.get("library_queue_results") or {}
            for lib_id in totals.keys():
                entry = results.get(lib_id)
                if not isinstance(entry, dict):
                    entry = {"processed": 0, "incomplete": 0, "errors": 0}
                results[lib_id] = entry
            status["library_queue_results"] = results

    def _increment_processing_library_result(
        self,
        server_id: str,
        status_key: str,
        library_id: str,
        field: str,
        amount: int = 1
    ) -> None:
        with self._lock:
            if server_id not in self._status:
                self._status[server_id] = {}
            status = self._status[server_id].setdefault(status_key, {})
            results = status.get("library_queue_results") or {}
            key = str(library_id)
            entry = results.get(key)
            if not isinstance(entry, dict):
                entry = {"processed": 0, "incomplete": 0, "errors": 0}
            entry[field] = int(entry.get(field) or 0) + int(amount or 0)
            results[key] = entry
            status["library_queue_results"] = results

    def _discovery_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None
    ) -> None:
        """
        Discovery worker: scans Emby libraries and populates the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, "discovery", last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()

            # Fetch all libraries from Emby
            self._update_status(
                server_id,
                "discovery",
                last_log="Recupero librerie dal server..."
            )

            libraries, error = _fetch_emby_libraries(server)
            if error or not libraries:
                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Errore recupero librerie: {error or 'Nessuna libreria trovata'}"
                )
                return

            # Filter libraries if target_libraries is provided
            if target_libraries:
                libraries = [lib for lib in libraries if lib.get("id") in target_libraries]

            if not libraries:
                self._update_status(
                    server_id,
                    "discovery",
                    last_log="Nessuna libreria da scansionare"
                )
                return

            blacklist: Dict[str, Any] = {}

            def is_blacklisted(item_id: str, media_source_id: str | None = None) -> bool:
                """Check if item is in blacklist with 3+ errors."""
                key = f"{item_id}:{media_source_id or ''}"
                entry = blacklist.get(key)
                if not entry:
                    return False
                return int(entry.get("retry_count") or 0) >= 3

            items_batch = []
            batch_size = 20

            # Iterate through each library
            for library in libraries:
                if stop_flag.is_set():
                    break

                library_id = library.get("id")
                if not library_id:
                    continue
                library_name = library.get("name", "Sconosciuto")
                library_error = False

                self._update_status(
                    server_id,
                    "discovery",
                    current_library_id=str(library_id),
                    current_library_name=library_name
                )

                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Scansione libreria: {library_name}"
                )

                start_index = 0
                page_size = 50

                while not stop_flag.is_set():
                    # Fetch page from Emby API for this library
                    success, payload = _call_emby_api(
                        server,
                        "Items",
                        method="GET",
                        params={
                            "ParentId": library_id,
                            "Recursive": "true",
                            "IncludeItemTypes": "Movie,Episode",
                            "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,Type",
                            "StartIndex": start_index,
                            "Limit": page_size
                        }
                    )

                    if not success or not isinstance(payload, dict):
                        self._update_status(
                            server_id,
                            "discovery",
                            last_log=f"Errore recupero item da {library_name}: {payload}"
                        )
                        library_error = True
                        self._mark_library_error(server_id, str(library_id))
                        break

                    items = payload.get("Items", [])
                    total_count = payload.get("TotalRecordCount", 0)
                    if library_id:
                        self._set_library_total(server_id, library_id, total_count)

                    if not items:
                        break

                    # Refresh blacklist to pick up any changes made during discovery
                    blacklist = db.load_probe_blacklist(server_id, scope=PROBE_SCOPE_LIBRARIES)

                    # Filter items that need probing
                    for item in items:
                        if stop_flag.is_set():
                            break

                        if not isinstance(item, dict):
                            continue

                        item_id = item.get("Id")
                        if not item_id:
                            continue

                        item_path = item.get("Path", "")

                        # Filter: only .strm files
                        if not item_path.lower().endswith(".strm"):
                            continue

                        # Extract metadata
                        item_type = item.get("Type", "")
                        item_name = item.get("Name", "Sconosciuto")
                        series_name = item.get("SeriesName")
                        season_number = item.get("ParentIndexNumber")
                        episode_number = item.get("IndexNumber")
                        # Use SeriesProductionYear if available, otherwise ProductionYear
                        year = item.get("SeriesProductionYear") or item.get("ProductionYear")

                        media_sources = item.get("MediaSources")
                        if not isinstance(media_sources, list) or not media_sources:
                            media_sources = [None]

                        for source in media_sources:
                            if source is None:
                                source_streams = item.get("MediaStreams", [])
                                source_runtime = item.get("RunTimeTicks")
                                source_media_id = None
                                source_name = None
                            elif isinstance(source, dict):
                                source_streams = source.get("MediaStreams", [])
                                source_runtime = source.get("RunTimeTicks")
                                source_media_id = source.get("Id")
                                source_name = source.get("Name")
                            else:
                                continue

                            if source_runtime and source_streams:
                                continue  # Already has metadata

                            # Skip items in blacklist with 3+ errors
                            if is_blacklisted(item_id, source_media_id):
                                continue

                            queue_name = _format_probe_display_name(
                                item_type,
                                item_name,
                                year,
                                series_name,
                                season_number,
                                episode_number,
                                item_path,
                                source_name
                            )

                            items_batch.append({
                                "server_id": server_id,
                                "item_id": item_id,
                                "scope": PROBE_SCOPE_LIBRARIES,
                                "media_source_id": source_media_id,
                                "library_id": library_id,
                                "library_name": library_name,
                                "name": queue_name,
                                "series_name": series_name,
                                "season_number": season_number,
                                "episode_number": episode_number,
                                "year": year,
                                "media_type": item_type,
                                "path": item_path
                            })

                        # Save batch to database
                        if len(items_batch) >= batch_size:
                            db.add_to_probe_queue(items_batch)
                            self._update_status(
                                server_id,
                                "discovery",
                                increment_found=len(items_batch),
                                last_log=f"Aggiunti {len(items_batch)} file alla coda da {library_name}"
                            )
                            items_batch = []

                    # Update progress
                    self._update_status(
                        server_id,
                        "discovery",
                        increment_total_scanned=len(items),
                        last_log=f"Scansionati {start_index + len(items)}/{total_count} item in {library_name}"
                    )
                    self._increment_library_scanned(server_id, str(library_id), len(items))

                    start_index += page_size
                    if start_index >= total_count:
                        break

                if stop_flag.is_set():
                    break
                if not library_error:
                    self._mark_library_completed(server_id, str(library_id))

            # Save remaining batch
            if items_batch and not stop_flag.is_set():
                db.add_to_probe_queue(items_batch)
                self._update_status(
                    server_id,
                    "discovery",
                    increment_found=len(items_batch)
                )

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "discovery",
                    last_log="Discovery interrotta dall'utente"
                )
            else:
                found_count = self._status.get(server_id, {}).get("discovery", {}).get("found", 0)
                self._update_status(
                    server_id,
                    "discovery",
                    last_log=f"Discovery completata. Trovati {found_count} file da analizzare."
                )

        except Exception as exc:
            self._update_status(
                server_id,
                "discovery",
                last_log=f"Errore critico: {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "discovery" in self._status[server_id]:
                    self._status[server_id]["discovery"]["running"] = False
                    self._status[server_id]["discovery"]["current_library_id"] = None
                    self._status[server_id]["discovery"]["current_library_name"] = None
                combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
                combo_status = self._status.get(server_id, {}).get(combo_key, {})
                if combo_status and not combo_status.get("running") and combo_status.get("board_mode") == "discovery":
                    library_ids = self._status.get(server_id, {}).get("discovery", {}).get("target_library_ids") or []
                    self._status[server_id][combo_key]["last_run"] = self._build_combo_last_run(
                        [server],
                        PROBE_SCOPE_LIBRARIES,
                        stop_flag.is_set(),
                        library_ids=library_ids,
                        task_types=["discovery"]
                    )
                    self._status[server_id][combo_key]["board_reset"] = True

    def _recent_discovery_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        stop_flag: threading.Event,
        limit: int = 200
    ) -> None:
        """
        Recent discovery worker: scans latest items and queues missing mediainfo.
        Uses hybrid algorithm: timestamp tracking + sliding window + inverted processing.
        """
        try:
            server_name = server.get("name") or server.get("url") or server_id

            if not self._db_getter:
                self._update_status(server_id, "recent_discovery", last_log=f"{server_name}: Errore - database non configurato", running=False)
                return

            db = self._db_getter()
            page_size = max(20, min(500, int(limit or 200)))

            config = {}
            try:
                config = db.get_recent_scan_config(server_id)
            except Exception:
                config = {}

            WINDOW_SIZE = _coerce_int_range(config.get("window_size"), 500, 100, 2000)
            WINDOW_THRESHOLD = _coerce_threshold(config.get("window_threshold"), 0.90)
            MAX_DAYS = _coerce_int_range(config.get("max_days"), 60, 7, 365)
            MAX_ITEMS = _coerce_int_range(config.get("max_items"), 2000, 500, 10000)
            SAFETY_MARGIN_DAYS = _coerce_int_range(config.get("safety_margin_days"), 7, 1, 30)

            now = datetime.now(timezone.utc)
            max_days_cutoff = now - timedelta(days=MAX_DAYS)

            # Get last scan timestamp with safety margin
            last_timestamp = db.get_recent_scan_timestamp(server_id)
            if last_timestamp:
                cutoff_date = last_timestamp - timedelta(days=SAFETY_MARGIN_DAYS)
                if cutoff_date < max_days_cutoff:
                    cutoff_date = max_days_cutoff
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=(
                        f"{server_name}: Scan incrementale dal {cutoff_date.strftime('%Y-%m-%d')} "
                        f"(margine {SAFETY_MARGIN_DAYS} giorni, max {MAX_DAYS} giorni)..."
                    )
                )
            else:
                cutoff_date = max_days_cutoff
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Primo scan completo (finestra {MAX_DAYS} giorni)..."
                )

            start_index = 0
            total_items_checked = 0
            sliding_window = []  # Track last 500 items with completion status
            oldest_item_date = None

            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Recupero elenco cartelle librerie..."
            )

            folders_success, folders_payload = _call_emby_api(
                server,
                "Library/VirtualFolders",
                method="GET"
            )
            folder_locations = []
            if folders_success and isinstance(folders_payload, list):
                for folder in folders_payload:
                    if not isinstance(folder, dict):
                        continue
                    locations = folder.get("Locations")
                    if not isinstance(locations, list):
                        continue
                    for location in locations:
                        if not location:
                            continue
                        folder_locations.append({
                            "id": folder.get("Id") or folder.get("ItemId"),
                            "name": folder.get("Name"),
                            "path": str(location).replace("\\", "/").rstrip("/").lower()
                        })

            blacklist = db.load_probe_blacklist(server_id, scope=PROBE_SCOPE_RECENT)

            def is_blacklisted(item_id: str, media_source_id: str | None = None) -> bool:
                key = f"{item_id}:{media_source_id or ''}"
                entry = blacklist.get(key)
                if not entry:
                    return False
                return int(entry.get("retry_count") or 0) >= 3

            def resolve_library(item_path: str | None, parent_id: str | None) -> tuple[str | None, str]:
                library_id = None
                library_name = "Libreria"
                if item_path:
                    item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
                    best_match = None
                    best_len = 0
                    for folder in folder_locations:
                        folder_path = folder.get("path") or ""
                        if not folder_path:
                            continue
                        folder_prefix = folder_path + "/"
                        if item_norm.startswith(folder_prefix) and len(folder_prefix) > best_len:
                            best_len = len(folder_prefix)
                            best_match = folder
                    if best_match:
                        library_id = best_match.get("id") or library_id
                        library_name = best_match.get("name") or library_name
                if not library_id and parent_id:
                    parent_success, parent_payload = _call_emby_api(
                        server,
                        f"Items/{parent_id}",
                        method="GET"
                    )
                    if parent_success and isinstance(parent_payload, dict):
                        library_id = parent_payload.get("Id") or library_id
                        library_name = parent_payload.get("Name") or library_name
                if not library_id:
                    library_id = parent_id
                return library_id, library_name

            items_batch = []
            batch_size = 20

            # Get recently added items - scan last 500 items sorted by DateCreated
            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Scansione ultimi {MAX_ITEMS} elementi aggiunti..."
            )

            max_items_to_scan = MAX_ITEMS  # Scan last items by DateCreated

            while not stop_flag.is_set():
                # Simple approach: get items sorted by DateCreated, process up to 500
                items_success, items_payload = _call_emby_api(
                    server,
                    "Items",
                    method="GET",
                    params={
                        "IncludeItemTypes": "Movie,Episode",
                        "Recursive": "true",
                        "SortBy": "DateCreated",
                        "SortOrder": "Descending",
                        "Limit": page_size,
                        "StartIndex": start_index,
                        "Fields": "Path,MediaStreams,RunTimeTicks,MediaSources,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,Type,DateCreated,Container"
                    }
                )

                if not items_success or not isinstance(items_payload, dict):
                    self._update_status(
                        server_id,
                        "recent_discovery",
                        last_log=f"{server_name}: Errore recupero ultimi elementi: {items_payload}"
                    )
                    return

                items = items_payload.get("Items", [])
                if not items:
                    if start_index == 0:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Nessun elemento recente trovato"
                        )
                    break

                for item in items:
                    if stop_flag.is_set():
                        break
                    if not isinstance(item, dict):
                        continue

                    item_id = item.get("Id")
                    if not item_id:
                        continue

                    item_date = _parse_emby_date(item.get("DateCreated"))

                    if item_date and item_date < cutoff_date:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Fermato - oltre {MAX_DAYS} giorni"
                        )
                        stop_flag.set()
                        break
                    # Track oldest item date for timestamp saving
                    if item_date and (oldest_item_date is None or item_date < oldest_item_date):
                        oldest_item_date = item_date

                    # Scan only the last max_items_to_scan items by DateCreated
                    # This ensures we check recently added content without processing the entire library
                    total_items_checked += 1
                    if total_items_checked > max_items_to_scan:
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            last_log=f"{server_name}: Scansionati {max_items_to_scan} elementi - discovery completata"
                        )
                        stop_flag.set()
                        break

                    item_path = item.get("Path", "")

                    # Filter: only .strm files (same logic as library discovery)
                    if not item_path.lower().endswith(".strm"):
                        continue

                    # Extract metadata
                    item_type = item.get("Type", "")
                    item_name = item.get("Name", "Sconosciuto")
                    series_name = item.get("SeriesName")
                    season_number = item.get("ParentIndexNumber")
                    episode_number = item.get("IndexNumber")
                    year = item.get("SeriesProductionYear") or item.get("ProductionYear")

                    media_sources = item.get("MediaSources")
                    if not isinstance(media_sources, list) or not media_sources:
                        media_sources = [None]

                    # Track if at least one source was queued for this item
                    item_has_queued_source = False

                    for source in media_sources:
                        if source is None:
                            source_streams = item.get("MediaStreams", [])
                            source_runtime = item.get("RunTimeTicks")
                            source_media_id = None
                            source_name = None
                        elif isinstance(source, dict):
                            source_streams = source.get("MediaStreams", [])
                            source_runtime = source.get("RunTimeTicks")
                            source_media_id = source.get("Id")
                            source_name = source.get("Name")
                        else:
                            continue

                        parent_id = item.get("ParentId")
                        library_id, library_name = resolve_library(item_path, parent_id)

                        # Check if this source has mediainfo
                        if source_runtime and source_streams:
                            continue  # Skip this source, it already has metadata

                        # Skip if blacklisted
                        if is_blacklisted(item_id, source_media_id):
                            continue

                        # Queue this source
                        queue_name = _format_probe_display_name(
                            item_type,
                            item_name,
                            year,
                            series_name,
                            season_number,
                            episode_number,
                            item_path,
                            source_name
                        )

                        items_batch.append({
                            "server_id": server_id,
                            "item_id": item_id,
                            "scope": PROBE_SCOPE_RECENT,
                            "media_source_id": source_media_id,
                            "library_id": library_id,
                            "library_name": library_name,
                            "name": queue_name,
                            "series_name": series_name,
                            "season_number": season_number,
                            "episode_number": episode_number,
                            "year": year,
                            "media_type": item_type,
                            "path": item_path
                        })

                        # Mark that we queued at least one source for this item
                        item_has_queued_source = True

                    # Update sliding window: 1 if no source was queued (all have metadata), 0 if at least one was queued
                    sliding_window.append(0 if item_has_queued_source else 1)
                    if len(sliding_window) > WINDOW_SIZE:
                        sliding_window.pop(0)

                    self._update_status(
                        server_id,
                        "recent_discovery",
                        increment_total_scanned=1
                    )

                    # Stop condition 4: sliding window threshold reached
                    if len(sliding_window) >= WINDOW_SIZE:
                        completion_rate = sum(sliding_window) / len(sliding_window)
                        if completion_rate >= WINDOW_THRESHOLD:
                            self._update_status(
                                server_id,
                                "recent_discovery",
                                last_log=f"{server_name}: Fermato - finestra {WINDOW_SIZE} elementi con {int(completion_rate*100)}% completi"
                            )
                            stop_flag.set()
                            break

                    # Flush batch periodically
                    if len(items_batch) >= batch_size:
                        db.add_to_probe_queue(items_batch)
                        self._update_status(
                            server_id,
                            "recent_discovery",
                            increment_found=len(items_batch),
                            last_log=f"{server_name}: Aggiunti {len(items_batch)} file dalla lista recente"
                        )
                        items_batch = []

                if stop_flag.is_set():
                    break

                start_index += page_size

            # Flush remaining items (always flush, even if stopped by sliding window)
            if items_batch:
                db.add_to_probe_queue(items_batch)
                self._update_status(
                    server_id,
                    "recent_discovery",
                    increment_found=len(items_batch)
                )

            # Save oldest scanned timestamp for next run
            if oldest_item_date:
                db.save_recent_scan_timestamp(server_id, oldest_item_date)

            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Discovery interrotta dall'utente"
                )
            else:
                found_count = self._status.get(server_id, {}).get("recent_discovery", {}).get("found", 0)
                scanned_count = self._status.get(server_id, {}).get("recent_discovery", {}).get("total_scanned", 0)
                self._update_status(
                    server_id,
                    "recent_discovery",
                    last_log=f"{server_name}: Discovery completata - Trovati {found_count} file da analizzare su {scanned_count} elementi scansionati"
                )

        except Exception as exc:
            self._update_status(
                server_id,
                "recent_discovery",
                last_log=f"{server_name}: Errore critico - {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "recent_discovery" in self._status[server_id]:
                    self._status[server_id]["recent_discovery"]["running"] = False

    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None,
        scope: str = PROBE_SCOPE_LIBRARIES,
        status_key: str = "processing"
    ) -> None:
        """
        Processing worker: processes items from the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, status_key, last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()

            while not stop_flag.is_set():
                if scope == PROBE_SCOPE_RECENT:
                    while not stop_flag.is_set():
                        with self._lock:
                            discovery_worker = self._workers.get(server_id, {}).get("recent_discovery")
                        if not discovery_worker or not discovery_worker.is_alive():
                            break
                        self._update_status(
                            server_id,
                            status_key,
                            last_log="In attesa: discovery in corso..."
                        )
                        if stop_flag.wait(1):
                            break
                    if stop_flag.is_set():
                        break

                # Load queue
                self._update_status(
                    server_id,
                    status_key,
                    last_log="Caricamento coda dal database..."
                )

                queue_items = db.get_probe_queue(server_id, library_ids=target_libraries, scope=scope)

                library_totals: Dict[str, int] = {}
                if scope == PROBE_SCOPE_LIBRARIES:
                    for lib_id in target_libraries or []:
                        if lib_id:
                            library_totals[str(lib_id)] = 0
                    for item in queue_items:
                        lib_id = item.get("library_id")
                        if lib_id:
                            key = str(lib_id)
                            library_totals[key] = library_totals.get(key, 0) + 1
                    if library_totals:
                        self._merge_processing_library_totals(server_id, status_key, library_totals)

                self._update_status(
                    server_id,
                    status_key,
                    total=len(queue_items),
                    last_log=f"Trovati {len(queue_items)} file da processare"
                )

                if not queue_items:
                    self._update_status(
                        server_id,
                        status_key,
                        last_log="Coda vuota, nessun file da processare"
                    )
                    break

                blacklist = db.load_probe_blacklist(server_id, scope=scope)

                def retry_count_for(item_id: str, media_source_id: str | None = None) -> int:
                    # Use composite key to match blacklist entry
                    key = f"{item_id}:{media_source_id or ''}"
                    entry = blacklist.get(key)
                    if not entry:
                        return 0
                    return int(entry.get("retry_count") or 0)

                processable = [
                    item for item in queue_items
                    if retry_count_for(item.get("item_id"), item.get("media_source_id")) < 3
                ]

                if not processable:
                    filtered_count = len(queue_items) - len(processable)
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Nessun file processabile: {filtered_count} file hanno raggiunto 3+ errori"
                    )
                    break

                # Check if we're processing retries
                has_retries = any(retry_count_for(item.get("item_id"), item.get("media_source_id")) > 0 for item in processable)
                if has_retries:
                    retry_count = sum(1 for item in processable if retry_count_for(item.get("item_id"), item.get("media_source_id")) > 0)
                    first_attempt_count = len(processable) - retry_count
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Processing: {first_attempt_count} primi tentativi + {retry_count} retry"
                    )

                def handle_queue_item(queue_item: Dict[str, Any]) -> bool:
                    if stop_flag.is_set():
                        return False

                    # Smart mode: check if server is busy and wait if needed
                    if mode == "smart":
                        while not stop_flag.is_set():
                            sessions, error = _fetch_emby_active_sessions(server)
                            if error or not sessions:
                                # No streams or error checking - proceed with processing
                                break
                            # Server is busy - wait before checking again
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"In pausa: {len(sessions)} stream attivi sul server..."
                            )
                            # Wait 10 seconds before checking again
                            if stop_flag.wait(10):
                                break

                        # If stopped while waiting, exit processing loop
                        if stop_flag.is_set():
                            return False

                    item_id = queue_item["item_id"]
                    item_display_name = _format_display_name_from_queue(queue_item)
                    library_name = queue_item.get("library_name")
                    library_id = queue_item.get("library_id")
                    media_source_id = queue_item.get("media_source_id")

                    # Check if this is a retry
                    current_retry_count = retry_count_for(item_id, media_source_id)
                    is_retry = current_retry_count > 0

                    # Update current item
                    self._update_status(
                        server_id,
                        status_key,
                        current_item=item_display_name,
                        current_library_id=library_id,
                        current_library_name=library_name,
                        last_log=f"Analisi: {item_display_name}"
                    )

                    # Probe the item
                    start_time = time.time()
                    probe_success = self._probe_item(server, item_id, item_display_name, media_source_id)
                    duration_ms = int((time.time() - start_time) * 1000)

                    # Check stop flag
                    if stop_flag.is_set():
                        return False

                    # Remove from queue
                    db.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)

                    status = "ERROR"
                    error_details = "Timeout o errore API"
                    should_requeue = True

                    if probe_success:
                        # Probe succeeded - this means Emby accepted the PlaybackInfo request
                        # Now verify that metadata was actually written using polling
                        # Emby may take several seconds to complete ffprobe analysis in background

                        max_attempts = 15  # Maximum polling attempts (15 seconds)
                        attempt = 0
                        metadata_ok = False
                        metadata_error = None

                        time.sleep(1)  # Initial delay before first check

                        while attempt < max_attempts and not stop_flag.is_set():
                            metadata_ok, metadata_error = self._verify_probe_metadata(server, item_id, media_source_id)

                            if metadata_ok:
                                # Metadata verification successful - break out of polling loop
                                break

                            attempt += 1
                            if attempt < max_attempts:
                                # Wait 1 second before next attempt
                                time.sleep(1)

                        if metadata_ok:
                            # Metadata verified successfully
                            status = "SUCCESS"
                            error_details = None
                            should_requeue = False
                            db.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
                        else:
                            # Verification failed after all polling attempts
                            # Either missing metadata or persistent API issues during verification
                            # Since the probe itself succeeded, treat any verification failure as INCOMPLETE
                            status = "INCOMPLETE"
                            error_details = metadata_error or "Mediainfo non scritto dopo polling"

                    if status != "SUCCESS":
                        error_type = "INCOMPLETE" if status == "INCOMPLETE" else "ERROR"
                        retry_count = db.update_probe_blacklist(
                            server_id,
                            item_id,
                            item_display_name,
                            error_details or "Errore probe",
                            media_source_id=media_source_id,
                            increment_retry=True,
                            error_type=error_type,
                            scope=scope,
                            library_id=library_id,
                            library_name=library_name
                        )
                        if retry_count >= 3:
                            should_requeue = False

                    final_for_library = not should_requeue

                    # Add to history
                    db.add_probe_history({
                        "server_id": server_id,
                        "item_id": item_id,
                        "media_source_id": media_source_id,
                        "scope": scope,
                        "name": item_display_name,
                        "library_name": library_name,
                        "status": status,
                        "error_details": error_details,
                        "duration_ms": duration_ms
                    })

                    if status == "SUCCESS":
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Completato (retry {current_retry_count}): {item_display_name}",
                                increment_processed_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Completato: {item_display_name}",
                                increment_processed=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "processed")
                    elif status == "INCOMPLETE":
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Incompleto (retry {current_retry_count}): {item_display_name}",
                                increment_incomplete_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Incompleto: {item_display_name}",
                                increment_incomplete=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "incomplete")
                    else:
                        if is_retry:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Errore (retry {current_retry_count}): {item_display_name}",
                                increment_errors_retry=1
                            )
                        else:
                            self._update_status(
                                server_id,
                                status_key,
                                last_log=f"Errore: {item_display_name}",
                                increment_errors=1
                            )
                        if final_for_library and scope == PROBE_SCOPE_LIBRARIES and library_id:
                            self._increment_processing_library_result(server_id, status_key, str(library_id), "errors")

                    if should_requeue and not stop_flag.is_set():
                        db.add_to_probe_queue([queue_item])

                    # Rate limiting
                    if stop_flag.wait(1):
                        return False

                    return True

                if scope == PROBE_SCOPE_LIBRARIES:
                    library_order = [str(lib_id) for lib_id in (target_libraries or []) if lib_id]
                    if not library_order:
                        library_names: Dict[str, str] = {}
                        for item in processable:
                            lib_id = item.get("library_id")
                            if not lib_id:
                                continue
                            key = str(lib_id)
                            if key not in library_names:
                                library_names[key] = str(item.get("library_name") or key)
                        library_order = sorted(library_names.keys(), key=lambda lib_id: library_names[lib_id].lower())

                    for library_id in library_order:
                        if stop_flag.is_set():
                            break
                        while not stop_flag.is_set():
                            library_queue = db.get_probe_queue(server_id, library_ids=[library_id], scope=scope)
                            if not library_queue:
                                break
                            blacklist = db.load_probe_blacklist(server_id, scope=scope)
                            library_processable = [
                                item for item in library_queue
                                if retry_count_for(item.get("item_id"), item.get("media_source_id")) < 3
                            ]
                            if not library_processable:
                                break
                            library_name = library_processable[0].get("library_name") or library_queue[0].get("library_name")
                            self._update_status(
                                server_id,
                                status_key,
                                current_library_id=str(library_id),
                                current_library_name=library_name
                            )
                            for queue_item in library_processable:
                                if not handle_queue_item(queue_item):
                                    break
                            if stop_flag.is_set():
                                break
                        if stop_flag.is_set():
                            break
                else:
                    for queue_item in processable:
                        if not handle_queue_item(queue_item):
                            break

                if stop_flag.is_set():
                    break

                # Ricarica la coda per processare eventuali retry
                # Il loop while continuerà automaticamente

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    status_key,
                    last_log="Processing interrotto dall'utente"
                )
            else:
                processed = self._status.get(server_id, {}).get(status_key, {}).get("processed", 0)
                incomplete = self._status.get(server_id, {}).get(status_key, {}).get("incomplete", 0)
                errors = self._status.get(server_id, {}).get(status_key, {}).get("errors", 0)
                total = processed + incomplete + errors
                if total == 0:
                    # No files were actually processed - keep the last status message (e.g., "Nessun file processabile")
                    pass
                else:
                    parts = [f"Successi: {processed}"]
                    if incomplete > 0:
                        parts.append(f"Incompleti: {incomplete}")
                    if errors > 0:
                        parts.append(f"Errori: {errors}")
                    self._update_status(
                        server_id,
                        status_key,
                        last_log=f"Processing completato. {', '.join(parts)}"
                    )

        except Exception as exc:
            self._update_status(
                server_id,
                status_key,
                last_log=f"Errore critico: {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and status_key in self._status[server_id]:
                    self._status[server_id][status_key]["running"] = False
                    self._status[server_id][status_key]["current_library_id"] = None
                    self._status[server_id][status_key]["current_library_name"] = None
                if scope == PROBE_SCOPE_LIBRARIES and status_key == "processing":
                    combo_key = f"combo_{PROBE_SCOPE_LIBRARIES}"
                    combo_status = self._status.get(server_id, {}).get(combo_key, {})
                    if combo_status and not combo_status.get("running") and combo_status.get("board_mode") == "processing":
                        library_ids = self._status.get(server_id, {}).get(status_key, {}).get("target_library_ids") or []
                        self._status[server_id][combo_key]["last_run"] = self._build_combo_last_run(
                            [server],
                            PROBE_SCOPE_LIBRARIES,
                            stop_flag.is_set(),
                            library_ids=library_ids,
                            task_types=["processing"]
                        )
                        self._status[server_id][combo_key]["board_reset"] = True

    def retry_item(
        self,
        server: Dict[str, Any],
        server_id: str,
        item_id: str,
        media_source_id: str | None = None,
        scope: str = PROBE_SCOPE_LIBRARIES
    ) -> tuple[bool, str]:
        """
        Retry a failed item by re-adding it to the queue.

        Args:
            server: Server configuration dict with url, api_key, etc.
            server_id: Unique server identifier
            item_id: Item ID to retry

        Returns:
            Tuple of (success, message)
        """
        if not self._db_getter:
            return False, "Database non configurato"

        # Fetch item metadata from Emby API (Items endpoint is more reliable than Items/{id})
        success, payload = _call_emby_api(
            server,
            "Items",
            method="GET",
            params={
                "Ids": item_id,
                "Fields": "Path,ParentId,SeriesName,IndexNumber,ParentIndexNumber,ProductionYear,SeriesProductionYear,RunTimeTicks,MediaStreams,MediaSources,Type"
            }
        )

        if not success or not isinstance(payload, dict):
            return False, f"Errore recupero item da Emby: {payload}"

        items = payload.get("Items")
        if not isinstance(items, list) or not items:
            # File doesn't exist anymore - clean it up from all tables
            db = self._db_getter()
            db.remove_from_probe_queue(server_id, item_id, media_source_id, scope=scope)
            db.remove_from_probe_blacklist(server_id, item_id, media_source_id, scope=scope)
            db.remove_from_probe_history(server_id, item_id, media_source_id, scope=scope)
            return False, "File non trovato su Emby (rimosso automaticamente dalla coda/blacklist)"

        payload = items[0]

        # Extract metadata (same mapping as in _discovery_worker)
        item_type = payload.get("Type", "")
        item_name = payload.get("Name", "Sconosciuto")
        series_name = payload.get("SeriesName")
        season_number = payload.get("ParentIndexNumber")
        episode_number = payload.get("IndexNumber")
        year = payload.get("SeriesProductionYear") or payload.get("ProductionYear")
        parent_id = payload.get("ParentId")
        item_path = payload.get("Path", "")

        library_id = None
        library_name = "Libreria"

        ancestors_success, ancestors_payload = _call_emby_api(
            server,
            f"Items/{item_id}/Ancestors",
            method="GET"
        )
        if ancestors_success and isinstance(ancestors_payload, list):
            for ancestor in ancestors_payload:
                if not isinstance(ancestor, dict):
                    continue
                if ancestor.get("Type") == "CollectionFolder":
                    library_id = ancestor.get("Id") or ancestor.get("ItemId")
                    library_name = ancestor.get("Name") or library_name
                    break

        if not library_id and item_path:
            folders_success, folders_payload = _call_emby_api(
                server,
                "Library/VirtualFolders",
                method="GET"
            )
            if folders_success and isinstance(folders_payload, list):
                best_match = None
                best_len = 0
                item_norm = str(item_path).replace("\\", "/").rstrip("/").lower()
                for folder in folders_payload:
                    if not isinstance(folder, dict):
                        continue
                    locations = folder.get("Locations")
                    if not isinstance(locations, list):
                        continue
                    for location in locations:
                        if not location:
                            continue
                        loc_norm = str(location).replace("\\", "/").rstrip("/").lower()
                        if not loc_norm:
                            continue
                        loc_prefix = loc_norm + "/"
                        if item_norm.startswith(loc_prefix) and len(loc_prefix) > best_len:
                            best_len = len(loc_prefix)
                            best_match = folder
                if isinstance(best_match, dict):
                    library_id = best_match.get("Id") or best_match.get("ItemId") or library_id
                    library_name = best_match.get("Name") or library_name

        if not library_id and parent_id:
            parent_success, parent_payload = _call_emby_api(
                server,
                f"Items/{parent_id}",
                method="GET"
            )
            if parent_success and isinstance(parent_payload, dict):
                library_id = parent_payload.get("Id") or library_id
                library_name = parent_payload.get("Name") or library_name

        if not library_id:
            library_id = parent_id

        media_sources = payload.get("MediaSources")
        if not isinstance(media_sources, list) or not media_sources:
            media_sources = [None]

        queue_items = []

        for source in media_sources:
            if source is None:
                source_streams = payload.get("MediaStreams", [])
                source_runtime = payload.get("RunTimeTicks")
                source_media_id = None
                source_name = None
            elif isinstance(source, dict):
                source_streams = source.get("MediaStreams", [])
                source_runtime = source.get("RunTimeTicks")
                source_media_id = source.get("Id")
                source_name = source.get("Name")
            else:
                continue

            if source_runtime and source_streams:
                continue

            queue_name = _format_probe_display_name(
                item_type,
                item_name,
                year,
                series_name,
                season_number,
                episode_number,
                item_path,
                source_name
            )

            queue_items.append({
                "server_id": server_id,
                "item_id": item_id,
                "scope": scope,
                "media_source_id": source_media_id,
                "library_id": library_id,
                "library_name": library_name,
                "name": queue_name,
                "series_name": series_name,
                "season_number": season_number,
                "episode_number": episode_number,
                "year": year,
                "media_type": item_type,
                "path": item_path
            })

        target_media_source_id = media_source_id
        if target_media_source_id:
            queue_items = [item for item in queue_items if item.get("media_source_id") == target_media_source_id]

        if not queue_items:
            return False, "Nessuna sorgente senza metadati da riprocessare"

        try:
            db = self._db_getter()
            # Add to queue
            db.add_to_probe_queue(queue_items)
            # Remove from history
            for queue_item in queue_items:
                db.remove_from_probe_history(server_id, item_id, queue_item.get("media_source_id"))
            display_name = queue_items[0].get("name") or item_name
            return True, f"Item '{display_name}' aggiunto alla coda ({len(queue_items)} sorgenti)"
        except Exception as exc:
            return False, f"Errore database: {exc}"

    def _verify_probe_metadata(
        self,
        server: Dict[str, Any],
        item_id: str,
        media_source_id: str | None = None,
        max_retries: int = 2
    ) -> tuple[bool, str | None]:
        """
        Verifica metadata con retry logic per bypass cache Emby.

        FIX PROBLEMA #9: Aggiunge retry con backoff esponenziale per evitare
        letture stale dalla cache interna di Emby dopo probe.

        Args:
            server: Server Emby
            item_id: ID dell'item
            media_source_id: ID del media source (opzionale)
            max_retries: Numero massimo tentativi (default: 2)

        Returns:
            Tupla (success: bool, error_msg: str | None)
        """
        import time

        for attempt in range(max_retries + 1):
            # Use Items endpoint with Ids parameter instead of Items/{id}
            # This avoids Emby's heavy caching on single-item endpoint
            success, payload = _call_emby_api(
                server,
                "Items",
                method="GET",
                params={
                    "Ids": item_id,
                    "Fields": "MediaSources,MediaStreams,RunTimeTicks"
                }
            )

            if not success:
                # Retry on API errors (might be temporary)
                if attempt < max_retries:
                    wait_time = 2 ** attempt  # Backoff esponenziale: 1s, 2s, 4s
                    time.sleep(wait_time)
                    continue
                # Return the actual error message from the API
                error_msg = str(payload) if payload else "API non risponde"
                return False, f"API error: {error_msg[:100]}"

            if not isinstance(payload, dict):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Risposta API non valida"

            # Extract item from Items list
            items = payload.get("Items", [])
            if not items or not isinstance(items, list):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Item non trovato nella risposta"

            item = items[0]
            if not isinstance(item, dict):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Formato item non valido"

            # Metadata extraction e validazione
            sources = item.get("MediaSources")

            # If media_source_id is specified, check that specific source
            if media_source_id and isinstance(sources, list):
                for source in sources:
                    if isinstance(source, dict) and source.get("Id") == media_source_id:
                        streams = source.get("MediaStreams", [])
                        runtime = source.get("RunTimeTicks")

                        if not runtime or not streams or len(streams) == 0:
                            # Retry - metadata potrebbe essere stale
                            if attempt < max_retries:
                                time.sleep(2 ** attempt)
                                break  # Esci dal for source, riprova il fetch
                            return False, "RunTimeTicks o MediaStreams mancante"

                        # Validazione streams video
                        has_valid_video = self._validate_video_streams(streams)
                        if not has_valid_video:
                            if attempt < max_retries:
                                time.sleep(2 ** attempt)
                                break
                            return False, "Nessun stream video valido"

                        return True, None

                # media_source_id specified but not found
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "MediaSource non trovato"

            # No media_source_id, check item level or first source
            streams = item.get("MediaStreams", [])
            runtime = item.get("RunTimeTicks")

            # If item-level metadata is missing, try first MediaSource
            if (not runtime or not streams) and isinstance(sources, list) and sources:
                first = sources[0] if isinstance(sources[0], dict) else None
                if first:
                    streams = first.get("MediaStreams", [])
                    runtime = first.get("RunTimeTicks")

            if not runtime or not streams or len(streams) == 0:
                # Retry - metadata potrebbe essere stale
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "RunTimeTicks o MediaStreams mancante"

            # FIX PROBLEMA #5: Validazione avanzata streams
            has_valid_video = self._validate_video_streams(streams)
            if not has_valid_video:
                # Retry - stream potrebbe non essere ancora processato
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Nessun stream video valido trovato"

            # Success!
            return True, None

        # Se arriviamo qui, tutti i retry sono falliti
        return False, "Verifica metadata fallita dopo tutti i tentativi"

    def _validate_video_streams(self, streams: list) -> bool:
        """
        Valida che ci sia almeno uno stream video con codec valido.

        Args:
            streams: Lista di MediaStreams

        Returns:
            True se trovato almeno uno stream video valido
        """
        for stream in streams:
            if not isinstance(stream, dict):
                continue

            stream_type = stream.get("Type", "").lower()
            if stream_type == "video":
                codec = stream.get("Codec")
                if codec and isinstance(codec, str) and len(codec) > 0:
                    return True

        return False

    def _probe_item(
        self,
        server: Dict[str, Any],
        item_id: str,
        item_name: str,
        media_source_id: str | None = None
    ) -> bool:
        """
        Probe an item by calling PlaybackInfo endpoint.

        Args:
            server: Server configuration
            item_id: Item ID to probe
            item_name: Item name for logging

        Returns:
            True if successful, False otherwise
        """
        base_url = server.get("url", "").rstrip("/")
        token = server.get("api_key", "").strip()

        if not base_url or not token:
            return False

        target = f"{base_url}/Items/{item_id}/PlaybackInfo"
        headers = {
            "X-Emby-Token": token,
            "Accept": "application/json"
        }
        params = {"UserId": ""}
        if media_source_id:
            params["MediaSourceId"] = media_source_id

        try:
            response = requests.post(target, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            return True
        except (requests.RequestException, requests.HTTPError):
            return False


# Global singleton instance
_probe_manager = EmbyProbeManager()


def get_probe_manager() -> EmbyProbeManager:
    """Get the global probe manager instance."""
    return _probe_manager
