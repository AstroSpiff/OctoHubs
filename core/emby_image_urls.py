"""Build client-facing Emby image URLs without exposing server credentials."""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode


def build_emby_image_proxy_url(
    server_id: Any,
    item_id: Any,
    *,
    image_type: str = "Primary",
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    tag: Any = None,
) -> str:
    """Return an authenticated application proxy URL for one Emby image."""
    normalized_server_id = str(server_id or "").strip()
    normalized_item_id = str(item_id or "").strip()
    if not normalized_server_id or not normalized_item_id:
        return ""

    query: Dict[str, Any] = {
        "server_id": normalized_server_id,
        "item_id": normalized_item_id,
        "type": image_type,
    }
    if max_width:
        query["max_width"] = int(max_width)
    if max_height:
        query["max_height"] = int(max_height)
    normalized_tag = str(tag or "").strip()
    if normalized_tag:
        query["tag"] = normalized_tag
    return f"/api/v1/emby/image?{urlencode(query)}"


def build_latest_emby_image_urls(
    server_id: Any,
    item_id: Any,
    *,
    primary_tag: Any = None,
) -> Dict[str, str]:
    """Build every Emby image field exposed by Latest Publications."""
    common = {"server_id": server_id, "item_id": item_id}
    return {
        "image_url": build_emby_image_proxy_url(
            **common,
            image_type="Primary",
            max_width=240,
            tag=primary_tag,
        ),
        "poster_url": build_emby_image_proxy_url(
            **common,
            image_type="Primary",
            max_width=720,
            tag=primary_tag,
        ),
        "backdrop_url": build_emby_image_proxy_url(
            **common,
            image_type="Backdrop",
            max_width=1280,
        ),
        "banner_url": build_emby_image_proxy_url(
            **common,
            image_type="Banner",
            max_width=1280,
        ),
        "thumb_url": build_emby_image_proxy_url(
            **common,
            image_type="Thumb",
            max_width=1280,
        ),
        "logo_url": build_emby_image_proxy_url(
            **common,
            image_type="Logo",
            max_width=720,
        ),
    }


__all__ = ["build_emby_image_proxy_url", "build_latest_emby_image_urls"]
