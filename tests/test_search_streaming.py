"""Streaming search behavior for manual searches."""

from __future__ import annotations

import copy
import unittest
from collections import Counter
from unittest.mock import patch

from starlette.websockets import WebSocketState

from core.config import DEFAULT_CONFIG
from search.download_references import protect_download_references
from search.streaming import search_streaming_parallel


class _FakeWebSocket:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.messages = []

    async def send_json(self, data):
        self.messages.append(data)


class _Backend:
    def __init__(self):
        self.saved = []

    def save_manual_search(self, payload):
        # Mirror the real storage boundary, which uses owner 0 references at rest.
        self.saved.append(protect_download_references(payload, persisted=True))

    def get_probe_matching_titles(self, _titles):
        return set()


def _search_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["SEARCH_RULES"]["query_terms"] = []
    config["SEARCH_RULES"]["query_languages"] = []
    config["SEARCH_RULES"]["filter_terms"] = []
    config["SEARCH_RULES"]["require_audio_language"] = False
    config["TARGET_LANGUAGES"] = []
    return config


class SearchStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_provider_rows_are_terminal_failures_not_partial_success(self):
        backend = _Backend()

        def fake_search(_query, _media_type, _config):
            return [{"title": {"nested": "invalid"}, "indexer": "Prowlarr"}]

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ):
            websocket = _FakeWebSocket()
            outcome = await search_streaming_parallel(
                query_variants=["Malformed"],
                search_types=["movie"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=websocket,
                session_id="manual-session",
                owner_id=41,
            )

        completed = [
            message
            for message in websocket.messages
            if message.get("type") == "all_completed"
        ]
        self.assertEqual("error", outcome["status"])
        self.assertEqual("error", completed[-1]["status"])
        self.assertFalse(completed[-1]["history_saved"])
        self.assertEqual([], backend.saved)

    async def test_unknown_media_type_searches_movies_and_tv(self):
        calls = []
        backend = _Backend()

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch("core.config_manager._ensure_db_backend", return_value=backend):
            websocket = _FakeWebSocket()
            await search_streaming_parallel(
                query_variants=["Manual query"],
                search_types=["unknown"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=websocket,
                session_id="manual-session",
                owner_id=41,
            )

        self.assertEqual(
            Counter({("Manual query", "movie"): 1, ("Manual query", "tv"): 1}),
            Counter(calls),
        )
        completed = [msg for msg in websocket.messages if msg.get("type") == "all_completed"]
        self.assertEqual(2, completed[-1]["total_queries"])
        self.assertEqual("mixed", backend.saved[-1]["items"][0]["media_type"])
        self.assertEqual(
            {
                "query": "Manual query",
                "media_type": "unknown",
                "indexers": ["prowlarr"],
                "seasons": [],
            },
            backend.saved[-1]["search_context"],
        )

    async def test_selected_tv_seasons_are_used_for_tmdb_query_generation(self):
        calls = []
        backend = _Backend()

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        tmdb_payload = {
            "id": 123,
            "name": "Example Show",
            "original_name": "Example Show",
            "first_air_date": "2025-01-01",
        }

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch("emby_runtime.api_clients.fetch_media_info", return_value=(tmdb_payload, "tv")), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ):
            await search_streaming_parallel(
                query_variants=["Fallback title"],
                search_types=["tv"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=_FakeWebSocket(),
                session_id="manual-session",
                owner_id=41,
                use_jellyseerr_logic=True,
                tmdb_id=123,
                seasons=[2],
            )

        queries = [query for query, _media_type in calls]
        self.assertTrue(queries)
        self.assertTrue(
            any("S02" in query or "2x" in query or "Stagione 2" in query or "Season 2" in query for query in queries)
        )
        self.assertFalse(any("S01" in query or "1x" in query for query in queries))
        self.assertFalse(any(query == "Fallback title" for query in queries))

    async def test_custom_query_terms_are_applied_to_independent_search_queries(self):
        calls = []
        backend = _Backend()

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ):
            await search_streaming_parallel(
                query_variants=["Manual Query"],
                search_types=["movie"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=_FakeWebSocket(),
                session_id="manual-session",
                owner_id=41,
                use_custom_rules=True,
                custom_rules={"search_rules": {"query_terms": ["2160p"]}},
            )

        queries = [query for query, _media_type in calls]
        self.assertIn("Manual Query 2160p", queries)
        self.assertNotIn("Manual Query", queries)

    async def test_selected_tv_seasons_apply_without_jellyseerr_logic(self):
        calls = []
        backend = _Backend()

        def fake_search(query, media_type, config):
            calls.append((query, media_type))
            return []

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ):
            await search_streaming_parallel(
                query_variants=["Example Show (2025)"],
                search_types=["tv"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=_FakeWebSocket(),
                session_id="manual-session",
                owner_id=41,
                seasons=[2],
            )

        queries = [query for query, _media_type in calls]
        self.assertTrue(queries)
        self.assertTrue(any("S02" in query or "2x" in query for query in queries))
        self.assertFalse(any(query == "Example Show (2025)" for query in queries))

    async def test_final_result_keeps_duplicate_sources_after_streaming(self):
        backend = _Backend()

        def fake_search(_query, _media_type, _config):
            return [
                {
                    "title": "Example Film 1080p",
                    "normalized_title": "example film 1080p",
                    "size_gb": 2.0,
                    "seeders": 20,
                    "indexer": "Prowlarr",
                    "link": "https://example.test/primary",
                },
                {
                    "title": "Example Film 1080p",
                    "normalized_title": "example film 1080p",
                    "size_gb": 2.0,
                    "seeders": 10,
                    "indexer": "Jackett",
                    "link": "https://example.test/duplicate",
                },
            ]

        with patch("search.indexers._prowlarr_configured", return_value=True), patch(
            "emby_runtime.api_clients.search_prowlarr",
            side_effect=fake_search,
        ), patch(
            "core.config_manager._ensure_db_backend",
            return_value=backend,
        ):
            websocket = _FakeWebSocket()
            await search_streaming_parallel(
                query_variants=["Example Film"],
                search_types=["movie"],
                selected_indexers={"prowlarr"},
                config=_search_config(),
                websocket=websocket,
                session_id="manual-session",
                owner_id=41,
            )

        live_results = [message for message in websocket.messages if message.get("type") == "result"]
        completed = [message for message in websocket.messages if message.get("type") == "all_completed"][-1]
        final_results = completed["filtered_results"]

        self.assertEqual(1, len(live_results))
        self.assertEqual(1, len(final_results))
        duplicate = final_results[0]["duplicates"][0]
        self.assertNotIn("link", duplicate)
        self.assertTrue(duplicate["torrent_ref"].startswith("ohsdl_"))
        self.assertTrue(final_results[0]["source_id"].startswith("ohsid_"))
        self.assertEqual(
            live_results[0]["data"]["source_id"],
            final_results[0]["source_id"],
        )
        persisted_results = backend.saved[-1]["items"][0]["results"]
        persisted_duplicate = persisted_results[0]["duplicates"][0]
        self.assertNotIn("link", persisted_duplicate)
        self.assertTrue(persisted_duplicate["torrent_ref"].startswith("ohsdl_"))
        self.assertNotEqual(duplicate["torrent_ref"], persisted_duplicate["torrent_ref"])
