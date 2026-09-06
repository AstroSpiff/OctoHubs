"""Canonical construction and persistence of Jellyseerr request projections."""

from __future__ import annotations

from typing import Any

from core.config_manager import _ensure_db_backend
from emby_latest import jellyseerr as latest_jellyseerr
from emby_runtime.api_clients import get_jellyseerr_requests
from services.requests_summary import _summarize_requests_for_dashboard


def save_request_refresh_dataset(
    config: dict[str, Any],
    requests_data: list[dict[str, Any]],
    *,
    backend: Any | None = None,
) -> list[dict[str, Any]]:
    """Publish every projection derived from one authoritative dataset."""
    overview = _summarize_requests_for_dashboard(
        config,
        requests_data=requests_data,
    )
    jellyseerr_entries = latest_jellyseerr.build_request_entries(requests_data)
    target_backend = backend or _ensure_db_backend()
    target_backend.save_request_refresh_snapshot(overview, jellyseerr_entries)
    return overview


def refresh_request_snapshot(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch Jellyseerr once and atomically publish all derived projections."""
    requests_data, ok = get_jellyseerr_requests(
        config,
        silent=True,
        return_status=True,
    )
    if not ok:
        raise RuntimeError("Jellyseerr request dataset unavailable")
    return save_request_refresh_dataset(config, requests_data)


__all__ = ["refresh_request_snapshot", "save_request_refresh_dataset"]
