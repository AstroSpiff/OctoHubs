"""Operational limits and normalization for library scan batches."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from core.emby_identifiers import normalize_emby_identifier


MAX_SCAN_LIBRARIES_PER_SERVER = 50
MAX_SCAN_LIBRARIES_PER_REQUEST = 100


def normalize_library_ids(
    values: Iterable[Any],
    *,
    maximum: int = MAX_SCAN_LIBRARIES_PER_SERVER,
) -> list[str]:
    """Validate, deduplicate and bound opaque library identifiers."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        library_id = normalize_emby_identifier(value)
        if library_id is None:
            raise ValueError("ID libreria non valido")
        if library_id in seen:
            continue
        seen.add(library_id)
        normalized.append(library_id)
        if len(normalized) > maximum:
            raise ValueError(f"Massimo {maximum} librerie per server")
    if not normalized:
        raise ValueError("Nessuna libreria specificata")
    return normalized


def normalize_group_libraries(values: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Deduplicate a group request and enforce total and per-server quotas."""
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    per_server: Counter[str] = Counter()
    for entry in values:
        server_id = normalize_emby_identifier(entry.get("server_id"))
        library_id = normalize_emby_identifier(entry.get("library_id"))
        if server_id is None or library_id is None:
            raise ValueError("Server o ID libreria non valido")
        identity = (server_id, library_id)
        if identity in seen:
            continue
        seen.add(identity)
        per_server[server_id] += 1
        if per_server[server_id] > MAX_SCAN_LIBRARIES_PER_SERVER:
            raise ValueError(
                f"Massimo {MAX_SCAN_LIBRARIES_PER_SERVER} librerie per server"
            )
        normalized.append({"server_id": server_id, "library_id": library_id})
        if len(normalized) > MAX_SCAN_LIBRARIES_PER_REQUEST:
            raise ValueError(
                f"Massimo {MAX_SCAN_LIBRARIES_PER_REQUEST} librerie per richiesta"
            )
    if not normalized:
        raise ValueError("Nessuna libreria specificata")
    return normalized
