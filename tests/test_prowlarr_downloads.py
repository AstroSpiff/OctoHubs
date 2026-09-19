"""Prowlarr-owned torrent dispatch contracts."""

from __future__ import annotations

from typing import Any

from services import prowlarr_downloads


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.closed = False

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, statuses: list[int]):
        self.responses = [_Response(status) for status in statuses]
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses[len(self.calls) - 1]

    def close(self):
        self.closed = True


def _config() -> dict[str, str]:
    return {
        "PROWLARR_URL": "https://prowlarr.invalid/",
        "PROWLARR_API_KEY": "private-api-key",
    }


def test_grab_posts_only_cached_release_identity_and_leaves_client_ownership_to_prowlarr(
    monkeypatch,
):
    session = _Session([200])
    monkeypatch.setattr(prowlarr_downloads.requests, "Session", lambda: session)

    success, message = prowlarr_downloads.grab_prowlarr_release(
        {"indexerId": 7, "guid": "opaque-release-guid"},
        {
            **_config(),
            "TORRENT_CLIENTS": [
                {"url": "https://deluge.invalid", "password": "must-not-leak"}
            ],
        },
    )

    assert success is True
    assert message == "Torrent affidato a Prowlarr"
    assert session.calls == [
        {
            "url": "https://prowlarr.invalid/api/v1/search",
            "headers": {
                "X-Api-Key": "private-api-key",
                "Accept": "application/json",
            },
            "json": {"indexerId": 7, "guid": "opaque-release-guid"},
            "allow_redirects": False,
            "stream": True,
        }
    ]
    assert "timeout" not in session.calls[0]
    assert session.responses[0].closed is True
    assert session.closed is True


def test_grab_reports_expired_prowlarr_cache_without_direct_client_fallback(monkeypatch):
    session = _Session([404])
    monkeypatch.setattr(prowlarr_downloads.requests, "Session", lambda: session)

    success, message = prowlarr_downloads.grab_prowlarr_release(
        {"indexerId": 7, "guid": "expired-guid"},
        _config(),
    )

    assert success is False
    assert message == "Risultato Prowlarr scaduto: ripeti la ricerca"
    assert len(session.calls) == 1


def test_batch_grab_records_partial_outcomes(monkeypatch):
    session = _Session([200, 409])
    monkeypatch.setattr(prowlarr_downloads.requests, "Session", lambda: session)

    success, message, details = prowlarr_downloads.grab_prowlarr_releases(
        [
            {"indexerId": 7, "guid": "first"},
            {"indexerId": 8, "guid": "second"},
        ],
        _config(),
    )

    assert success is True
    assert message == "1/2 risultati inviati da Prowlarr; 1 non inviati"
    assert details == {
        "sent": 1,
        "failed": 1,
        "total": 2,
        "failures": [
            {
                "index": 1,
                "error": "Prowlarr non ha potuto recuperare il torrent dall'indexer",
            }
        ],
    }
    assert session.closed is True


def test_search_pipeline_preserves_grab_identity_only_as_owner_bound_reference(
    monkeypatch,
):
    from core.scanner import filter_results
    from emby_runtime.api_clients_indexers import search_prowlarr
    from search.download_references import (
        configure_download_reference_secret,
        protect_download_references,
    )
    from search.prowlarr_grab_references import resolve_prowlarr_grab_reference

    class SearchResponse:
        status_code = 200
        headers: dict[str, str] = {}

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "title": "Example Film ITA 1080p",
                    "indexerId": 17,
                    "indexer": "Example",
                    "guid": "private-release-guid",
                    "downloadUrl": "https://indexer.invalid/download/17",
                    "seeders": 4,
                    "size": 1024,
                }
            ]

        def close(self):
            return None

    monkeypatch.setattr(
        "emby_runtime.api_clients_indexers.requests.get",
        lambda *_args, **_kwargs: SearchResponse(),
    )
    configure_download_reference_secret("pipeline-grab-secret")

    raw = search_prowlarr(
        "Example Film",
        "movie",
        {"PROWLARR_URL": "https://prowlarr.invalid", "PROWLARR_API_KEY": "key"},
    )
    filtered = filter_results(
        raw,
        {"SEARCH_RULES": {"min_seeders": 0}, "TARGET_LANGUAGES": []},
        media_type="movie",
    )
    protected = protect_download_references(filtered, owner_id=41)

    assert "_prowlarr_grab" not in protected[0]
    assert "private-release-guid" not in repr(protected)
    assert resolve_prowlarr_grab_reference(
        41, protected[0]["prowlarr_grab_ref"]
    ) == {"indexerId": 17, "guid": "private-release-guid"}
