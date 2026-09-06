"""Authentication and immutable server identity for Event Bridge transports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException

from core.storage import StorageError
from emby_runtime.event_bridge_credentials import (
    event_bridge_credential_generation,
    event_bridge_credential_generation_is_current,
)
from emby_runtime.event_bridge_payloads import event_bridge_payloads, header_value


EVENT_BRIDGE_SERVER_ID_HEADER = "X-OctoHubs-Server-Id"


@dataclass(frozen=True)
class EventBridgePrincipal:
    server_id: str
    credential_generation: str = ""


def authenticate_event_bridge(headers: Mapping[str, Any]) -> EventBridgePrincipal:
    """Authenticate a server-specific credential; no shared-secret fallback exists."""
    server_id = header_value(headers, EVENT_BRIDGE_SERVER_ID_HEADER)
    credential = header_value(headers, "X-Webhook-Secret")
    try:
        generation = event_bridge_credential_generation(server_id, credential)
    except StorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="Credenziali Event Bridge non disponibili",
        ) from exc
    if not generation:
        raise HTTPException(status_code=403, detail="Credenziale Event Bridge non valida")
    return EventBridgePrincipal(server_id=server_id, credential_generation=generation)


def event_bridge_principal_is_current(principal: EventBridgePrincipal) -> bool:
    """Return whether a long-lived transport still owns the persisted generation."""
    try:
        return event_bridge_credential_generation_is_current(
            principal.server_id,
            principal.credential_generation,
        )
    except StorageError:
        return False


def validate_event_bridge_payload_identity(
    principal: EventBridgePrincipal,
    payload: dict[str, Any],
) -> None:
    """Require every payload identity to match the authenticated server."""
    identities = [_payload_server_id(item) for item in event_bridge_payloads(payload)]
    if not identities or any(not server_id for server_id in identities):
        raise HTTPException(status_code=403, detail="Identità server Event Bridge mancante")
    if any(server_id != principal.server_id for server_id in identities):
        raise HTTPException(status_code=403, detail="Identità server Event Bridge non valida")


def _payload_server_id(payload: dict[str, Any]) -> str:
    server = payload.get("server")
    if isinstance(server, dict):
        server_id = str(server.get("id") or "").strip()
        if server_id:
            return server_id
    return str(payload.get("serverId") or "").strip()
