"""Streaming search behavior for manual searches."""

from __future__ import annotations

import copy
import unittest
from collections import Counter
from unittest.mock import patch

from starlette.websockets import WebSocketState

from core.config import DEFAULT_CONFIG
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
        self.saved.append(payload)


def _search_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["SEARCH_RULES"]["query_terms"] = []
    config["SEARCH_RULES"]["query_languages"] = []
    config["SEARCH_RULES"]["filter_terms"] = []
    config["SEARCH_RULES"]["require_audio_language"] = False
    config["TARGET_LANGUAGES"] = []
    return config


class SearchStreamingTests(unittest.IsolatedAsyncioTestCase):
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
            )

        self.assertEqual(
            Counter({("Manual query", "movie"): 1, ("Manual query", "tv"): 1}),
            Counter(calls),
        )
        completed = [msg for msg in websocket.messages if msg.get("type") == "all_completed"]
        self.assertEqual(2, completed[-1]["total_queries"])
        self.assertEqual("mixed", backend.saved[-1]["items"][0]["media_type"])

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
                seasons=[2],
            )

        queries = [query for query, _media_type in calls]
        self.assertTrue(queries)
        self.assertTrue(any("S02" in query or "2x" in query for query in queries))
        self.assertFalse(any(query == "Example Show (2025)" for query in queries))
