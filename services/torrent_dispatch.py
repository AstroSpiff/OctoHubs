"""Dispatch torrent operations through the selected configured client."""

from __future__ import annotations

from typing import Any

from emby_runtime.api_clients_deluge import (
    ping_deluge,
    send_to_deluge,
    send_to_deluge_batch,
)
from emby_runtime.api_clients_qbittorrent import (
    send_to_qbittorrent,
    send_to_qbittorrent_batch,
)
from emby_runtime.api_clients_transmission import (
    ping_transmission,
    send_to_transmission,
    send_to_transmission_batch,
)
from emby_runtime.api_clients_ping import _ping_qbittorrent
from services.torrent_clients import select_torrent_client


def send_to_torrent_client(
    link: str,
    config: dict[str, Any],
    client_id: Any = None,
) -> tuple[bool, str]:
    profile = select_torrent_client(config, client_id)
    if not profile:
        return False, "Client torrent non disponibile o non abilitato"
    kind = profile["kind"]
    if kind == "qbittorrent":
        return send_to_qbittorrent(link, _qbittorrent_config(profile))
    if kind == "deluge":
        return send_to_deluge(link, profile)
    return send_to_transmission(link, profile)


def send_to_torrent_client_batch(
    links: list[str],
    config: dict[str, Any],
    client_id: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    profile = select_torrent_client(config, client_id)
    if not profile:
        return (
            False,
            "Client torrent non disponibile o non abilitato",
            {
                "sent": 0,
                "failed": [],
                "total": len(links),
            },
        )
    kind = profile["kind"]
    if kind == "qbittorrent":
        return send_to_qbittorrent_batch(links, _qbittorrent_config(profile))
    if kind == "deluge":
        return send_to_deluge_batch(links, profile)
    return send_to_transmission_batch(links, profile)


def ping_torrent_client(profile: dict[str, Any]) -> tuple[bool, str]:
    kind = profile.get("kind")
    if kind == "qbittorrent":
        return _ping_qbittorrent(_qbittorrent_config(profile))
    if kind == "deluge":
        return ping_deluge(profile)
    if kind == "transmission":
        return ping_transmission(profile)
    return False, "Tipo client torrent non supportato"


def _qbittorrent_config(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "QBITTORRENT_URL": profile.get("url"),
        "QBITTORRENT_USERNAME": profile.get("username"),
        "QBITTORRENT_PASSWORD": profile.get("password"),
    }


__all__ = [
    "ping_torrent_client",
    "send_to_torrent_client",
    "send_to_torrent_client_batch",
]
