"""Shared Event Bridge payload and secret helpers."""

from __future__ import annotations

import hmac
import os
from typing import Any, Mapping

from fastapi import HTTPException


EVENT_BRIDGE_SCHEMA = "octohubs.emby.event.v1"
EVENT_BRIDGE_BATCH_SCHEMA = "octohubs.emby.event_batch.v1"
LEGACY_EVENT_BRIDGE_SCHEMA = "octohub.emby.event.v1"
LEGACY_EVENT_BRIDGE_BATCH_SCHEMA = "octohub.emby.event_batch.v1"
EVENT_BRIDGE_SCHEMAS = {EVENT_BRIDGE_SCHEMA, LEGACY_EVENT_BRIDGE_SCHEMA}
EVENT_BRIDGE_BATCH_SCHEMAS = {EVENT_BRIDGE_BATCH_SCHEMA, LEGACY_EVENT_BRIDGE_BATCH_SCHEMA}


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


def validate_event_bridge_secret(headers: Mapping[str, Any]) -> None:
    expected = (os.getenv("WEBHOOK_SECRET") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET non configurato")
    provided = header_value(headers, "X-Webhook-Secret")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Event Bridge secret non valido")


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
