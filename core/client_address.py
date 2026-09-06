"""Resolve client addresses only from explicitly trusted proxy headers."""

from __future__ import annotations

import ipaddress
import os
from typing import Any


_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def _trusted_proxy_networks(trust_proxy_env: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    cidr_env = trust_proxy_env.replace("_TRUST_PROXY_HEADERS", "_TRUSTED_PROXY_CIDRS")
    raw = os.environ.get(cidr_env) or os.environ.get("TRUSTED_PROXY_CIDRS") or ""
    networks = []
    for value in str(raw).replace(",", " ").split():
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _valid_address(value: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None


def resolve_client_address(
    request: Any,
    *,
    trust_proxy_env: str = "LOGIN_TRUST_PROXY_HEADERS",
) -> str:
    """Return a normalized address, ignoring forwarded headers by default."""
    trust_proxy = str(os.environ.get(trust_proxy_env, "")).strip().lower() in _TRUTHY_VALUES
    peer = _valid_address(getattr(getattr(request, "client", None), "host", None))
    trusted_networks = _trusted_proxy_networks(trust_proxy_env)
    peer_is_trusted = bool(
        trust_proxy
        and peer is not None
        and trusted_networks
        and any(peer in network for network in trusted_networks)
    )
    if peer_is_trusted:
        headers = getattr(request, "headers", {}) or {}
        real_ip = _valid_address(headers.get("X-Real-IP"))
        if real_ip is not None:
            return real_ip.compressed
        forwarded = [
            address
            for value in str(headers.get("X-Forwarded-For") or "").split(",")
            if (address := _valid_address(value)) is not None
        ]
        chain = [*forwarded, peer]
        for address in reversed(chain):
            if any(address in network for network in trusted_networks):
                continue
            return address.compressed
        if forwarded:
            return forwarded[0].compressed
    if peer is not None:
        return peer.compressed
    remote = _valid_address(getattr(request, "remote_addr", None))
    if remote is not None:
        return remote.compressed
    return "unknown"


__all__ = ["resolve_client_address"]
