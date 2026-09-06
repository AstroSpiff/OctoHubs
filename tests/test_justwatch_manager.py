"""JustWatch availability behaviour."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest


class _FakeJustWatchStorage:
    def __init__(self, cached=None) -> None:
        self.cached = cached or {}
        self.lookups = []
        self.saved = []
        self.cleared = []

    def get_justwatch_cache(self, **kwargs):
        self.lookups.append(kwargs)
        key = (kwargs["show_name"], kwargs["season"], kwargs["episode"])
        return self.cached.get(key)

    def save_justwatch_cache(self, **kwargs):
        self.saved.append(kwargs)

    def clear_justwatch_cache(self, **kwargs):
        self.cleared.append(kwargs)
        return 1


class JustWatchManagerTests(unittest.TestCase):
    def _manager(self, storage=None):
        from core.justwatch_manager import JustWatchManager

        manager = object.__new__(JustWatchManager)
        manager.storage = storage or _FakeJustWatchStorage()
        return manager

    def test_episode_offers_do_not_fall_back_to_show_level_offers(self):
        manager = self._manager()
        manager._get_show_details = lambda _node_id: {
            "seasons": [
                {
                    "content": {"seasonNumber": 1},
                    "episodes": [
                        {
                            "content": {"episodeNumber": 8},
                            "offers": [],
                        }
                    ],
                }
            ],
            "offers": [
                {
                    "monetizationType": "FLATRATE",
                    "package": {"clearName": "Apple TV"},
                }
            ],
        }

        offers = manager._get_episode_offers("show-node", 1, 8)

        self.assertEqual(offers, [])

    def test_episode_availability_requires_episode_specific_offers(self):
        manager = self._manager()
        manager._search_show = lambda _title, _year=None: {
            "id": "show-node",
            "offers": [
                {
                    "monetizationType": "FLATRATE",
                    "package": {"clearName": "Apple TV"},
                }
            ],
        }
        manager._get_episode_offers = lambda *_args: []

        available, providers = manager.check_availability_details(
            "Cape Fear",
            1,
            8,
            year=2026,
        )

        self.assertIs(available, False)
        self.assertEqual(providers, [])
        self.assertEqual(manager.storage.saved[-1]["is_available"], False)

    def test_episode_availability_ignores_legacy_show_level_cache(self):
        storage = _FakeJustWatchStorage(
            cached={
                ("Cape Fear", 1, 8): {
                    "is_available": True,
                    "providers": ["Apple TV"],
                    "last_checked": datetime.now(),
                }
            }
        )
        manager = self._manager(storage)
        manager._search_show = lambda _title, _year=None: {"id": "show-node"}
        manager._get_episode_offers = lambda *_args: []

        available, providers = manager.check_availability_details(
            "Cape Fear",
            1,
            8,
            year=2026,
        )

        self.assertIs(available, False)
        self.assertEqual(providers, [])
        self.assertEqual(storage.lookups[0]["show_name"], "Cape Fear::episode-v2")
        self.assertEqual(storage.saved[-1]["show_name"], "Cape Fear::episode-v2")

    def test_clear_cache_clears_legacy_and_episode_v2_keys(self):
        storage = _FakeJustWatchStorage()
        manager = self._manager(storage)

        cleared = manager.clear_cache("Cape Fear")

        self.assertEqual(cleared, 2)
        self.assertEqual(
            storage.cleared,
            [
                {"show_name": "Cape Fear"},
                {"show_name": "Cape Fear::episode-v2"},
            ],
        )

    def test_justwatch_graphql_transport_is_streamed_and_bounded(self):
        from unittest.mock import patch

        from core.justwatch_manager import JustWatchManager

        manager = object.__new__(JustWatchManager)
        manager._rate_limit = lambda: None
        manager._graphql_headers = lambda: {"Content-Type": "application/json"}
        sentinel = object()
        payload = {"data": {"node": None}}
        with patch("core.justwatch_manager.requests.post", return_value=sentinel) as request, patch(
            "core.justwatch_manager.read_bounded_json_response",
            return_value=payload,
        ) as bounded_reader:
            response = manager._graphql_post({"query": "query Test { __typename }"})

        self.assertEqual(response, payload)
        self.assertIs(request.call_args.kwargs["stream"], True)
        self.assertEqual(request.call_args.kwargs["timeout"], 20)
        bounded_reader.assert_called_once_with(sentinel)

    def test_legacy_justwatch_dependency_and_rest_branch_are_absent(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "core/justwatch_manager.py").read_text(encoding="utf-8")
        runtime_requirements = (root / "requirements.in").read_text(encoding="utf-8").lower()

        self.assertNotIn("from justwatch import", source)
        self.assertNotIn("self.jw", source)
        self.assertNotIn("_TimeoutSession", source)
        self.assertNotIn("justwatch==", runtime_requirements)


if __name__ == "__main__":
    unittest.main()
