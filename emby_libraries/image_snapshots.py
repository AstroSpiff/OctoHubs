"""Snapshot builders for Emby image streaming and cache metadata."""

from __future__ import annotations

import requests

from core.config_manager import load_config


def _build_emby_image_cache_meta(server_id, item_id, image_type="Primary", max_width=None, max_height=None, tag=None, scope=None):
    """
    Build cache metadata for Emby images (ETag, Cache-Control).

    Returns:
        Tuple of (payload, etag, cache_control, status_code)
    """
    # Generate ETag from parameters
    etag_parts = [str(server_id), str(item_id), str(image_type or "Primary")]
    if max_width:
        etag_parts.append(f"w{max_width}")
    if max_height:
        etag_parts.append(f"h{max_height}")
    if tag:
        etag_parts.append(f"t{tag}")

    etag = f'"{"-".join(etag_parts)}"'
    cache_control = "public, max-age=31536000, immutable"  # 1 year cache

    return None, etag, cache_control, 200


def _build_emby_image_stream(server_id, item_id, image_type="Primary", max_width=None, max_height=None, tag=None, scope=None):
    from emby_libraries.snapshots import _resolve_emby_server

    if not server_id or not item_id:
        return None, None, {"success": False, "message": "Parametri mancanti"}, 400

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

    params = {"api_key": token}
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

    try:
        response = requests.get(
            url,
            headers={"X-Emby-Token": token, "Accept": "image/*"},
            params=params,
            stream=True,
            timeout=15
        )
        response.raise_for_status()
    except requests.RequestException:
        return None, None, {"success": False, "message": "Errore caricamento immagine"}, 502

    content_type = response.headers.get("Content-Type") or "image/jpeg"

    def iter_stream():
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            response.close()

    return iter_stream(), content_type, None, 200
