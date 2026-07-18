"""Concurrency settings for Latest Publications collection."""

from __future__ import annotations

from typing import Any, Dict


DEFAULT_PARALLELISM = {
    "server_workers": 0,
    "requests_per_server": 4,
}


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_parallelism_settings(settings: Any) -> Dict[str, int]:
    """Normalize the persisted Latest parallelism block."""
    source = settings if isinstance(settings, dict) else {}
    parallelism = source.get("parallelism")
    if not isinstance(parallelism, dict):
        parallelism = {}

    server_workers = _coerce_int(
        parallelism.get("server_workers", source.get("latest_server_workers")),
        DEFAULT_PARALLELISM["server_workers"],
    )
    requests_per_server = _coerce_int(
        parallelism.get("requests_per_server", source.get("latest_requests_per_server")),
        DEFAULT_PARALLELISM["requests_per_server"],
    )

    if server_workers < 0:
        server_workers = DEFAULT_PARALLELISM["server_workers"]
    if requests_per_server <= 0:
        requests_per_server = DEFAULT_PARALLELISM["requests_per_server"]

    requests_per_server = min(requests_per_server, 16)
    return {
        "server_workers": server_workers,
        "requests_per_server": requests_per_server,
    }


def resolve_parallelism(settings: Any, server_count: int) -> Dict[str, int]:
    """Resolve normalized settings into concrete worker counts for a run."""
    normalized = normalize_parallelism_settings(settings)
    try:
        total_servers = max(1, int(server_count))
    except (TypeError, ValueError):
        total_servers = 1

    configured_server_workers = normalized["server_workers"]
    if configured_server_workers <= 0:
        server_workers = total_servers
    else:
        server_workers = configured_server_workers
    server_workers = max(1, min(server_workers, total_servers))

    return {
        "server_workers": server_workers,
        "requests_per_server": normalized["requests_per_server"],
    }
