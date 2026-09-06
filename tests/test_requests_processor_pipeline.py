"""Behavioral coverage for the focused request-scan pipeline."""

from __future__ import annotations

from unittest.mock import patch

from services.requests_processor import process_requests


def _config():
    return {
        "SEARCH_RULES": {
            "skip_available_content": True,
            "skip_unreleased_content": False,
            "query_terms": [],
            "filter_terms": [],
            "exclude_terms": [],
            "require_audio_language": False,
        },
        "REQUEST_RULES": {},
    }


def test_empty_request_scan_persists_the_same_empty_summary():
    saved = []

    with patch(
        "services.request_scan_pipeline.get_jellyseerr_requests",
        return_value=([], True),
    ), patch(
        "services.request_scan_pipeline.load_results_file",
        return_value={"items": [{"request_id": "old"}]},
    ), patch(
        "services.request_scan_pipeline._merge_scan_summaries",
        side_effect=lambda _previous, current: current,
    ), patch(
        "services.request_scan_pipeline.save_results",
        side_effect=saved.append,
    ):
        summary = process_requests(_config())

    assert summary["total_requests"] == 0
    assert summary["checked_requests"] == 0
    assert summary["found"] == 0
    assert summary["items"] == []
    assert saved == [summary]


def test_movie_request_preserves_result_payload_and_progress_callbacks():
    request = {
        "id": 17,
        "type": "movie",
        "title": "Film test",
        "year": 2024,
        "media": {"status": 1, "mediaType": "movie"},
    }
    provider_result = {
        "title": "Film test 2024 1080p",
        "size_gb": 3.5,
        "seeders": 12,
        "indexer": "Prowlarr",
        "link": "magnet:?xt=urn:btih:test",
    }
    attempts = [{"query": "Film test 2024", "results_found": 1}]
    progress = []
    saved = []

    with patch(
        "services.request_scan_pipeline.get_jellyseerr_requests",
        return_value=([request], True),
    ), patch(
        "services.request_scan_pipeline.load_results_file",
        return_value={},
    ), patch(
        "services.request_scan_pipeline._merge_scan_summaries",
        side_effect=lambda _previous, current: current,
    ), patch(
        "services.request_scan_pipeline.save_results",
        side_effect=saved.append,
    ), patch(
        "services.requests_processor.execute_search_with_variants",
        return_value=([provider_result], attempts),
    ):
        summary = process_requests(
            _config(),
            status_callback=lambda *values: progress.append(values),
        )

    assert summary["total_requests"] == 1
    assert summary["checked_requests"] == 1
    assert summary["found"] == 1
    assert summary["aborted"] is False
    assert summary["target_subset"] is False
    assert summary["items"] == [
        {
            "request_id": 17,
            "title": "Film test",
            "year": "2024",
            "media_type": "movie",
            "season": None,
            "queries": attempts,
            "results_found": 1,
            "results": [{**provider_result, "duplicates": []}],
            "excluded": [],
        }
    ]
    assert progress == [(0, 1, None, None), (1, 1, "Film test", None)]
    assert saved == [summary]


def test_request_scan_redacts_provider_references_and_log_control_characters(capsys):
    from services.request_scan_execution import _group_and_log_results

    canary = "R18_PROVIDER_SECRET_CANARY"
    provider_result = {
        "title": f"Film\nforged-line token={canary}",
        "size_gb": 3.5,
        "seeders": 12,
        "indexer": f"Indexer\x1b[31m apikey={canary}",
        "link": (
            "https://provider.invalid/private/item.torrent"
            f"?apikey={canary}&passkey={canary}"
        ),
    }

    grouped = _group_and_log_results(
        [provider_result],
        f"Catalog\nforged-heading password={canary}",
        "",
        {"SEARCH_RULES": {}},
        "movie",
    )

    output = capsys.readouterr().out
    assert grouped[0]["link"] == provider_result["link"]
    assert canary not in output
    assert "Catalog forged-heading password=[REDACTED]" in output
    assert "Film forged-line token=[REDACTED]" in output
    assert "Indexer [31m apikey=[REDACTED]" in output
    assert "https://provider.invalid/[REDACTED].torrent" in output
    assert "\x1b" not in output
