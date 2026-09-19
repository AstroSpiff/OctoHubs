"""Canonical torrent-client configuration and dispatch selection."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import uuid4

from core.configuration_redaction import public_connection_url, submitted_connection_url


TorrentClientKind = Literal["qbittorrent", "deluge", "transmission"]
SUPPORTED_TORRENT_CLIENTS: tuple[TorrentClientKind, ...] = (
    "qbittorrent",
    "deluge",
    "transmission",
)
MAX_TORRENT_CLIENTS = 10
_CLIENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_LEGACY_QBITTORRENT_ID = "qbittorrent-legacy"


def torrent_client_profiles(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized profiles, projecting legacy qBittorrent settings once."""
    source = config if isinstance(config, dict) else {}
    stored = source.get("TORRENT_CLIENTS")
    if isinstance(stored, list) and stored:
        return _normalize_stored_profiles(stored)

    legacy = _legacy_qbittorrent_profile(source)
    return [legacy] if legacy else []


def public_torrent_client_profiles(
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Expose safe client metadata without reusable credentials."""
    return [
        {
            "id": profile["id"],
            "name": profile["name"],
            "kind": profile["kind"],
            "url": public_connection_url(profile.get("url")),
            "username": str(profile.get("username") or ""),
            "password_configured": bool(profile.get("password")),
            "enabled": bool(profile.get("enabled")),
            "is_default": bool(profile.get("is_default")),
            "configured": torrent_client_configured(profile),
        }
        for profile in torrent_client_profiles(config)
    ]


def enabled_torrent_clients(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        profile
        for profile in torrent_client_profiles(config)
        if profile.get("enabled") and torrent_client_configured(profile)
    ]


def select_torrent_client(
    config: dict[str, Any] | None,
    client_id: Any = None,
) -> dict[str, Any] | None:
    """Resolve an explicitly selected enabled client or the configured default."""
    enabled = enabled_torrent_clients(config)
    requested = str(client_id or "").strip()
    if requested:
        return next((item for item in enabled if item["id"] == requested), None)
    return next(
        (item for item in enabled if item.get("is_default")),
        enabled[0] if len(enabled) == 1 else None,
    )


def normalize_submitted_torrent_clients(
    submitted: Any,
    current_config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Validate a full replacement while preserving omitted secrets by stable id."""
    if not isinstance(submitted, list):
        raise ValueError("Elenco client torrent non valido")
    if len(submitted) > MAX_TORRENT_CLIENTS:
        raise ValueError(
            f"Sono consentiti al massimo {MAX_TORRENT_CLIENTS} client torrent"
        )

    existing_by_id = {
        profile["id"]: profile for profile in torrent_client_profiles(current_config)
    }
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for raw in submitted:
        profile = _normalize_submitted_profile(raw, existing_by_id, seen_ids, seen_names)
        normalized.append(profile)
        seen_ids.add(profile["id"])
        seen_names.add(profile["name"].casefold())

    enabled = [profile for profile in normalized if profile["enabled"]]
    defaults = [profile for profile in enabled if profile["is_default"]]
    if len(defaults) > 1:
        raise ValueError("Può esistere un solo client torrent predefinito")
    if enabled and not defaults:
        enabled[0]["is_default"] = True
    return normalized


def _normalize_submitted_profile(
    raw: Any,
    existing_by_id: dict[str, dict[str, Any]],
    seen_ids: set[str],
    seen_names: set[str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Profilo client torrent non valido")
    client_id = str(raw.get("id") or uuid4()).strip()
    if not _CLIENT_ID_PATTERN.fullmatch(client_id) or client_id in seen_ids:
        raise ValueError("Identificatore client torrent non valido o duplicato")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in SUPPORTED_TORRENT_CLIENTS:
        raise ValueError("Tipo di client torrent non supportato")
    name = str(raw.get("name") or _default_client_name(kind)).strip()[:80]
    if not name or name.casefold() in seen_names:
        raise ValueError("Ogni client torrent deve avere un nome univoco")

    existing = existing_by_id.get(client_id, {})
    clear_password = raw.get("clear_password") is True
    new_password = str(raw.get("password") or "")
    profile = {
        "id": client_id,
        "name": name,
        "kind": kind,
        "url": submitted_connection_url(raw.get("url"), existing.get("url")),
        "username": str(
            raw.get("username")
            if "username" in raw
            else existing.get("username") or ""
        ).strip(),
        "password": (
            ""
            if clear_password
            else new_password or str(existing.get("password") or "")
        ),
        "enabled": raw.get("enabled") is True,
        "is_default": raw.get("is_default") is True,
    }
    if profile["is_default"] and not profile["enabled"]:
        raise ValueError("Il client torrent predefinito deve essere abilitato")
    return profile


def torrent_client_configured(profile: dict[str, Any]) -> bool:
    kind = profile.get("kind")
    if kind == "qbittorrent":
        return bool(
            profile.get("url") and profile.get("username") and profile.get("password")
        )
    if kind == "deluge":
        return bool(profile.get("url") and profile.get("password"))
    if kind == "transmission":
        return bool(profile.get("url"))
    return False


def _normalize_stored_profiles(profiles: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in profiles[:MAX_TORRENT_CLIENTS]:
        if not isinstance(raw, dict):
            continue
        client_id = str(raw.get("id") or "").strip()
        kind = str(raw.get("kind") or "").strip().lower()
        if (
            not _CLIENT_ID_PATTERN.fullmatch(client_id)
            or client_id in seen_ids
            or kind not in SUPPORTED_TORRENT_CLIENTS
        ):
            continue
        normalized.append(
            {
                "id": client_id,
                "name": str(raw.get("name") or _default_client_name(kind)).strip()[:80],
                "kind": kind,
                "url": str(raw.get("url") or "").strip(),
                "username": str(raw.get("username") or "").strip(),
                "password": str(raw.get("password") or ""),
                "enabled": raw.get("enabled") is True,
                "is_default": raw.get("is_default") is True,
            }
        )
        seen_ids.add(client_id)
    enabled = [profile for profile in normalized if profile["enabled"]]
    defaults = [profile for profile in enabled if profile["is_default"]]
    if enabled and len(defaults) != 1:
        for profile in normalized:
            profile["is_default"] = profile is enabled[0]
    return normalized


def _legacy_qbittorrent_profile(source: dict[str, Any]) -> dict[str, Any] | None:
    url = str(source.get("QBITTORRENT_URL") or "").strip()
    username = str(source.get("QBITTORRENT_USERNAME") or "").strip()
    password = str(source.get("QBITTORRENT_PASSWORD") or "")
    if not (url or username or password):
        return None
    return {
        "id": _LEGACY_QBITTORRENT_ID,
        "name": "qBittorrent",
        "kind": "qbittorrent",
        "url": url,
        "username": username,
        "password": password,
        "enabled": True,
        "is_default": True,
    }


def _default_client_name(kind: str) -> str:
    return {
        "qbittorrent": "qBittorrent",
        "deluge": "Deluge",
        "transmission": "Transmission",
    }.get(kind, "Client torrent")


__all__ = [
    "MAX_TORRENT_CLIENTS",
    "SUPPORTED_TORRENT_CLIENTS",
    "enabled_torrent_clients",
    "normalize_submitted_torrent_clients",
    "public_torrent_client_profiles",
    "select_torrent_client",
    "torrent_client_configured",
    "torrent_client_profiles",
]
