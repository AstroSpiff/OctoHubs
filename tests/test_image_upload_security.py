"""Regression tests for stored-image validation and same-origin XSS boundaries."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace
import zlib

from fastapi import UploadFile
from PIL import Image
import pytest
from starlette.datastructures import Headers

from core.image_uploads import (
    ImageUploadError,
    MAX_IMAGE_UPLOAD_BYTES,
    sanitize_image_bytes,
)
from emby_collections import routes as collection_routes
from emby_users.icon_manager import IconManager


def _image_bytes(image_format: str = "PNG", *, with_metadata: bool = False) -> bytes:
    mode = "RGBA" if image_format in {"PNG", "WEBP"} else "RGB"
    color = (20, 80, 160, 180) if mode == "RGBA" else (20, 80, 160)
    image = Image.new(mode, (4, 3), color)
    output = BytesIO()
    options = {}
    if with_metadata:
        exif = Image.Exif()
        exif[0x010E] = "untrusted metadata"
        options["exif"] = exif
    image.save(output, format=image_format, **options)
    return output.getvalue()


def _upload(data: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.parametrize(
    "image_format,mime_type",
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
def test_safe_raster_formats_are_decoded_and_reencoded(image_format, mime_type):
    safe = sanitize_image_bytes(_image_bytes(image_format, with_metadata=True))

    assert safe.mime_type == mime_type
    assert (safe.width, safe.height) == (4, 3)
    with Image.open(BytesIO(safe.data)) as decoded:
        assert decoded.format == image_format
        assert not decoded.getexif()


@pytest.mark.parametrize(
    "payload",
    [
        b"<html><script>top.location='https://attacker.invalid'</script></html>",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    ],
)
def test_active_content_is_rejected(payload):
    with pytest.raises(ImageUploadError, match="non supportato|non valido"):
        sanitize_image_bytes(payload)


def test_active_trailing_polyglot_content_is_removed_by_reencoding():
    original = _image_bytes("PNG")
    safe = sanitize_image_bytes(original + b"<script>alert(1)</script>")

    assert b"<script" not in safe.data
    assert len(safe.data) < len(original + b"<script>alert(1)</script>")


def test_upload_byte_limit_is_enforced_before_decoding():
    with pytest.raises(ImageUploadError, match="Limite 5 MB"):
        sanitize_image_bytes(b"x" * (MAX_IMAGE_UPLOAD_BYTES + 1))


def test_pixel_limit_rejects_compressed_dimension_bombs():
    payload = bytearray(_image_bytes("PNG"))
    ihdr_data = bytes(payload[16:29])
    oversized_ihdr = (5000).to_bytes(4, "big") + (3000).to_bytes(4, "big") + ihdr_data[8:]
    payload[16:29] = oversized_ihdr
    payload[29:33] = zlib.crc32(b"IHDR" + oversized_ihdr).to_bytes(4, "big")

    with pytest.raises(ImageUploadError, match="Risoluzione"):
        sanitize_image_bytes(bytes(payload))


class _IconStorage:
    def __init__(self):
        self.saved = []
        self.stored = None

    def save_icon_rule(self, profile_id, column_key, path, data, mime_type):
        self.saved.append((profile_id, column_key, path, data, mime_type))

    def get_icon_rule_data(self, _profile_id, _column_key):
        return self.stored

    def get_icon_bindings(self):
        return []

    def get_icon_rules(self):
        return []


def _icon_manager(storage: _IconStorage) -> IconManager:
    return IconManager(
        storage,
        get_users_dashboard_data=lambda: {"groups": []},
        get_server_by_id=lambda _server_id: None,
    )


def test_user_icon_uses_decoded_content_instead_of_client_filename_or_mime():
    storage = _IconStorage()
    manager = _icon_manager(storage)

    manager.save_icon_rule(
        "profile-1",
        "server-1",
        _upload(_image_bytes("PNG"), "payload.svg", "image/svg+xml"),
    )

    assert storage.saved[0][4] == "image/png"
    with Image.open(BytesIO(storage.saved[0][3])) as decoded:
        assert decoded.format == "PNG"


def test_user_icon_rejects_svg_without_persisting_or_syncing():
    storage = _IconStorage()
    manager = _icon_manager(storage)

    with pytest.raises(ImageUploadError):
        manager.save_icon_rule(
            "profile-1",
            "server-1",
            _upload(b"<svg><script>alert(1)</script></svg>", "icon.png", "image/png"),
        )

    assert storage.saved == []


def test_legacy_active_user_icon_is_not_returned():
    storage = _IconStorage()
    storage.stored = (b"<html><script>alert(1)</script></html>", "text/html")

    assert _icon_manager(storage).get_icon_image("profile-1", "server-1") is None


def test_collection_upload_rejects_svg_before_persistence():
    response = asyncio.run(
        collection_routes.api_emby_collections_upload_poster(
            "collection-1",
            _upload(b"<svg><script>alert(1)</script></svg>", "poster.svg", "image/svg+xml"),
            user=SimpleNamespace(role="admin"),
        )
    )

    assert response.status_code == 400
    assert json.loads(response.body)["success"] is False


def test_collection_upload_stores_canonical_mime_from_decoded_content(monkeypatch):
    saved = []
    backend = SimpleNamespace(
        get_emby_collection_definition=lambda _collection_id: {"id": "collection-1"},
    )
    monkeypatch.setattr(collection_routes, "_ensure_db_backend", lambda: backend)
    monkeypatch.setattr(
        collection_routes,
        "save_collection_poster_blob",
        lambda collection_id, mime_type, data: saved.append((collection_id, mime_type, data)),
    )
    monkeypatch.setattr(collection_routes, "publish_application_event", lambda *_args: None)

    response = asyncio.run(
        collection_routes.api_emby_collections_upload_poster(
            "collection-1",
            _upload(_image_bytes("JPEG"), "payload.html", "text/html"),
            user=SimpleNamespace(role="admin"),
        )
    )

    assert response == {"success": True}
    assert saved[0][:2] == ("collection-1", "image/jpeg")


def test_legacy_active_collection_image_is_not_served(monkeypatch):
    monkeypatch.setattr(
        collection_routes,
        "get_collection_poster_blob",
        lambda _collection_id: {
            "mime_type": "text/html",
            "data": b"<html><script>alert(1)</script></html>",
        },
    )

    response = asyncio.run(
        collection_routes.api_emby_collections_get_poster(
            "collection-1",
            user=SimpleNamespace(role="admin"),
        )
    )

    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"


def test_collection_image_response_uses_decoded_mime_and_nosniff(monkeypatch):
    monkeypatch.setattr(
        collection_routes,
        "get_collection_backdrop_blob",
        lambda _collection_id: {
            "mime_type": "text/html",
            "data": _image_bytes("WEBP"),
        },
    )

    response = asyncio.run(
        collection_routes.api_emby_collections_get_backdrop(
            "collection-1",
            user=SimpleNamespace(role="admin"),
        )
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"
