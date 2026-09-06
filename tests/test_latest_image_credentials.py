"""Regression tests for credential-free Latest Publication images."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from core.storage import EmbyLatestCacheItem
from core.storage.storage_latest import StorageLatestMixin
from emby_latest.builders import _build_emby_latest_item
from emby_latest.notification_images import (
    PreparedTelegramPhoto,
    TelegramPhotoUpload,
    prepare_telegram_photo,
)
from emby_latest.notifications import send_notifications


_EMBY_SECRET = "CANARY_EMBY_SECRET"


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


class _ImageResponse:
    def __init__(self, content: bytes):
        self._content = content
        self.headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(content)),
        }
        self.is_redirect = False
        self.is_permanent_redirect = False
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        assert chunk_size > 0
        yield self._content

    def close(self):
        self.closed = True


class _NotificationStorage:
    def __init__(self, payload):
        self.payload = deepcopy(payload)
        self.saved_states = []

    def load_latest_cache(self, cache_kind):
        assert cache_kind == "batch"
        return deepcopy(self.payload)

    def load_latest_state(self):
        return {}

    def save_latest_state(self, state):
        self.saved_states.append(deepcopy(state))


class _DeleteQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def delete(self, **_kwargs):
        return 0


class _LatestSession:
    def __init__(self):
        self.added = []

    def query(self, _model):
        return _DeleteQuery()

    def add(self, row):
        self.added.append(row)

    def flush(self):
        for index, row in enumerate(self.added, start=1):
            if isinstance(row, EmbyLatestCacheItem):
                row.id = index

    def get(self, _model, _identity):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class _LatestStorage(StorageLatestMixin):
    def __init__(self):
        self.session = _LatestSession()

    def _get_session(self):
        return self.session


def test_latest_builder_exposes_only_internal_image_proxy_urls():
    server = {
        "id": "server-a",
        "url": "https://emby.example.test",
        "api_key": _EMBY_SECRET,
    }
    item = {
        "Id": "movie-1",
        "Name": "Movie",
        "Type": "Movie",
        "ImageTags": {"Primary": "image-tag"},
    }

    with patch(
        "emby_latest.builders._resolve_emby_library_for_item",
        return_value=("library-1", "Movies"),
    ):
        result = _build_emby_latest_item(item, server)

    assert result is not None
    for field in (
        "image_url",
        "poster_url",
        "backdrop_url",
        "banner_url",
        "thumb_url",
        "logo_url",
    ):
        assert result[field].startswith("/api/v1/emby/image?")
        assert _EMBY_SECRET not in result[field]
        assert "api_key=" not in result[field].lower()
    assert result["emby_url"] == (
        "https://emby.example.test/web/index.html#!/itemdetails.html?id=movie-1"
    )


def test_latest_storage_ignores_tainted_image_urls_on_write_and_read():
    storage = _LatestStorage()
    tainted_url = f"https://emby.example.test/image?api_key={_EMBY_SECRET}"
    payload = {
        "movies": [
            {
                "server_id": "server-a",
                "item_id": "movie-1",
                "item_type": "Movie",
                "title": "Movie",
                "image_tag": "image-tag",
                "image_url": tainted_url,
                "poster_url": tainted_url,
                "backdrop_url": tainted_url,
                "banner_url": tainted_url,
                "thumb_url": tainted_url,
                "logo_url": tainted_url,
            }
        ],
        "series": [],
        "errors": [],
    }

    storage.save_latest_cache("batch", payload, limit=25, per_server_limit=5)
    stored_item = next(
        row for row in storage.session.added if isinstance(row, EmbyLatestCacheItem)
    )
    stored = tuple(
        getattr(stored_item, field)
        for field in (
            "image_url",
            "poster_url",
            "backdrop_url",
            "banner_url",
            "thumb_url",
            "logo_url",
        )
    )
    loaded = storage._latest_cache_item_to_dict(stored_item)

    for image_url in (*stored, *(loaded[field] for field in (
        "image_url",
        "poster_url",
        "backdrop_url",
        "banner_url",
        "thumb_url",
        "logo_url",
    ))):
        assert image_url.startswith("/api/v1/emby/image?")
        assert _EMBY_SECRET not in image_url
        assert "api_key=" not in image_url.lower()


def test_emby_notification_image_is_downloaded_with_header_and_sanitized():
    response = _ImageResponse(_png_bytes())
    item = {
        "server_id": "server-a",
        "item_id": "movie/1",
        "image_tag": "image-tag",
        "poster_url": "/api/v1/emby/image?server_id=server-a&item_id=movie%2F1&type=Primary",
    }
    config = {
        "EMBY": {
            "SERVERS": [
                {
                    "id": "server-a",
                    "url": "https://emby.example.test",
                    "api_key": _EMBY_SECRET,
                }
            ]
        }
    }

    with patch(
        "emby_latest.notification_images.requests.get",
        return_value=response,
    ) as get_image:
        prepared = prepare_telegram_photo(item["poster_url"], item, config)

    assert prepared.error == ""
    assert prepared.url == ""
    assert prepared.upload is not None
    assert prepared.upload.content_type == "image/png"
    call = get_image.call_args
    assert call.args[0] == "https://emby.example.test/Items/movie%2F1/Images/Primary"
    assert call.kwargs["headers"]["X-Emby-Token"] == _EMBY_SECRET
    assert "api_key" not in call.kwargs["params"]
    assert _EMBY_SECRET not in call.args[0]
    assert response.closed is True


def test_latest_notification_uploads_emby_image_bytes_instead_of_its_url():
    poster_url = "/api/v1/emby/image?server_id=server-a&item_id=movie-1&type=Primary"
    cache_payload = {
        "payload": {
            "movies": [
                {
                    "server_id": "server-a",
                    "item_id": "movie-1",
                    "signature": "tmdb:1",
                    "item_type": "movie",
                    "title": "Movie",
                    "year": 2026,
                    "added_at": "2026-08-30T10:00:00+00:00",
                    "poster_url": poster_url,
                }
            ],
            "series": [],
        }
    }
    storage = _NotificationStorage(cache_payload)
    latest_settings = {
        "PRESETS": [
            {"id": "preset-a", "name": "Preset", "template": "{{ poster_url }}\n{{ title }}"}
        ],
        "NOTIFICATION_RULES": [
            {
                "id": "rule-a",
                "name": "Rule A",
                "enabled": True,
                "server_ids": ["server-a"],
                "preset_id": "preset-a",
                "telegram_config_id": "telegram-a",
            }
        ],
    }
    telegram_settings = {
        "PRESETS": [
            {
                "id": "telegram-a",
                "name": "Telegram",
                "bot_ids": ["bot-a"],
                "group_ids": ["group-a"],
                "channel_ids": [],
            }
        ],
        "BOTS": [{"id": "bot-a", "token": "telegram-token"}],
        "GROUPS": [{"id": "group-a", "chat_id": "chat-a"}],
        "CHANNELS": [],
    }
    prepared = PreparedTelegramPhoto(
        upload=TelegramPhotoUpload(b"safe-image", "image/png", "publication.png")
    )
    calls = []

    def fake_telegram(token, method, params, files=None):
        calls.append((token, method, params, files))
        return True, "OK", {}

    with patch(
        "emby_latest.settings._load_latest_settings",
        return_value=latest_settings,
    ), patch(
        "telegram._load_telegram_settings",
        return_value=telegram_settings,
    ), patch(
        "emby_latest.jellyseerr._apply_jellyseerr_request_info",
        return_value=None,
    ), patch(
        "emby_latest.notifications.prepare_telegram_photo",
        return_value=prepared,
    ), patch(
        "emby_latest.notifications._telegram_api_request",
        side_effect=fake_telegram,
    ), patch("time.sleep", return_value=None):
        result = send_notifications(
            10,
            config={
                "DATABASE": {"ENABLED": True},
                "EMBY": {"SERVERS": [{"id": "server-a"}]},
            },
            db_storage=storage,
        )

    assert result["success"] is True
    assert result["sent"] == 1
    assert len(calls) == 1
    _, method, params, files = calls[0]
    assert method == "sendPhoto"
    assert "photo" not in params
    assert params["caption"] == "Movie"
    assert files == {
        "photo": ("publication.png", b"safe-image", "image/png")
    }
