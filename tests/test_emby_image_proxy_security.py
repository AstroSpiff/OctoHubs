"""Security boundaries for the authenticated Emby image proxy."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from emby_libraries.image_snapshots import (
    _MAX_IMAGE_BYTES,
    _build_emby_image_cache_meta,
    _build_emby_image_stream,
)


class _Response:
    def __init__(self, *, content_type="image/jpeg", content=b"image", status=200):
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }
        self.content = content
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self.is_permanent_redirect = status in {301, 308}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError("provider failed")

    def iter_content(self, chunk_size):
        assert chunk_size > 0
        yield self.content

    def close(self):
        self.closed = True


def _config():
    return {
        "EMBY": {
            "SERVERS": [
                {
                    "id": "server-a",
                    "url": "https://emby.example.test",
                    "api_key": "CANARY_EMBY_SECRET",
                }
            ]
        }
    }


@pytest.mark.parametrize(
    "item_id,image_type,scope",
    [
        ("x", "../../../System/Info", None),
        ("../System", "Primary", None),
        ("movie/1", "Primary", None),
        ("movie-1", "Primary", "../../Users"),
        ("movie-1", "NotAnImage", None),
    ],
)
def test_proxy_rejects_path_traversal_and_unknown_image_routes(
    item_id,
    image_type,
    scope,
):
    with patch("emby_libraries.image_snapshots.load_config", return_value=(_config(), True)), patch(
        "emby_libraries.image_snapshots.requests.get"
    ) as request_image:
        _, _, error, status = _build_emby_image_stream(
            "server-a",
            item_id,
            image_type=image_type,
            scope=scope,
        )

    assert status == 400
    assert error == {"success": False, "message": "Parametri immagine non validi"}
    request_image.assert_not_called()


def test_proxy_uses_header_auth_and_only_forwards_image_parameters():
    response = _Response()
    with patch("emby_libraries.image_snapshots.load_config", return_value=(_config(), True)), patch(
        "emby_libraries.image_snapshots.requests.get",
        return_value=response,
    ) as request_image:
        stream, content_type, error, status = _build_emby_image_stream(
            "server-a",
            "movie-1",
            image_type="Primary",
            max_width="720",
            tag="image-tag",
        )

    assert (content_type, error, status) == ("image/jpeg", None, 200)
    assert b"".join(stream) == b"image"
    call = request_image.call_args
    assert call.args[0] == "https://emby.example.test/Items/movie-1/Images/Primary"
    assert call.kwargs["headers"]["X-Emby-Token"] == "CANARY_EMBY_SECRET"
    assert call.kwargs["params"] == {"maxWidth": 720, "tag": "image-tag"}
    assert call.kwargs["allow_redirects"] is False
    assert "CANARY_EMBY_SECRET" not in call.args[0]


def test_proxy_rejects_non_image_and_oversized_responses():
    cases = (
        _Response(content_type="application/json", content=b"{}"),
        _Response(content=b"x" * (_MAX_IMAGE_BYTES + 1)),
    )
    for response in cases:
        with patch("emby_libraries.image_snapshots.load_config", return_value=(_config(), True)), patch(
            "emby_libraries.image_snapshots.requests.get",
            return_value=response,
        ):
            stream, content_type, error, status = _build_emby_image_stream(
                "server-a",
                "movie-1",
            )

        assert stream is None
        assert content_type is None
        assert status == 502
        assert error["success"] is False
        assert response.closed is True


def test_authenticated_image_cache_is_private_and_revalidated():
    _, etag, cache_control, status = _build_emby_image_cache_meta(
        "server-a",
        "movie-1",
    )

    assert status == 200
    assert etag
    assert cache_control == "private, max-age=3600, must-revalidate"


def test_image_cache_metadata_rejects_control_characters_before_building_headers():
    _, etag, cache_control, status = _build_emby_image_cache_meta(
        "server-a",
        "movie-1",
        tag="safe\r\nX-Injected: yes",
    )

    assert status == 400
    assert etag is None
    assert cache_control == "private, max-age=3600, must-revalidate"


def test_image_etag_is_a_digest_of_every_canonical_variant():
    variants = {
        _build_emby_image_cache_meta(
            "server-a",
            "movie-1",
            scope=scope,
            max_width="720",
            tag="image-tag",
        )[1]
        for scope in (None, "item", "user")
    }

    assert len(variants) == 3
    assert all(value and value.startswith('"') and value.endswith('"') for value in variants)
