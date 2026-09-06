"""Manual search API behavior."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from core.config import DEFAULT_CONFIG
from search.manager import _build_manual_search_snapshot
from search.stream_limits import MAX_SEARCH_QUERY_LENGTH


def _search_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["SEARCH_RULES"]["query_terms"] = []
    config["SEARCH_RULES"]["query_languages"] = []
    config["SEARCH_RULES"]["filter_terms"] = []
    config["SEARCH_RULES"]["require_audio_language"] = False
    config["TARGET_LANGUAGES"] = []
    return config


class ManualSearchSnapshotTests(unittest.TestCase):
    @patch("search.manual_search_pipeline.load_config")
    @patch("builtins.print")
    def test_oversized_query_is_rejected_before_logging_or_configuration_load(
        self,
        print_mock,
        load_config,
    ):
        payload, status_code = _build_manual_search_snapshot(
            {
                "query": "q" * (MAX_SEARCH_QUERY_LENGTH + 1),
                "media_type": "movie",
                "indexers": ["prowlarr"],
            }
        )

        self.assertEqual(400, status_code)
        self.assertFalse(payload["success"])
        self.assertEqual("Query troppo lunga", payload["message"])
        print_mock.assert_not_called()
        load_config.assert_not_called()

    def test_custom_query_terms_are_applied_to_manual_api_queries(self):
        calls = []

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        with patch(
            "search.manual_search_pipeline.load_config",
            return_value=(_search_config(), True),
        ), patch(
            "search.manual_search_results._prowlarr_configured",
            return_value=True,
        ), patch(
            "search.manual_search_results.search_prowlarr",
            side_effect=fake_search,
        ):
            payload, status_code = _build_manual_search_snapshot(
                {
                    "query": "Manual Query",
                    "media_type": "movie",
                    "indexers": ["prowlarr"],
                    "use_custom_rules": True,
                    "custom_rules": {"search_rules": {"query_terms": ["2160p"]}},
                }
            )

        self.assertEqual(200, status_code)
        self.assertTrue(payload["success"])
        queries = [query for query, _media_type in calls]
        self.assertIn("Manual Query 2160p", queries)
        self.assertNotIn("Manual Query", queries)

    def test_unconfigured_indexer_warning_is_deduplicated_across_media_types(self):
        with patch(
            "search.manual_search_pipeline.load_config",
            return_value=(_search_config(), True),
        ), patch(
            "search.manual_search_results._prowlarr_configured",
            return_value=False,
        ):
            payload, status_code = _build_manual_search_snapshot(
                {
                    "query": "Manual Query",
                    "indexers": ["prowlarr"],
                }
            )

        self.assertEqual(200, status_code)
        self.assertEqual(["Prowlarr non configurato"], payload["warnings"])
        self.assertEqual(["Manual Query"], payload["debug_queries"])
        self.assertEqual([], payload["results"])

    def test_custom_result_filters_keep_normalized_provider_payload(self):
        provider_results = [
            {
                "title": "Keep Release S01E02",
                "size_gb": 2.0,
                "resolution_bucket": "1080p",
                "seeders": 10,
                "indexer": "Prowlarr",
                "link": "https://example.test/keep",
                "magnetUri": "magnet:?xt=urn:btih:keep",
            },
            {
                "title": "Drop Release S01E02",
                "size_gb": 2.0,
                "resolution_bucket": "1080p",
                "seeders": 8,
                "indexer": "Prowlarr",
                "link": "https://example.test/drop",
            },
        ]
        with patch(
            "search.manual_search_pipeline.load_config",
            return_value=(_search_config(), True),
        ), patch(
            "search.manual_search_results._prowlarr_configured",
            return_value=True,
        ), patch(
            "search.manual_search_results.search_prowlarr",
            return_value=provider_results,
        ), patch(
            "search.manual_search_results.filter_results",
            side_effect=lambda results, *_args, **_kwargs: results,
        ), patch(
            "search.manual_search_results._load_emby_library_title_index",
            return_value=set(),
        ):
            payload, status_code = _build_manual_search_snapshot(
                {
                    "query": "Manual Query",
                    "media_type": "tv",
                    "indexers": ["prowlarr"],
                    "use_custom_rules": True,
                    "custom_rules": {
                        "include_filter": "keep",
                        "min_size_gb": 1.0,
                        "max_size_gb": 3.0,
                    },
                }
            )

        self.assertEqual(200, status_code)
        self.assertEqual(1, len(payload["results"]))
        result = payload["results"][0]
        self.assertEqual("Keep Release S01E02", result["title"])
        self.assertEqual("magnet:?xt=urn:btih:keep", result["guid"])
        self.assertEqual("1080p", result["resolution"])
        self.assertEqual(1, result["season_number"])
        self.assertFalse(result["in_library"])
