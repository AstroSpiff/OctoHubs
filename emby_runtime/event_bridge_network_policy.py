"""Source-network policy for Event Bridge HTTP and WebSocket connections."""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any

from fastapi import HTTPException

from core.client_address import resolve_client_address
from core.log_sanitization import format_exception_for_log


logger = logging.getLogger(__name__)

def validate_event_bridge_source(connection: Any) -> None:
    """Reject Event Bridge callers outside the optional IP/CIDR allowlist."""
    raw_allowlist = (os.getenv("WEBHOOK_IP_WHITELIST") or "").strip()
    if not raw_allowlist:
        return

    try:
        networks = _parse_allowlist(raw_allowlist)
    except ValueError as exc:
        logger.error("Configurazione WEBHOOK_IP_WHITELIST non valida:\n%s", format_exception_for_log(exc))
        raise HTTPException(
            status_code=503,
            detail="WEBHOOK_IP_WHITELIST non valida",
        ) from exc

    peer_value, peer_source = _peer_value(connection)
    try:
        peer = ipaddress.ip_address(peer_value)
    except ValueError as exc:
        logger.warning(
            "Connessione Event Bridge rifiutata: indirizzo %s assente o non valido",
            peer_source,
        )
        raise HTTPException(
            status_code=403,
            detail="Sorgente Event Bridge non consentita",
        ) from exc

    candidates = [peer]
    if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped is not None:
        candidates.append(peer.ipv4_mapped)
    if any(
        candidate.version == network.version and candidate in network
        for candidate in candidates
        for network in networks
    ):
        return

    logger.warning(
        "Connessione Event Bridge rifiutata: indirizzo %s IPv%s fuori dalla allowlist",
        peer_source,
        peer.version,
    )
    raise HTTPException(
        status_code=403,
        detail="Sorgente Event Bridge non consentita",
    )


def event_bridge_peer_key(connection: Any) -> str:
    """Return the same peer identity used by the source policy for pre-auth limits."""
    value, _source = _peer_value(connection)
    return value or "unknown"


def _parse_allowlist(raw_allowlist: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    entries = [entry.strip() for entry in raw_allowlist.split(",")]
    networks = []
    for position, entry in enumerate(entries, start=1):
        if not entry:
            raise ValueError(f"voce {position} vuota")
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise ValueError(f"voce {position} non valida") from exc
    return tuple(networks)


def _peer_value(connection: Any) -> tuple[str, str]:
    """Resolve proxy headers only when their direct peer is an allowed proxy."""
    return resolve_client_address(
        connection,
        trust_proxy_env="WEBHOOK_TRUST_PROXY_HEADERS",
    ), "risolto"
