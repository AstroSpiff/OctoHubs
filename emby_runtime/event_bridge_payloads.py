"""Shared Event Bridge payload and secret helpers."""

from __future__ import annotations

from typing import Any, Mapping


EVENT_BRIDGE_SCHEMA = "octohubs.emby.event.v1"
EVENT_BRIDGE_BATCH_SCHEMA = "octohubs.emby.event_batch.v1"
EVENT_BRIDGE_SCHEMAS = {EVENT_BRIDGE_SCHEMA}
EVENT_BRIDGE_BATCH_SCHEMAS = {EVENT_BRIDGE_BATCH_SCHEMA}


def header_value(headers: Mapping[str, Any], name: str) -> str:
    """Return a header value regardless of mapping case behavior."""
    try:
        return str(headers.get(name) or headers.get(name.lower()) or "").strip()
    except Exception:
        normalized = name.lower()
        for key, value in dict(headers or {}).items():
            if str(key).lower() == normalized:
                return str(value or "").strip()
    return ""


def event_bridge_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") not in EVENT_BRIDGE_BATCH_SCHEMAS:
        return [payload]
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def mark_event_bridge_transport(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    """Return a shallow copy annotated with the transport used to reach OctoHubs."""
    clean_transport = str(transport or "").strip()
    if payload.get("schema") not in EVENT_BRIDGE_BATCH_SCHEMAS:
        marked = dict(payload)
        marked["_eventBridgeTransport"] = clean_transport
        return marked

    marked = dict(payload)
    events = payload.get("events")
    if isinstance(events, list):
        marked["events"] = [
            {**event, "_eventBridgeTransport": clean_transport}
            if isinstance(event, dict)
            else event
            for event in events
        ]
    marked["_eventBridgeTransport"] = clean_transport
    return marked
