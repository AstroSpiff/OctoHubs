"""Source-network policy for Event Bridge HTTP and WebSocket connections."""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any, Mapping

from fastapi import HTTPException

from emby_runtime.event_bridge_payloads import header_value


logger = logging.getLogger(__name__)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def validate_event_bridge_source(connection: Any) -> None:
    """Reject Event Bridge callers outside the optional IP/CIDR allowlist."""
    raw_allowlist = (os.getenv("WEBHOOK_IP_WHITELIST") or "").strip()
    if not raw_allowlist:
        return

    try:
        networks = _parse_allowlist(raw_allowlist)
    except ValueError as exc:
        logger.error("Configurazione WEBHOOK_IP_WHITELIST non valida: %s", exc)
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
    if _trust_proxy_headers():
        headers: Mapping[str, Any] = getattr(connection, "headers", {}) or {}
        proxy_ip = header_value(headers, "X-Real-IP")
        if proxy_ip:
            return proxy_ip, "proxy"

    client = getattr(connection, "client", None)
    host = getattr(client, "host", "") if client is not None else ""
    if not host and isinstance(client, (tuple, list)) and client:
        host = client[0]
    return str(host or "").strip(), "diretto"


def _trust_proxy_headers() -> bool:
    return (os.getenv("WEBHOOK_TRUST_PROXY_HEADERS") or "").strip().lower() in _TRUTHY_VALUES
