"""Availability helpers for Jellyseerr request processing."""

from __future__ import annotations

from typing import Any

from core.utils import _normalize_media_type, get_nested
from search.seasons import (
    _collect_request_season_payloads,
    _is_season_entry_available,
    _is_status_available,
)


def _request_status_available(request_item: dict[str, Any]) -> bool:
    status = (
        get_nested(request_item, "media", "status")
        or request_item.get("status")
        or get_nested(request_item, "mediaInfo", "status")
    )
    return _is_status_available(status)


def _season_statuses_available(season_statuses: list[dict[str, Any]] | None) -> bool:
    if not season_statuses:
        return False
    statuses = [
        str(entry.get("status") or "").lower()
        for entry in season_statuses
        if isinstance(entry, dict)
    ]
    return bool(statuses) and all(status == "available" for status in statuses)


def _season_payloads_available(request_item: dict[str, Any]) -> bool:
    payloads = [
        entry
        for entry in _collect_request_season_payloads(request_item, include_related=True)
        if isinstance(entry, dict)
    ]
    return bool(payloads) and all(_is_season_entry_available(entry) for entry in payloads)


def is_request_available(
    request_item: dict[str, Any] | None,
    season_statuses: list[dict[str, Any]] | None = None,
) -> bool:
    """Return whether a Jellyseerr request is already fully available."""

    if not isinstance(request_item, dict):
        return False
    if request_item.get("is_available") is True:
        return True
    if _request_status_available(request_item):
        return True

    media_type = _normalize_media_type(
        request_item.get("media_type")
        or request_item.get("type")
        or get_nested(request_item, "media", "mediaType")
        or get_nested(request_item, "mediaInfo", "mediaType")
    )
    if media_type != "tv":
        return False
    if season_statuses is not None:
        return _season_statuses_available(season_statuses)
    cached_season_statuses = request_item.get("season_status")
    if isinstance(cached_season_statuses, list):
        return _season_statuses_available(cached_season_statuses)
    return _season_payloads_available(request_item)


def normalize_request_availability(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return request rows with cached availability recalculated where possible."""

    normalized: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        available = is_request_available(request)
        if request.get("is_available") is available:
            normalized.append(request)
            continue
        updated = dict(request)
        updated["is_available"] = available
        normalized.append(updated)
    return normalized
