"""JustWatch availability behaviour."""

from __future__ import annotations

from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
