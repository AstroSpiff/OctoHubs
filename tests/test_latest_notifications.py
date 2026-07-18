"""Latest publications notification behavior."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from emby_latest.notifications import send_notifications


class _ExplicitNotificationStorage:
    def __init__(self, cache_payload):
        self.cache_payload = deepcopy(cache_payload)
        self.saved_states = []

    def load_latest_cache(self, cache_kind):
        if cache_kind != "batch":
            return {}
        return deepcopy(self.cache_payload)

    def load_latest_state(self):
        return {}

    def save_latest_state(self, state):
        self.saved_states.append(deepcopy(state))


class LatestNotificationTests(unittest.TestCase):
    def test_send_notifications_uses_explicit_db_storage_for_cache_and_state(self):
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
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        storage = _ExplicitNotificationStorage(cache_payload)
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
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
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        with patch(
            "core.config_manager._ensure_db_backend",
            side_effect=AssertionError("global backend should not be used"),
        ), patch("emby_latest.settings._load_latest_settings", return_value=latest_settings), patch(
            "telegram._load_telegram_settings",
            return_value=telegram_settings,
        ), patch("emby_latest.jellyseerr._apply_jellyseerr_request_info", return_value=None), patch(
            "emby_latest.notifications._telegram_api_request",
            return_value=(True, "OK", {}),
        ), patch("time.sleep", return_value=None):
            result = send_notifications(
                10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
                db_storage=storage,
            )

        self.assertTrue(result["success"])
        self.assertEqual(1, result["sent"])
        self.assertTrue(storage.saved_states)
        self.assertTrue(storage.saved_states[-1]["server-a"]["movies"]["items"]["tmdb:1"]["notified"])

    def test_send_notifications_marks_lowercase_movie_type_as_notified(self):
        saved_states = []
        latest_state = {"server-a": {"movies": {"items": {}}}}
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
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": ["telegram-a"],
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
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value=latest_state,
        ), patch("emby_latest.db_state.save_state", side_effect=lambda state: saved_states.append(state)), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", return_value=(True, "OK", {})), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["sent"], 1)
        self.assertTrue(saved_states)
        movie_state = saved_states[-1]["server-a"]["movies"]["items"]["tmdb:1"]
        self.assertTrue(movie_state["notified"])

    def test_send_notifications_reports_template_errors_without_sending(self):
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
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{{ title"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": ["telegram-a"],
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
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None) as save_state, patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", return_value=(True, "OK", {})) as send_request, patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertTrue(any("Errore template" in error for error in result["errors"]))
        send_request.assert_not_called()
        save_state.assert_not_called()

    def test_send_notifications_limits_items_per_server_without_global_cap(self):
        sent_titles = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": server_id,
                        "item_id": f"{server_id}-movie-{index}",
                        "signature": f"{server_id}:tmdb:{index}",
                        "item_type": "movie",
                        "title": f"{server_id} Movie {index}",
                        "year": 2026,
                        "added_at": f"2026-07-15T10:0{index}:00+00:00",
                    }
                    for server_id in ("server-a", "server-b")
                    for index in range(1, 4)
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": ["telegram-a"],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a", "server-b"],
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
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        def fake_telegram(_token, _method, params):
            sent_titles.append(params.get("text") or params.get("caption") or "")
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=2,
                config={
                    "DATABASE": {"ENABLED": True},
                    "EMBY": {"SERVERS": [{"id": "server-a"}, {"id": "server-b"}]},
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["sent"], 4)
        self.assertEqual(
            sent_titles,
            [
                "server-a Movie 1",
                "server-a Movie 2",
                "server-b Movie 1",
                "server-b Movie 2",
            ],
        )

    def test_send_notifications_limits_movies_and_series_separately_per_server(self):
        sent_titles = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": f"movie-{index}",
                        "signature": f"tmdb:movie-{index}",
                        "item_type": "movie",
                        "title": f"Movie {index}",
                        "year": 2026,
                        "added_at": f"2026-07-15T10:0{index}:00+00:00",
                    }
                    for index in range(1, 3)
                ],
                "series": [
                    {
                        "server_id": "server-a",
                        "item_id": f"series-{index}",
                        "item_type": "series",
                        "title": f"Series {index}",
                        "year": 2026,
                        "added_at": f"2026-07-15T11:0{index}:00+00:00",
                    }
                    for index in range(1, 3)
                ],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
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
            "BOTS": [{"id": "bot-a", "token": "token"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat"}],
            "CHANNELS": [],
        }

        def fake_telegram(_token, _method, params):
            sent_titles.append(params.get("text") or params.get("caption") or "")
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=2,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(4, result["sent"])
        self.assertEqual(["Movie 1", "Movie 2", "Series 1", "Series 2"], sent_titles)

    def test_send_notifications_allows_same_item_for_different_rule_recipients(self):
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "signature": "server-a:tmdb:1",
                        "item_type": "movie",
                        "title": "Movie 1",
                        "year": 2026,
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": [],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
                {
                    "id": "rule-b",
                    "name": "Rule B",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-b",
                },
            ],
        }
        telegram_settings = {
            "PRESETS": [
                {
                    "id": "telegram-a",
                    "name": "Telegram A",
                    "bot_ids": ["bot-a"],
                    "group_ids": ["group-a"],
                    "channel_ids": [],
                },
                {
                    "id": "telegram-b",
                    "name": "Telegram B",
                    "bot_ids": ["bot-b"],
                    "group_ids": ["group-b"],
                    "channel_ids": [],
                },
            ],
            "BOTS": [
                {"id": "bot-a", "token": "token-a"},
                {"id": "bot-b", "token": "token-b"},
            ],
            "GROUPS": [
                {"id": "group-a", "chat_id": "chat-a"},
                {"id": "group-b", "chat_id": "chat-b"},
            ],
            "CHANNELS": [],
        }

        def fake_telegram(token, _method, params):
            deliveries.append((token, params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["sent"], 2)
        self.assertEqual(
            deliveries,
            [
                ("token-a", "chat-a", "Movie 1"),
                ("token-b", "chat-b", "Movie 1"),
            ],
        )

    def test_send_notifications_retries_only_failed_destinations(self):
        state = {}
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "signature": "server-a:tmdb:1",
                        "item_type": "movie",
                        "title": "Movie 1",
                        "year": 2026,
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": [],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
            ],
        }
        telegram_settings = {
            "PRESETS": [
                {
                    "id": "telegram-a",
                    "name": "Telegram",
                    "bot_ids": ["bot-a"],
                    "group_ids": ["group-ok", "group-fail"],
                    "channel_ids": [],
                },
            ],
            "BOTS": [{"id": "bot-a", "token": "token-a"}],
            "GROUPS": [
                {"id": "group-ok", "chat_id": "chat-ok"},
                {"id": "group-fail", "chat_id": "chat-fail"},
            ],
            "CHANNELS": [],
        }

        def save_state(payload):
            state.clear()
            state.update(deepcopy(payload))

        def first_telegram(_token, _method, params):
            chat_id = params.get("chat_id")
            deliveries.append(("first", chat_id, params.get("text") or params.get("caption")))
            if chat_id == "chat-fail":
                return False, "forced failure", {}
            return True, "OK", {}

        def second_telegram(_token, _method, params):
            deliveries.append(("second", params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        common_patches = [
            patch("emby_latest.db_cache.load_cache", return_value=cache_payload),
            patch("emby_latest.db_state.load_state", side_effect=lambda: deepcopy(state)),
            patch("emby_latest.db_state.save_state", side_effect=save_state),
            patch("emby_latest.settings._load_latest_settings", return_value=latest_settings),
            patch("telegram._load_telegram_settings", return_value=telegram_settings),
            patch("emby_latest.jellyseerr._apply_jellyseerr_request_info", return_value=None),
            patch("time.sleep", return_value=None),
        ]

        for started_patch in common_patches:
            started_patch.start()
        try:
            with patch("emby_latest.notifications._telegram_api_request", side_effect=first_telegram):
                first = send_notifications(
                    per_server_limit=10,
                    config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
                )
            with patch("emby_latest.notifications._telegram_api_request", side_effect=second_telegram):
                second = send_notifications(
                    per_server_limit=10,
                    config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
                )
        finally:
            for started_patch in reversed(common_patches):
                started_patch.stop()

        self.assertTrue(first["success"])
        self.assertEqual(1, first["sent"])
        self.assertEqual(1, first["failed"])
        self.assertTrue(second["success"])
        self.assertEqual(1, second["sent"])
        self.assertEqual(
            [
                ("first", "chat-ok", "Movie 1"),
                ("first", "chat-fail", "Movie 1"),
                ("second", "chat-fail", "Movie 1"),
            ],
            deliveries,
        )
        movie_state = state["server-a"]["movies"]["items"]["server-a:tmdb:1"]
        self.assertTrue(movie_state["notified"])

    def test_send_notifications_sends_same_item_again_for_new_batch(self):
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "signature": "server-a:tmdb:1",
                        "item_type": "movie",
                        "title": "Movie 1",
                        "year": 2026,
                        "added_at": "2026-07-16T10:00:00+00:00",
                        "batch_id": "server-a:movie:20260716100000:20260716100000",
                        "update_type": "update",
                        "update_label": "Nuova versione",
                    }
                ],
                "series": [],
            }
        }
        latest_state = {
            "server-a": {
                "movies": {
                    "items": {
                        "server-a:tmdb:1": {
                            "item_id": "movie-1",
                            "signature": "server-a:tmdb:1",
                            "title": "Movie 1",
                            "notified": True,
                            "notified_at": "2026-07-15T10:02:00+00:00",
                            "notified_destinations": {
                                "bot-a:chat-a": {
                                    "bot_id": "bot-a",
                                    "chat_id": "chat-a",
                                    "notified_at": "2026-07-15T10:02:00+00:00",
                                }
                            },
                        }
                    }
                },
                "series": {"items": {}},
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": [],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
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
                },
            ],
            "BOTS": [{"id": "bot-a", "token": "token-a"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat-a"}],
            "CHANNELS": [],
        }

        def fake_telegram(_token, _method, params):
            deliveries.append((params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value=deepcopy(latest_state),
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(1, result["sent"])
        self.assertEqual([("chat-a", "Movie 1")], deliveries)

    def test_send_notifications_applies_per_server_limit_after_pending_destination_filter(self):
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-old",
                        "signature": "server-a:tmdb:old",
                        "item_type": "movie",
                        "title": "Old Movie",
                        "year": 2026,
                        "added_at": "2026-07-15T10:00:00+00:00",
                    },
                    {
                        "server_id": "server-a",
                        "item_id": "movie-new",
                        "signature": "server-a:tmdb:new",
                        "item_type": "movie",
                        "title": "New Movie",
                        "year": 2026,
                        "added_at": "2026-07-15T10:01:00+00:00",
                    },
                ],
                "series": [],
            }
        }
        latest_state = {
            "server-a": {
                "movies": {
                    "items": {
                        "server-a:tmdb:old": {
                            "item_id": "movie-old",
                            "signature": "server-a:tmdb:old",
                            "title": "Old Movie",
                            "notified": True,
                            "notified_at": "2026-07-15T10:02:00+00:00",
                            "notified_destinations": {
                                "bot-a:chat-a": {
                                    "bot_id": "bot-a",
                                    "chat_id": "chat-a",
                                    "notified_at": "2026-07-15T10:02:00+00:00",
                                }
                            },
                        }
                    }
                },
                "series": {"items": {}},
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": [],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
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
                },
            ],
            "BOTS": [{"id": "bot-a", "token": "token-a"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat-a"}],
            "CHANNELS": [],
        }

        def fake_telegram(_token, _method, params):
            deliveries.append((params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value=latest_state,
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=1,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(1, result["sent"])
        self.assertEqual([("chat-a", "New Movie")], deliveries)

    def test_send_notifications_server_filter_skips_rules_for_other_servers_without_warning(self):
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-a",
                        "signature": "server-a:tmdb:a",
                        "item_type": "movie",
                        "title": "Movie A",
                        "year": 2026,
                        "added_at": "2026-07-15T10:00:00+00:00",
                    },
                    {
                        "server_id": "server-b",
                        "item_id": "movie-b",
                        "signature": "server-b:tmdb:b",
                        "item_type": "movie",
                        "title": "Movie B",
                        "year": 2026,
                        "added_at": "2026-07-15T10:01:00+00:00",
                    },
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": ["telegram-a"],
            "NOTIFICATION_RULES": [
                {
                    "id": "rule-a",
                    "name": "Rule A",
                    "enabled": True,
                    "server_ids": ["server-a"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
                {
                    "id": "rule-b",
                    "name": "Rule B",
                    "enabled": True,
                    "server_ids": ["server-b"],
                    "preset_id": "preset-a",
                    "telegram_config_id": "telegram-a",
                },
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
            "BOTS": [{"id": "bot-a", "token": "token-a"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat-a"}],
            "CHANNELS": [],
        }

        def fake_telegram(token, _method, params):
            deliveries.append((token, params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=10,
                server_filter="server-a",
                config={
                    "DATABASE": {"ENABLED": True},
                    "EMBY": {"SERVERS": [{"id": "server-a"}, {"id": "server-b"}]},
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(deliveries, [("token-a", "chat-a", "Movie A")])

    def test_send_notifications_requires_active_notification_rule(self):
        deliveries = []
        cache_payload = {
            "payload": {
                "movies": [
                    {
                        "server_id": "server-a",
                        "item_id": "movie-1",
                        "signature": "server-a:tmdb:1",
                        "item_type": "movie",
                        "title": "Movie 1",
                        "year": 2026,
                        "added_at": "2026-07-15T10:00:00+00:00",
                    }
                ],
                "series": [],
            }
        }
        latest_settings = {
            "PRESETS": [{"id": "preset-a", "name": "Preset", "template": "{title}"}],
            "ACTIVE_PRESET_ID": "preset-a",
            "TELEGRAM_PRESET_IDS": ["telegram-a"],
            "NOTIFICATION_RULES": [],
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
            "BOTS": [{"id": "bot-a", "token": "token-a"}],
            "GROUPS": [{"id": "group-a", "chat_id": "chat-a"}],
            "CHANNELS": [],
        }

        def fake_telegram(token, _method, params):
            deliveries.append((token, params.get("chat_id"), params.get("text") or params.get("caption")))
            return True, "OK", {}

        with patch("emby_latest.db_cache.load_cache", return_value=cache_payload), patch(
            "emby_latest.db_state.load_state",
            return_value={},
        ), patch("emby_latest.db_state.save_state", return_value=None), patch(
            "emby_latest.settings._load_latest_settings",
            return_value=latest_settings,
        ), patch("telegram._load_telegram_settings", return_value=telegram_settings), patch(
            "emby_latest.jellyseerr._apply_jellyseerr_request_info",
            return_value=None,
        ), patch("emby_latest.notifications._telegram_api_request", side_effect=fake_telegram), patch(
            "time.sleep",
            return_value=None,
        ):
            result = send_notifications(
                per_server_limit=10,
                config={"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": [{"id": "server-a"}]}},
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["sent"], 0)
        self.assertIn("Crea o attiva almeno una regola di notifica", result["message"])
        self.assertEqual(deliveries, [])


if __name__ == "__main__":
    unittest.main()
