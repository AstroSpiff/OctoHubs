"""Shared URL builders for external API clients."""

from __future__ import annotations


def build_service_api_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    endpoint = str(path or "").strip()
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
    return f"{base}{endpoint}"


def build_jellyseerr_api_url(config: dict, path: str) -> str:
    return build_service_api_url((config or {}).get("JELLYSEERR_URL") or "", path)
