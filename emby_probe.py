"""Emby Probe Manager - Background worker for analyzing and repairing .strm files."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import requests

from api_clients import _call_emby_api, _fetch_emby_active_sessions, _fetch_emby_libraries


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
                "last_log": "Avvio discovery...",
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
                "total": 0,
                "current_item": None,
                "last_log": f"Avvio processing in modalità {mode}...",
                "mode": mode,
                "started_at": datetime.now(timezone.utc).isoformat()
            }

            worker = threading.Thread(
                target=self._processing_worker,
                args=(server, server_id, mode, stop_flag, target_libraries),
                daemon=True
            )
            worker.start()
            self._workers[server_id]["processing"] = worker

        return True

    def stop_discovery(self, server_id: str) -> bool:
        """Stop the discovery worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "discovery" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["discovery"].set()
        return True

    def stop_processing(self, server_id: str) -> bool:
        """Stop the processing worker for a server."""
        with self._lock:
            if server_id not in self._stop_flags or "processing" not in self._stop_flags[server_id]:
                return False
            self._stop_flags[server_id]["processing"].set()
        return True

    def get_status(self, server_id: str) -> Dict[str, Any]:
        """Get the status of both discovery and processing workers for a server."""
        with self._lock:
            return self._status.get(server_id, {})

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
                library_name = library.get("name", "Sconosciuto")

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
                        break

                    items = payload.get("Items", [])
                    total_count = payload.get("TotalRecordCount", 0)
                    if library_id:
                        self._set_library_total(server_id, library_id, total_count)

                    if not items:
                        break

                    # Refresh blacklist to pick up any changes made during discovery
                    blacklist = db.load_probe_blacklist(server_id)

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

                    start_index += page_size
                    if start_index >= total_count:
                        break

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

    def _processing_worker(
        self,
        server: Dict[str, Any],
        server_id: str,
        mode: str,
        stop_flag: threading.Event,
        target_libraries: Optional[list[str]] = None
    ) -> None:
        """
        Processing worker: processes items from the queue.
        """
        try:
            if not self._db_getter:
                self._update_status(server_id, "processing", last_log="Errore: database non configurato", running=False)
                return

            db = self._db_getter()

            while not stop_flag.is_set():
                # Load queue
                self._update_status(
                    server_id,
                    "processing",
                    last_log="Caricamento coda dal database..."
                )

                queue_items = db.get_probe_queue(server_id, library_ids=target_libraries)

                self._update_status(
                    server_id,
                    "processing",
                    total=len(queue_items),
                    last_log=f"Trovati {len(queue_items)} file da processare"
                )

                if not queue_items:
                    self._update_status(
                        server_id,
                        "processing",
                        last_log="Coda vuota, nessun file da processare"
                    )
                    break

                blacklist = db.load_probe_blacklist(server_id)

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
                        "processing",
                        last_log=f"Nessun file processabile: {filtered_count} file hanno raggiunto 3+ errori"
                    )
                    break

                interrupted_by_streams = False

                # Process each item
                for queue_item in processable:
                    if stop_flag.is_set():
                        break

                    # Smart mode: check if server is busy
                    if mode == "smart":
                        sessions, error = _fetch_emby_active_sessions(server)
                        if not error and sessions:
                            self._update_status(
                                server_id,
                                "processing",
                                last_log=f"Server occupato ({len(sessions)} stream attivi), interruzione..."
                            )
                            interrupted_by_streams = True
                            break

                    item_id = queue_item["item_id"]
                    item_display_name = _format_display_name_from_queue(queue_item)
                    library_name = queue_item.get("library_name")
                    library_id = queue_item.get("library_id")
                    media_source_id = queue_item.get("media_source_id")

                    # Update current item
                    self._update_status(
                        server_id,
                        "processing",
                        current_item=item_display_name,
                        last_log=f"Analisi: {item_display_name}"
                    )

                    # Probe the item
                    start_time = time.time()
                    probe_success = self._probe_item(server, item_id, item_display_name, media_source_id)
                    duration_ms = int((time.time() - start_time) * 1000)

                    # Check stop flag
                    if stop_flag.is_set():
                        break

                    # Remove from queue
                    db.remove_from_probe_queue(server_id, item_id, media_source_id)

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
                            db.remove_from_probe_blacklist(server_id, item_id, media_source_id)
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
                            library_id=library_id,
                            library_name=library_name
                        )
                        if retry_count >= 3:
                            should_requeue = False

                    # Add to history
                    db.add_probe_history({
                        "server_id": server_id,
                        "item_id": item_id,
                        "media_source_id": media_source_id,
                        "name": item_display_name,
                        "library_name": library_name,
                        "status": status,
                        "error_details": error_details,
                        "duration_ms": duration_ms
                    })

                    if status == "SUCCESS":
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Completato: {item_display_name}",
                            increment_processed=1
                        )
                    elif status == "INCOMPLETE":
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Incompleto: {item_display_name}",
                            increment_incomplete=1
                        )
                    else:
                        self._update_status(
                            server_id,
                            "processing",
                            last_log=f"Errore: {item_display_name}",
                            increment_errors=1
                        )

                    if should_requeue and not stop_flag.is_set():
                        db.add_to_probe_queue([queue_item])

                    # Rate limiting
                    if stop_flag.wait(1):
                        break

                if stop_flag.is_set():
                    break

                if interrupted_by_streams:
                    self._update_status(
                        server_id,
                        "processing",
                        last_log="Interrotto per stream attivi, riprova dopo..."
                    )
                    break

                # Ricarica la coda per processare eventuali retry
                # Il loop while continuerà automaticamente

            # Final message
            if stop_flag.is_set():
                self._update_status(
                    server_id,
                    "processing",
                    last_log="Processing interrotto dall'utente"
                )
            else:
                processed = self._status.get(server_id, {}).get("processing", {}).get("processed", 0)
                incomplete = self._status.get(server_id, {}).get("processing", {}).get("incomplete", 0)
                errors = self._status.get(server_id, {}).get("processing", {}).get("errors", 0)
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
                        "processing",
                        last_log=f"Processing completato. {', '.join(parts)}"
                    )

        except Exception as exc:
            self._update_status(
                server_id,
                "processing",
                last_log=f"Errore critico: {exc}"
            )
        finally:
            with self._lock:
                if server_id in self._status and "processing" in self._status[server_id]:
                    self._status[server_id]["processing"]["running"] = False

    def retry_item(
        self,
        server: Dict[str, Any],
        server_id: str,
        item_id: str,
        media_source_id: str | None = None
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
            db.remove_from_probe_queue(server_id, item_id, media_source_id)
            db.remove_from_probe_blacklist(server_id, item_id, media_source_id)
            db.remove_from_probe_history(server_id, item_id, media_source_id)
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
        media_source_id: str | None = None
    ) -> tuple[bool, str | None]:
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
            # Return the actual error message from the API
            error_msg = str(payload) if payload else "API non risponde"
            return False, f"API error: {error_msg[:100]}"

        if not isinstance(payload, dict):
            return False, "Risposta API non valida"

        # Extract item from Items list
        items = payload.get("Items", [])
        if not items or not isinstance(items, list):
            return False, "Item non trovato nella risposta"

        item = items[0]
        if not isinstance(item, dict):
            return False, "Formato item non valido"

        sources = item.get("MediaSources")

        # If media_source_id is specified, check that specific source
        if media_source_id and isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and source.get("Id") == media_source_id:
                    streams = source.get("MediaStreams", [])
                    runtime = source.get("RunTimeTicks")

                    if not runtime:
                        return False, "RunTimeTicks mancante"
                    if not streams or len(streams) == 0:
                        return False, "MediaStreams vuoto"

                    return True, None

            # media_source_id specified but not found
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

        if not runtime:
            return False, "RunTimeTicks mancante"
        if not streams or len(streams) == 0:
            return False, "MediaStreams vuoto"

        return True, None

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
