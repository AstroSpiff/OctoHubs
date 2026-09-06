"""Snapshot builders for Emby image streaming and cache metadata."""

from __future__ import annotations

import hashlib
import json
import re

import requests

from core.config_manager import load_config
from core.http_response_limits import close_response_safely


_ALLOWED_IMAGE_TYPES = frozenset({"Primary", "Backdrop", "Banner", "Thumb", "Logo"})
_ALLOWED_SCOPES = frozenset({"", "item", "user"})
_ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
_EMBY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _validated_dimension(value):
    if value in (None, ""):
        return None
    try:
        dimension = int(value)
    except (TypeError, ValueError):
        return None
    return dimension if 1 <= dimension <= 4096 else None


def _validate_image_request(item_id, image_type, scope, max_width, max_height, tag):
    normalized_item_id = str(item_id or "").strip()
    normalized_type = str(image_type or "Primary").strip()
    normalized_scope = str(scope or "").strip().lower()
    normalized_tag = str(tag or "").strip()
    if not _EMBY_ID_PATTERN.fullmatch(normalized_item_id):
        return None
    if normalized_type not in _ALLOWED_IMAGE_TYPES or normalized_scope not in _ALLOWED_SCOPES:
        return None
    width = _validated_dimension(max_width)
    height = _validated_dimension(max_height)
    if max_width not in (None, "") and width is None:
        return None
    if max_height not in (None, "") and height is None:
        return None
    if len(normalized_tag) > 255 or any(ord(character) < 32 or ord(character) == 127 for character in normalized_tag):
        return None
    return normalized_item_id, normalized_type, normalized_scope, width, height, normalized_tag


def _build_emby_image_cache_meta(server_id, item_id, image_type="Primary", max_width=None, max_height=None, tag=None, scope=None):
    """
    Build cache metadata for Emby images (ETag, Cache-Control).

    Returns:
        Tuple of (payload, etag, cache_control, status_code)
    """
    cache_control = "private, max-age=3600, must-revalidate"
    normalized_server_id = str(server_id or "").strip()
    if (
        not normalized_server_id
        or len(normalized_server_id) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized_server_id)
    ):
        return None, None, cache_control, 400
    validated = _validate_image_request(
        item_id,
        image_type,
        scope,
        max_width,
        max_height,
        tag,
    )
    if validated is None:
        return None, None, cache_control, 400
    normalized_item_id, normalized_type, normalized_scope, width, height, normalized_tag = validated
    canonical = json.dumps(
        [
            normalized_server_id,
            normalized_item_id,
            normalized_type,
            normalized_scope,
            width,
            height,
            normalized_tag,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    etag = f'"{hashlib.sha256(canonical).hexdigest()}"'

    return None, etag, cache_control, 200


def _build_emby_image_stream(server_id, item_id, image_type="Primary", max_width=None, max_height=None, tag=None, scope=None):
    from emby_libraries.snapshots import _resolve_emby_server

    if not server_id or not item_id:
        return None, None, {"success": False, "message": "Parametri mancanti"}, 400

    validated = _validate_image_request(
        item_id,
        image_type,
        scope,
        max_width,
        max_height,
        tag,
    )
    if not validated:
        return None, None, {"success": False, "message": "Parametri immagine non validi"}, 400
    item_id, image_type, scope, max_width, max_height, tag = validated

    config, is_valid = load_config()
    if not is_valid or not config:
        return None, None, {"success": False, "message": "Config non valida"}, 400
    server = _resolve_emby_server(config, server_id)
    if not server:
        return None, None, {"success": False, "message": "Server non trovato"}, 404

    base_url = (server.get("url") or "").strip().rstrip("/")
    token = (server.get("api_key") or "").strip()
    if not base_url or not token:
        return None, None, {"success": False, "message": "Credenziali Emby mancanti"}, 400

    params = {}
    if max_width:
        params["maxWidth"] = max_width
    if max_height:
        params["maxHeight"] = max_height
    if tag:
        params["tag"] = tag

    if scope == "user":
        url = f"{base_url}/Users/{item_id}/Images/{image_type}"
    else:
        url = f"{base_url}/Items/{item_id}/Images/{image_type}"

    response = None
    try:
        response = requests.get(
            url,
            headers={"X-Emby-Token": token, "Accept": "image/*"},
            params=params,
            stream=True,
            allow_redirects=False,
            timeout=15,
        )
        response.raise_for_status()
        if response.is_redirect or response.is_permanent_redirect:
            response.close()
            return None, None, {"success": False, "message": "Risposta immagine non valida"}, 502
    except requests.RequestException:
        close_response_safely(response)
        return None, None, {"success": False, "message": "Errore caricamento immagine"}, 502

    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        response.close()
        return None, None, {"success": False, "message": "Risposta immagine non valida"}, 502
    try:
        content_length = int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > _MAX_IMAGE_BYTES:
        response.close()
        return None, None, {"success": False, "message": "Immagine troppo grande"}, 502

    content = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > _MAX_IMAGE_BYTES:
                return None, None, {"success": False, "message": "Immagine troppo grande"}, 502
    except requests.RequestException:
        return None, None, {"success": False, "message": "Errore caricamento immagine"}, 502
    finally:
        response.close()

    # Validation is complete before the route commits HTTP 200.
    return iter((bytes(content),)), content_type, None, 200
