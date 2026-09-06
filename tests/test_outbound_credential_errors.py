"""Outbound failures must not expose provider credentials."""

from __future__ import annotations

from unittest.mock import patch

import requests

from core.log_sanitization import sanitize_text_for_log, sanitize_url_for_log
from emby_latest.enrichment_sources import _fetch_mdblist_ratings_by_imdb
from emby_runtime.api_clients_emby import _call_emby_api
from telegram.manager import _telegram_api_request as manager_telegram_request


CANARY = "CANARY_PROVIDER_SECRET"


def test_emby_errors_are_stable_and_token_is_header_only():
    error = requests.ConnectionError(
        f"failed https://emby.example.test/System/Info?api_key={CANARY}"
    )
    with patch("emby_runtime.api_clients_emby.requests.get", side_effect=error) as request:
        success, message = _call_emby_api(
            {"url": "https://emby.example.test", "api_key": CANARY},
            "System/Info",
        )

    assert success is False
    assert message == "Errore richiesta Emby"
    assert CANARY not in message
    assert request.call_args.kwargs["params"] == {}
    assert request.call_args.kwargs["headers"]["X-Emby-Token"] == CANARY
    assert request.call_args.kwargs["allow_redirects"] is False


def test_collection_image_upload_keeps_emby_token_out_of_url_and_query(caplog):
    from emby_collections.collection_emby import _set_collection_poster_blob

    error = requests.ConnectionError(
        f"failed https://emby.example.test/Items/123/Images/Primary?api_key={CANARY}"
    )
    with patch(
        "emby_collections.collection_emby.requests.post", side_effect=error
    ) as request:
        _set_collection_poster_blob(
            {"url": "https://emby.example.test", "api_key": CANARY},
            "123",
            b"image",
            "image/png",
        )

    assert "api_key" not in request.call_args.kwargs
    assert "params" not in request.call_args.kwargs
    assert request.call_args.kwargs["headers"]["X-Emby-Token"] == CANARY
    assert request.call_args.kwargs["allow_redirects"] is False
    assert CANARY not in caplog.text


def test_emby_redirect_is_rejected_without_following_credentials():
    response = requests.Response()
    response.status_code = 302
    response.headers["Location"] = "https://attacker.example.test/sink"

    with patch(
        "emby_runtime.api_clients_emby.requests.get", return_value=response
    ) as request:
        success, message = _call_emby_api(
            {"url": "https://emby.example.test", "api_key": CANARY},
            "System/Info",
        )

    assert (success, message) == (False, "Redirect Emby rifiutato")
    assert request.call_count == 1
    assert request.call_args.kwargs["allow_redirects"] is False


def test_jellyseerr_request_failure_is_generic_through_snapshot(monkeypatch, caplog):
    from emby_runtime import jellyseerr_snapshots

    canary_url = f"https://user:{CANARY}@jelly.example.test/api?apikey={CANARY}"
    monkeypatch.setattr(
        "emby_runtime.api_clients_jellyseerr.requests.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.ConnectionError(f"failed at {canary_url}")
        ),
    )
    monkeypatch.setattr(
        jellyseerr_snapshots,
        "load_config",
        lambda: (
            {
                "JELLYSEERR_URL": "https://jelly.example.test",
                "JELLYSEERR_API_KEY": CANARY,
            },
            True,
        ),
    )

    payload, status = jellyseerr_snapshots._build_jellyseerr_request_snapshot(
        {"mediaId": 10, "mediaType": "movie"}
    )

    assert status == 502
    assert payload["message"] == "Jellyseerr non disponibile"
    assert CANARY not in str(payload)
    assert CANARY not in caplog.text


def test_telegram_request_exceptions_do_not_escape_bot_token():
    error = requests.ConnectionError(
        f"failed https://api.telegram.org/bot{CANARY}/getMe"
    )
    with patch("telegram.manager.requests.get", side_effect=error):
        success, message, result = manager_telegram_request(CANARY, "getMe", {})

    assert (success, result) == (False, {})
    assert message == "Errore richiesta Telegram."
    assert CANARY not in message


def test_telegram_bot_tokens_are_redacted_from_url_paths_and_embedded_text():
    url = f"https://api.telegram.org/bot{CANARY}/getMe?chat_id=1"

    assert CANARY not in sanitize_url_for_log(url)
    assert CANARY not in sanitize_text_for_log(f"provider failed at {url}")
    assert "/bot[REDACTED]/getMe" in sanitize_url_for_log(url)


def test_mdblist_exception_log_redacts_query_secret(capsys):
    error = requests.ConnectionError(
        f"failed https://mdblist.com/api/?apikey={CANARY}&i=tt123"
    )
    with patch("emby_latest.enrichment_sources.requests.get", side_effect=error):
        result = _fetch_mdblist_ratings_by_imdb("tt123", [CANARY])

    assert result == {}
    output = capsys.readouterr().out
    assert CANARY not in output
    assert "apikey=%5BREDACTED%5D" in output or "apikey=[REDACTED]" in output
