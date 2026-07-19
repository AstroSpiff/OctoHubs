"""Manual search API behavior."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from core.config import DEFAULT_CONFIG
from search.manager import _build_manual_search_snapshot


def _search_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["SEARCH_RULES"]["query_terms"] = []
    config["SEARCH_RULES"]["query_languages"] = []
    config["SEARCH_RULES"]["filter_terms"] = []
    config["SEARCH_RULES"]["require_audio_language"] = False
    config["TARGET_LANGUAGES"] = []
    return config


class ManualSearchSnapshotTests(unittest.TestCase):
    def test_custom_query_terms_are_applied_to_manual_api_queries(self):
        calls = []

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        with patch("search.manager.load_config", return_value=(_search_config(), True)), patch(
            "search.manager._prowlarr_configured",
            return_value=True,
        ), patch(
            "search.manager.search_prowlarr",
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
