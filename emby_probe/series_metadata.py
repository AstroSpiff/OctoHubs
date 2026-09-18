"""Resolve stable series metadata for Probe queue entries."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any


_BATCH_SIZE = 100


def _chunks(values: list[str], size: int = _BATCH_SIZE) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if 1800 <= parsed <= datetime.now().year + 20:
        return parsed
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        parsed = int(text[:4])
        if 1800 <= parsed <= datetime.now().year + 20:
            return parsed
    return None


def _fetch_items(
    server: dict[str, Any],
    item_ids: list[str],
    fields: str,
    call_emby_api: Callable[..., tuple[bool, Any]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for batch in _chunks(item_ids):
        success, payload = call_emby_api(
            server,
            "Items",
            method="GET",
            params={"Ids": ",".join(batch), "Fields": fields, "Limit": len(batch)},
        )
        items = payload.get("Items") if success and isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("Id") or "").strip()
            if item_id:
                results[item_id] = item
    return results


def resolve_series_metadata(
    server: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    call_emby_api: Callable[..., tuple[bool, Any]],
) -> dict[str, tuple[str, int]]:
    """Return ``item_id -> (series_id, premiere_year)`` from series objects.

    Episode ``ProductionYear`` describes an episode or season and therefore
    cannot be used as the series premiere year.  The authoritative value is
    read from the referenced Emby Series object.
    """
    item_by_id = {
        str(item.get("Id") or item.get("item_id") or "").strip(): item
        for item in items
        if isinstance(item, dict)
        and str(item.get("Id") or item.get("item_id") or "").strip()
        and (
            str(item.get("Type") or item.get("media_type") or "").lower()
            == "episode"
            or bool(item.get("SeriesName") or item.get("series_name"))
        )
    }
    if not item_by_id:
        return {}

    missing_series_ids = [
        item_id
        for item_id, item in item_by_id.items()
        if not str(item.get("SeriesId") or item.get("series_id") or "").strip()
    ]
    if missing_series_ids:
        fetched = _fetch_items(
            server,
            missing_series_ids,
            "SeriesId,SeriesName,SeriesProductionYear,Type",
            call_emby_api,
        )
        for item_id, payload in fetched.items():
            item_by_id[item_id] = {**item_by_id[item_id], **payload}

    series_ids = sorted(
        {
            str(item.get("SeriesId") or item.get("series_id") or "").strip()
            for item in item_by_id.values()
            if str(item.get("SeriesId") or item.get("series_id") or "").strip()
        }
    )
    if not series_ids:
        return {}

    series_items = _fetch_items(
        server,
        series_ids,
        "ProductionYear,PremiereDate,Name,Type",
        call_emby_api,
    )
    series_years = {
        series_id: _year(payload.get("ProductionYear"))
        or _year(payload.get("PremiereDate"))
        for series_id, payload in series_items.items()
    }

    resolved: dict[str, tuple[str, int]] = {}
    for item_id, item in item_by_id.items():
        series_id = str(item.get("SeriesId") or item.get("series_id") or "").strip()
        premiere_year = series_years.get(series_id)
        if series_id and premiere_year is not None:
            resolved[item_id] = (series_id, premiere_year)
    return resolved


def resolve_item_titles(
    server: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    call_emby_api: Callable[..., tuple[bool, Any]],
) -> dict[str, tuple[str, int | None]]:
    """Resolve canonical localized titles for existing queued movies."""
    item_ids = sorted(
        {
            str(item.get("Id") or item.get("item_id") or "").strip()
            for item in items
            if isinstance(item, dict)
            and str(item.get("Id") or item.get("item_id") or "").strip()
        }
    )
    fetched = _fetch_items(
        server,
        item_ids,
        "Name,ProductionYear,Type",
        call_emby_api,
    )
    resolved: dict[str, tuple[str, int | None]] = {}
    for item_id, item in fetched.items():
        title = str(item.get("Name") or "").strip()
        if title:
            resolved[item_id] = (title, _year(item.get("ProductionYear")))
    return resolved


def apply_series_metadata(
    items: list[dict[str, Any]],
    resolved: dict[str, tuple[str, int]],
) -> None:
    """Apply resolved metadata in place before queue persistence."""
    for item in items:
        item_id = str(item.get("Id") or item.get("item_id") or "").strip()
        metadata = resolved.get(item_id)
        if metadata is None:
            continue
        series_id, year = metadata
        item["SeriesId"] = series_id
        item["SeriesProductionYear"] = year
        item["series_id"] = series_id
        item["series_year_resolved"] = True


def series_metadata_updates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project queue entries into deduplicated storage metadata updates."""
    updates: dict[tuple[Any, str], dict[str, Any]] = {}
    for item in items:
        if not item.get("series_year_resolved"):
            continue
        series_name = str(item.get("series_name") or "").strip()
        series_id = str(item.get("series_id") or "").strip()
        year = item.get("year")
        if not series_name or not series_id or year is None:
            continue
        key = (item.get("library_id"), series_name)
        updates[key] = {
            "library_id": item.get("library_id"),
            "series_name": series_name,
            "series_id": series_id,
            "year": year,
        }
    return list(updates.values())


def persist_series_metadata(
    storage: Any,
    server_id: str,
    scope: str,
    items: list[dict[str, Any]],
) -> None:
    """Persist resolved metadata when the storage backend supports it."""
    update = getattr(storage, "resolve_probe_series_metadata", None)
    metadata = series_metadata_updates(items)
    if callable(update) and metadata:
        update(server_id, scope=scope, metadata=metadata)
