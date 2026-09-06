"""Prepare Latest Publication images for safe Telegram delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlsplit

import requests

from core.image_uploads import (
    ImageUploadError,
    MAX_IMAGE_UPLOAD_BYTES,
    sanitize_image_bytes,
)
from core.utils import find_server_by_id, get_emby_servers


_EMBY_IMAGE_FIELDS = {
    "image_url": ("Primary", 240),
    "poster_url": ("Primary", 720),
    "backdrop_url": ("Backdrop", 1280),
    "banner_url": ("Banner", 1280),
    "thumb_url": ("Thumb", 1280),
    "logo_url": ("Logo", 720),
}
_SECRET_QUERY_KEYS = frozenset(
    {"api_key", "apikey", "token", "access_token", "x-emby-token"}
)
_EXTENSION_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@dataclass(frozen=True)
class TelegramPhotoUpload:
    content: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class PreparedTelegramPhoto:
    url: str = ""
    upload: Optional[TelegramPhotoUpload] = None
    error: str = ""


def _selected_emby_image_field(image_url: str, item: Dict[str, Any]) -> Optional[str]:
    for field in _EMBY_IMAGE_FIELDS:
        candidate = str(item.get(field) or "").strip()
        if candidate and candidate == image_url:
            return field
    return None


def _safe_external_image_url(image_url: str) -> bool:
    try:
        parsed = urlsplit(image_url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    return not query_keys.intersection(_SECRET_QUERY_KEYS)


def _download_emby_image(
    item: Dict[str, Any],
    config: Dict[str, Any],
    image_field: str,
) -> PreparedTelegramPhoto:
    server_id = str(item.get("server_id") or "").strip()
    item_id = str(item.get("item_id") or "").strip()
    server = find_server_by_id(get_emby_servers(config), server_id)
    base_url = str((server or {}).get("url") or "").strip().rstrip("/")
    token = str((server or {}).get("api_key") or "").strip()
    if not server or not base_url or not token or not item_id:
        return PreparedTelegramPhoto(error="Immagine Emby non disponibile")

    image_type, max_width = _EMBY_IMAGE_FIELDS[image_field]
    params: Dict[str, Any] = {"maxWidth": max_width, "quality": 90}
    primary_tag = str(item.get("image_tag") or "").strip()
    if image_type == "Primary" and primary_tag:
        params["tag"] = primary_tag

    response = None
    try:
        response = requests.get(
            f"{base_url}/Items/{quote(item_id, safe='')}/Images/{image_type}",
            headers={"X-Emby-Token": token, "Accept": "image/*"},
            params=params,
            stream=True,
            allow_redirects=False,
            timeout=(5, 15),
        )
        response.raise_for_status()
        if response.is_redirect or response.is_permanent_redirect:
            return PreparedTelegramPhoto(error="Immagine Emby non disponibile")

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_IMAGE_UPLOAD_BYTES:
            return PreparedTelegramPhoto(error="Immagine Emby troppo grande")

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_UPLOAD_BYTES:
                return PreparedTelegramPhoto(error="Immagine Emby troppo grande")
            chunks.append(chunk)
        sanitized = sanitize_image_bytes(b"".join(chunks))
    except (requests.RequestException, ImageUploadError, TypeError, ValueError):
        return PreparedTelegramPhoto(error="Immagine Emby non disponibile")
    finally:
        if response is not None:
            response.close()

    extension = _EXTENSION_BY_MIME[sanitized.mime_type]
    return PreparedTelegramPhoto(
        upload=TelegramPhotoUpload(
            content=sanitized.data,
            content_type=sanitized.mime_type,
            filename=f"publication.{extension}",
        )
    )


def prepare_telegram_photo(
    image_url: Any,
    item: Dict[str, Any],
    config: Dict[str, Any],
) -> PreparedTelegramPhoto:
    """Use an upload for Emby images and a secret-free URL for external images."""
    normalized_url = str(image_url or "").strip()
    if not normalized_url:
        return PreparedTelegramPhoto()

    image_field = _selected_emby_image_field(normalized_url, item)
    if image_field:
        return _download_emby_image(item, config, image_field)
    if _safe_external_image_url(normalized_url):
        return PreparedTelegramPhoto(url=normalized_url)
    return PreparedTelegramPhoto(error="URL immagine non valido")


def send_prepared_telegram_photo(
    api_request: Callable[..., Tuple[bool, str, Dict[str, Any]]],
    bot_token: str,
    chat_id: Any,
    caption: str,
    photo: PreparedTelegramPhoto,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Send one prepared photo without putting Emby credentials in its URL."""
    payload: Dict[str, Any] = {"chat_id": chat_id}
    normalized_caption = caption.strip()
    if normalized_caption:
        payload["caption"] = normalized_caption[:1024]
        payload["parse_mode"] = "HTML"
    if photo.upload:
        upload = photo.upload
        return api_request(
            bot_token,
            "sendPhoto",
            payload,
            files={
                "photo": (upload.filename, upload.content, upload.content_type)
            },
        )
    payload["photo"] = photo.url
    return api_request(bot_token, "sendPhoto", payload)


__all__ = [
    "PreparedTelegramPhoto",
    "TelegramPhotoUpload",
    "prepare_telegram_photo",
    "send_prepared_telegram_photo",
]
