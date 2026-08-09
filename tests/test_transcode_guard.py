"""Transcode Guard policy and service behavior."""

from __future__ import annotations

import pytest

from emby_runtime.transcode_guard import (
    DEFAULT_TRANSCODE_GUARD_SETTINGS,
    TRANSCODE_GUARD_MODES,
    TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY,
    TRANSCODE_GUARD_SETTINGS_KEY,
    TRANSCODE_GUARD_STREAM_LOG_KEY,
    TranscodeGuardService,
    classify_stream,
    normalize_transcode_guard_settings,
)
from emby_runtime.streams import EmbyStreamsManager


def test_policy_blocks_only_real_4k_video_transcode():
    settings = normalize_transcode_guard_settings({})

    decision = classify_stream({
        "session_id": "s1",
        "title": "Big Movie",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
        "transcode_reasons": ["VideoCodecNotSupported"],
    }, settings)

    assert decision["category"] == "video_transcode"
    assert decision["should_enforce"] is True
    assert decision["severity"] == "danger"


def test_default_fetch_sessions_reuses_shared_stream_cache(monkeypatch):
    from emby_runtime import transcode_guard as transcode_guard_module

    manager = EmbyStreamsManager()
    calls = []

    def fetch_sessions(server):
        calls.append(server["id"])
        return ([{"session_id": f"s{len(calls)}"}], None)

    monkeypatch.setattr("emby_runtime.streams.get_streams_manager", lambda: manager)
    monkeypatch.setattr("emby_runtime.api_clients._fetch_emby_active_sessions", fetch_sessions)

    first, first_error = transcode_guard_module._default_fetch_sessions({"id": "server-a"})
    second, second_error = transcode_guard_module._default_fetch_sessions({"id": "server-a"})

    assert first_error is None
    assert second_error is None
    assert first[0]["session_id"] == "s1"
    assert second[0]["session_id"] == "s1"
    assert calls == ["server-a"]


def test_policy_allows_audio_only_transcode_and_container_remux():
    settings = normalize_transcode_guard_settings({})

    audio_only = classify_stream({
        "session_id": "s2",
        "title": "Audio Only",
        "video_height": 2160,
        "video_mode": "diretta",
        "audio_mode": "transcodifica",
        "play_method": "Transcode",
        "transcode_container": "ts",
        "transcode_reasons": ["AudioCodecNotSupported"],
    }, settings)
    remux = classify_stream({
        "session_id": "s3",
        "title": "Remux",
        "video_height": 2160,
        "video_mode": "diretta",
        "audio_mode": "diretta",
        "play_method": "DirectStream",
        "container": "mkv",
        "stream_container": "mkv",
        "transcode_container": "mp4",
    }, settings)

    assert audio_only["category"] == "audio_transcode"
    assert audio_only["should_enforce"] is False
    assert remux["category"] == "container_remux"
    assert remux["should_enforce"] is False


def test_policy_does_not_call_directstream_remux_without_container_change():
    settings = normalize_transcode_guard_settings({})

    decision = classify_stream({
        "session_id": "s-directstream",
        "title": "Devs S1:E7",
        "video_height": 1080,
        "video_mode": "diretta",
        "audio_mode": "diretta",
        "play_method": "DirectStream",
        "container": "mkv",
        "stream_container": "mkv",
    }, settings)

    assert decision["category"] == "direct"
    assert decision["should_enforce"] is False


def test_service_records_container_remux_as_direct_stream_information_not_violation():
    storage = _Storage()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    streams = [{
        "session_id": "remux-1",
        "item_id": "movie-1",
        "title": "Container Only",
        "user": "roy",
        "client": "Emby Theater",
        "device": "Windows",
        "device_id": "device-remux",
        "media_type": "Movie",
        "video_height": 2160,
        "video_width": 3840,
        "video_mode": "diretta",
        "audio_mode": "diretta",
        "play_method": "DirectStream",
        "container": "mkv",
        "stream_container": "mkv",
        "transcode_container": "hls",
        "transcode_reasons": ["ContainerNotSupported", "DirectPlayError"],
    }]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (streams, None),
        send_message=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected message")),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
    )
    service.save_settings({
        "enabled": True,
        "stream_history_retention_days": 0,
        "rules": [{
            "id": "video-rule",
            "name": "Solo transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 2160,
            "mode": "monitor",
        }],
    })

    service.check_once()

    row = service.get_status()["stream_history"]["rows"][0]
    assert row["session_id"] == "remux-1"
    assert row["last_decision_category"] == "container_remux"
    assert row["tags"] == ["container remux", "direct stream", "corretta"]
    assert row["violations_committed"] == []
    assert row["transcode_reasons"] == ["ContainerNotSupported", "DirectPlayError"]


def test_service_never_warns_or_stops_allowed_container_remux_with_legacy_stop_mode():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    streams = [{
        "session_id": "remux-1",
        "item_id": "episode-7",
        "title": "Devs S1:E7",
        "user": "fb_johnsmith",
        "client": "Emby for LG",
        "device": "LG Smart TV",
        "device_id": "lg-1",
        "media_type": "Episode",
        "video_height": 1080,
        "video_width": 1920,
        "video_mode": "diretta",
        "audio_mode": "diretta",
        "play_method": "DirectStream",
        "container": "mkv",
        "stream_container": "mkv",
        "transcode_container": "hls",
        "transcode_reasons": ["ContainerNotSupported"],
    }]
    messages = []
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (streams, None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
        "correction_window_seconds": 1,
        "rules": [{
            "id": "video-1440",
            "name": "Transcode video 1440p+",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn_then_stop",
        }],
    })

    first = service.check_once()
    clock.advance(6)
    second = service.check_once()

    assert first["violations"] == 0
    assert second["violations"] == 0
    assert messages == []
    assert stops == []
    row = service.get_status()["stream_history"]["rows"][0]
    assert row["last_decision_category"] == "container_remux"
    assert row["tags"] == ["container remux", "direct stream", "corretta"]
    assert row["violations_committed"] == []


def test_decorated_stream_does_not_inherit_stopped_state_when_current_decision_is_allowed():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
    })
    stream = {
        "session_id": "session-1",
        "title": "Devs S1:E7",
        "video_height": 1080,
        "video_mode": "diretta",
        "audio_mode": "diretta",
        "play_method": "DirectStream",
        "container": "mkv",
        "stream_container": "mkv",
        "transcode_container": "hls",
    }
    with service._lock:
        service._violations[service._violation_key("server-a", "session-1", "default")] = {
            "state": "stopped",
            "first_seen_at": "2026-07-22T19:44:00+00:00",
            "warned_at": "2026-07-22T19:44:01+00:00",
            "stopped_at": "2026-07-22T19:44:30+00:00",
        }

    decision = service.decorate_streams("server-a", [stream])[0]["transcode_guard"]

    assert decision["category"] == "container_remux"
    assert decision["should_enforce"] is False
    assert "state" not in decision
    assert "stopped_at" not in decision


def test_policy_does_not_block_unknown_height_by_default():
    settings = normalize_transcode_guard_settings({})

    decision = classify_stream({
        "session_id": "s4",
        "title": "Unknown",
        "video_mode": "transcodifica",
        "audio_mode": "transcodifica",
    }, settings)

    assert decision["category"] == "unknown"
    assert decision["should_enforce"] is False
    assert decision["reason"] == "Altezza video sorgente non disponibile"


def test_policy_can_exclude_device_and_ip_networks():
    settings = normalize_transcode_guard_settings({
        "excluded_devices": "Shield",
        "excluded_ips": "192.168.1.0/24",
    })

    by_device = classify_stream({
        "session_id": "s5",
        "title": "Device",
        "device": "Shield",
        "ip": "10.0.0.8",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)
    by_ip = classify_stream({
        "session_id": "s6",
        "title": "Ip",
        "device": "Browser",
        "ip": "192.168.1.24:8096",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert by_device["category"] == "excluded"
    assert by_device["should_enforce"] is False
    assert by_ip["category"] == "excluded"
    assert by_ip["reason"] == "IP escluso"


def test_settings_normalization_keeps_safe_defaults():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "min_source_height": "2160",
        "grace_seconds": "12",
        "correction_window_seconds": "75",
        "poll_interval_seconds": "2",
        "message_display_mode": "confirmation",
        "warning_timeout_ms": "300000",
        "max_warnings": "3",
        "message_cooldown_seconds": "45",
        "excluded_users": "roy, admin",
        "excluded_devices": "Shield, Apple TV",
        "excluded_ips": "10.0.0.0/24",
    })

    assert DEFAULT_TRANSCODE_GUARD_SETTINGS["mode"] == "monitor"
    assert settings["enabled"] is True
    assert settings["mode"] == "warn_then_stop"
    assert settings["min_source_height"] == 2160
    assert settings["grace_seconds"] == 0
    assert settings["correction_window_seconds"] == 75
    assert settings["poll_interval_seconds"] == 2
    assert settings["message_display_mode"] == "confirmation"
    assert settings["warning_timeout_ms"] == 300000
    assert settings["max_warnings"] == 3
    assert settings["message_cooldown_seconds"] == 45
    assert settings["excluded_users"] == ["roy", "admin"]
    assert settings["excluded_devices"] == ["Shield", "Apple TV"]
    assert settings["excluded_ips"] == ["10.0.0.0/24"]


def test_pause_modes_are_not_available_and_legacy_values_map_to_stop_modes():
    pause_settings = normalize_transcode_guard_settings({
        "enabled": True,
        "mode": "pause",
        "server_ids": ["server-a"],
    })
    warn_pause_settings = normalize_transcode_guard_settings({
        "enabled": True,
        "mode": "warn_then_pause",
        "server_ids": ["server-a"],
    })

    assert "pause" not in TRANSCODE_GUARD_MODES
    assert "warn_then_pause" not in TRANSCODE_GUARD_MODES
    assert pause_settings["mode"] == "stop"
    assert pause_settings["rules"][0]["mode"] == "stop"
    assert warn_pause_settings["mode"] == "warn_then_stop"
    assert warn_pause_settings["rules"][0]["mode"] == "warn_then_stop"


def test_settings_normalization_migrates_single_policy_to_initial_rule():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "min_source_height": 1440,
        "message_header": "Vecchia policy",
        "message_text": "Correggi {title}",
    })

    assert settings["enabled"] is True
    assert settings["mode"] == "warn_then_stop"
    assert len(settings["rules"]) == 1
    rule = settings["rules"][0]
    assert rule["id"] == "legacy-video-transcode"
    assert rule["name"] == "Transcode video sopra soglia"
    assert rule["enabled"] is True
    assert rule["profile"] == "video_transcode_threshold"
    assert rule["min_source_height"] == 1440
    assert rule["mode"] == "warn_then_stop"
    assert rule["message_header"] == "Vecchia policy"
    assert rule["message_text"] == "Correggi {title}"


def test_legacy_profiles_migrate_to_explicit_stream_criteria():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {"id": "video", "profile": "any_video_transcode"},
            {"id": "video-audio", "profile": "video_audio_transcode"},
            {"id": "audio", "profile": "audio_transcode"},
            {"id": "remux", "profile": "remux"},
        ],
    })

    by_id = {rule["id"]: rule for rule in settings["rules"]}
    assert by_id["video"]["video_state"] == "transcode"
    assert by_id["video"]["audio_state"] == "any"
    assert by_id["video"]["remux_state"] == "any"
    assert by_id["video"]["min_source_height"] == 0
    assert by_id["video-audio"]["video_state"] == "transcode"
    assert by_id["video-audio"]["audio_state"] == "transcode"
    assert by_id["audio"]["video_state"] == "direct"
    assert by_id["audio"]["audio_state"] == "transcode"
    assert by_id["remux"]["video_state"] == "direct"
    assert by_id["remux"]["audio_state"] == "direct"
    assert by_id["remux"]["remux_state"] == "present"


def test_rule_stream_criteria_match_exact_video_audio_combinations():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "video-only",
                "name": "Solo video",
                "enabled": True,
                "server_ids": ["server-a"],
                "video_state": "transcode",
                "audio_state": "direct",
                "remux_state": "any",
                "min_source_height": 0,
                "mode": "warn",
            },
        ],
    })

    video_only = classify_stream({
        "server_id": "server-a",
        "session_id": "video-only",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)
    video_audio = classify_stream({
        "server_id": "server-a",
        "session_id": "video-audio",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "transcodifica",
    }, settings)

    assert video_only["rule_id"] == "video-only"
    assert video_only["category"] == "video_transcode"
    assert video_audio["rule_id"] == ""
    assert video_audio["should_enforce"] is False


def test_rule_stream_criteria_can_require_remux_presence_or_absence():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "video-remux",
                "name": "Video con remux",
                "enabled": True,
                "server_ids": ["server-a"],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "present",
                "min_source_height": 0,
                "mode": "warn",
            },
        ],
    })

    with_remux = classify_stream({
        "server_id": "server-a",
        "session_id": "with-remux",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
        "container": "mkv",
        "transcode_container": "mp4",
    }, settings)
    without_remux = classify_stream({
        "server_id": "server-a",
        "session_id": "without-remux",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert with_remux["rule_id"] == "video-remux"
    assert without_remux["rule_id"] == ""


def test_quality_threshold_uses_width_and_height_to_detect_scope_4k():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "scope-4k",
                "name": "Scope 4K",
                "enabled": True,
                "server_ids": ["server-a"],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
                "min_source_height": 2160,
                "mode": "warn",
            },
        ],
    })

    decision = classify_stream({
        "server_id": "server-a",
        "session_id": "scope",
        "title": "Movie",
        "video_width": 3840,
        "video_height": 1604,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert decision["rule_id"] == "scope-4k"
    assert decision["source_height"] == 1604
    assert decision["source_quality_tier"] == 2160
    assert decision["threshold"] == 2160


def test_rules_are_evaluated_by_order_and_disabled_rules_are_skipped():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "browser",
                "name": "Avviso browser",
                "enabled": True,
                "profile": "browser_playback",
                "mode": "warn",
                "message_text": "Usa un client nativo",
            },
            {
                "id": "4k",
                "name": "Blocco 4K",
                "enabled": True,
                "profile": "video_transcode_threshold",
                "mode": "stop",
                "min_source_height": 2160,
            },
        ],
    })

    decision = classify_stream({
        "session_id": "s-browser",
        "title": "Movie",
        "client": "Chrome",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert decision["rule_id"] == "browser"
    assert decision["rule_name"] == "Avviso browser"
    assert decision["mode"] == "warn"
    assert decision["should_enforce"] is True

    settings["rules"][0]["enabled"] = False
    decision_after_disable = classify_stream({
        "session_id": "s-browser",
        "title": "Movie",
        "client": "Chrome",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert decision_after_disable["rule_id"] == "4k"
    assert decision_after_disable["mode"] == "stop"


def test_rule_exclusions_are_scoped_to_the_rule_and_allow_later_rules():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "4k",
                "name": "Blocco 4K",
                "enabled": True,
                "profile": "video_transcode_threshold",
                "mode": "stop",
                "min_source_height": 2160,
                "excluded_users": "roy",
            },
            {
                "id": "browser",
                "name": "Avviso browser",
                "enabled": True,
                "profile": "browser_playback",
                "mode": "warn",
            },
        ],
    })

    decision = classify_stream({
        "session_id": "s-browser",
        "title": "Movie",
        "user": "roy",
        "client": "Chrome",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert settings["rules"][0]["excluded_users"] == ["roy"]
    assert decision["rule_id"] == "browser"
    assert decision["rule_name"] == "Avviso browser"
    assert decision["mode"] == "warn"


def test_rule_server_scope_is_scoped_to_the_rule_and_allows_later_rules():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "purple-4k",
                "name": "Blocco 4K Purple",
                "enabled": True,
                "server_ids": ["purple"],
                "profile": "video_transcode_threshold",
                "mode": "stop",
                "min_source_height": 2160,
            },
            {
                "id": "green-browser",
                "name": "Avviso browser Green",
                "enabled": True,
                "server_ids": ["green"],
                "profile": "browser_playback",
                "mode": "warn",
            },
        ],
    })

    decision = classify_stream({
        "server_id": "green",
        "session_id": "s-browser",
        "title": "Movie",
        "client": "Chrome",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert settings["rules"][0]["server_ids"] == ["purple"]
    assert decision["rule_id"] == "green-browser"
    assert decision["rule_name"] == "Avviso browser Green"


def test_rule_without_server_scope_does_not_apply_to_any_server():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "4k",
                "name": "Blocco 4K",
                "enabled": True,
                "server_ids": [],
                "profile": "video_transcode_threshold",
                "mode": "stop",
                "min_source_height": 2160,
            },
        ],
    })

    decision = classify_stream({
        "server_id": "green",
        "session_id": "s-4k",
        "title": "Movie",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert decision["rule_id"] == ""
    assert decision["category"] == "video_transcode"
    assert decision["should_enforce"] is False


def test_legacy_global_exclusions_migrate_into_the_initial_rule():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "excluded_users": "roy, admin",
        "excluded_clients": "Chrome",
        "excluded_devices": "Shield",
        "excluded_ips": "10.0.0.0/24",
    })

    rule = settings["rules"][0]
    assert rule["excluded_users"] == ["roy", "admin"]
    assert rule["excluded_clients"] == ["Chrome"]
    assert rule["excluded_devices"] == ["Shield"]
    assert rule["excluded_ips"] == ["10.0.0.0/24"]


def test_legacy_global_server_scope_migrates_into_the_initial_rule():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "server_ids": ["purple", "green"],
    })

    assert settings["server_ids"] == ["purple", "green"]
    assert settings["rules"][0]["server_ids"] == ["purple", "green"]


def test_existing_rules_do_not_inherit_top_level_scope_fields():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "server_ids": ["purple"],
        "excluded_users": ["roy"],
        "excluded_clients": ["Browser"],
        "excluded_devices": ["iPad"],
        "excluded_ips": ["10.0.0.5"],
        "rules": [
            {
                "id": "first",
                "name": "Prima",
                "enabled": True,
                "server_ids": ["green"],
                "excluded_users": ["admin"],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
            },
            {
                "id": "second",
                "name": "Seconda",
                "enabled": False,
                "server_ids": [],
                "excluded_users": [],
                "excluded_clients": [],
                "excluded_devices": [],
                "excluded_ips": [],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
            },
        ],
    })

    first, second = settings["rules"]

    assert first["server_ids"] == ["green"]
    assert first["excluded_users"] == ["admin"]
    assert first["excluded_clients"] == []
    assert first["excluded_devices"] == []
    assert first["excluded_ips"] == []

    assert second["enabled"] is False
    assert second["server_ids"] == []
    assert second["excluded_users"] == []
    assert second["excluded_clients"] == []
    assert second["excluded_devices"] == []
    assert second["excluded_ips"] == []


def test_legacy_rule_groups_are_flattened_to_ordered_rules_with_explicit_child_scope():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "transcode-group",
                "name": "Avvisi transcode",
                "type": "group",
                "enabled": True,
                "profile": "any_transcode",
                "server_ids": ["server-a"],
                "excluded_users": ["admin"],
                "message_header": "Gruppo",
                "children": [
                    {
                        "id": "video-audio",
                        "name": "Video e audio",
                        "enabled": True,
                        "profile": "video_audio_transcode",
                        "mode": "warn",
                        "server_ids": ["server-a"],
                        "excluded_users": ["admin"],
                        "message_text": "Video e audio in transcode",
                    },
                    {
                        "id": "audio",
                        "name": "Solo audio",
                        "enabled": True,
                        "profile": "audio_transcode",
                        "mode": "warn",
                        "server_ids": ["server-a"],
                        "excluded_users": ["admin"],
                        "message_text": "Solo audio in transcode",
                    },
                ],
            },
        ],
    })

    assert [rule["id"] for rule in settings["rules"]] == ["video-audio", "audio"]
    assert all(rule["type"] == "rule" for rule in settings["rules"])
    assert all(rule["children"] == [] for rule in settings["rules"])
    assert all(rule["server_ids"] == ["server-a"] for rule in settings["rules"])
    assert all(rule["excluded_users"] == ["admin"] for rule in settings["rules"])
    assert all(rule["message_header"] == "Gruppo" for rule in settings["rules"])

    video_audio = classify_stream({
        "server_id": "server-a",
        "session_id": "s-va",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "transcodifica",
    }, settings)
    audio_only = classify_stream({
        "server_id": "server-a",
        "session_id": "s-audio",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "diretta",
        "audio_mode": "transcodifica",
    }, settings)

    assert video_audio["rule_id"] == "video-audio"
    assert video_audio["message_text"] == "Video e audio in transcode"
    assert audio_only["rule_id"] == "audio"
    assert audio_only["message_text"] == "Solo audio in transcode"


def test_flattened_legacy_group_does_not_inherit_rule_scope_when_child_is_empty():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "old-group",
                "name": "Vecchio gruppo",
                "type": "group",
                "enabled": True,
                "server_ids": ["purple"],
                "excluded_users": ["roy"],
                "excluded_clients": ["Browser"],
                "excluded_devices": ["iPad"],
                "excluded_ips": ["10.0.0.5"],
                "children": [
                    {
                        "id": "explicit-child",
                        "name": "Figlia esplicita",
                        "enabled": True,
                        "server_ids": ["green"],
                        "excluded_users": ["admin"],
                    },
                    {
                        "id": "empty-child",
                        "name": "Figlia vuota",
                        "enabled": False,
                        "server_ids": [],
                        "excluded_users": [],
                        "excluded_clients": [],
                        "excluded_devices": [],
                        "excluded_ips": [],
                    },
                ],
            },
        ],
    })

    explicit_child, empty_child = settings["rules"]

    assert explicit_child["server_ids"] == ["green"]
    assert explicit_child["excluded_users"] == ["admin"]
    assert explicit_child["excluded_clients"] == []
    assert explicit_child["excluded_devices"] == []
    assert explicit_child["excluded_ips"] == []

    assert empty_child["enabled"] is False
    assert empty_child["server_ids"] == []
    assert empty_child["excluded_users"] == []
    assert empty_child["excluded_clients"] == []
    assert empty_child["excluded_devices"] == []
    assert empty_child["excluded_ips"] == []


def test_flattened_legacy_group_without_matching_child_is_not_a_false_violation():
    settings = normalize_transcode_guard_settings({
        "enabled": True,
        "rules": [
            {
                "id": "transcode-group",
                "name": "Avvisi transcode",
                "type": "group",
                "enabled": True,
                "profile": "any_transcode",
                "mode": "monitor",
                "children": [
                    {
                        "id": "audio",
                        "name": "Solo audio",
                        "enabled": True,
                        "profile": "audio_transcode",
                        "mode": "warn",
                    },
                ],
            },
        ],
    })

    assert [rule["id"] for rule in settings["rules"]] == ["audio"]
    assert settings["rules"][0]["type"] == "rule"

    decision = classify_stream({
        "session_id": "s-video",
        "title": "Movie",
        "video_height": 1080,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }, settings)

    assert decision["category"] == "video_transcode"
    assert decision["should_enforce"] is False


def test_service_rejects_enabled_rule_without_selected_server():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)

    with pytest.raises(ValueError, match="Seleziona almeno un server"):
        service.save_settings({
            "enabled": True,
            "rules": [
                {
                    "id": "no-server",
                    "name": "Senza server",
                    "enabled": True,
                    "server_ids": [],
                    "video_state": "transcode",
                    "audio_state": "any",
                    "remux_state": "any",
                },
            ],
        })

    assert storage.values == {}


def test_service_does_not_reapply_previous_global_servers_to_disabled_rule():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)
    service.save_settings({
        "enabled": True,
        "rules": [
            {
                "id": "with-servers",
                "name": "Con server",
                "enabled": True,
                "server_ids": ["purple", "blue", "red", "green"],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
            },
        ],
    })

    settings = service.save_settings({
        "enabled": True,
        "rules": [
            {
                "id": "without-servers",
                "name": "Senza server",
                "enabled": False,
                "server_ids": [],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
            },
        ],
    })

    assert settings["rules"][0]["enabled"] is False
    assert settings["rules"][0]["server_ids"] == []
    assert settings["server_ids"] == []


def test_service_save_settings_merges_existing_policy_fields():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "min_source_height": 1080,
        "grace_seconds": 30,
        "correction_window_seconds": 120,
        "poll_interval_seconds": 8,
        "max_warnings": 2,
        "message_cooldown_seconds": 40,
        "message_display_mode": "confirmation",
        "allow_audio_only_transcode": False,
        "allow_container_remux": False,
        "ignore_paused": False,
        "message_header": "Attenzione streaming",
        "message_text": "Correggi {title}",
        "server_ids": ["server-a"],
        "excluded_users": ["admin"],
        "excluded_devices": ["Shield"],
        "excluded_ips": ["10.0.0.0/24"],
    })

    settings = service.save_settings({"enabled": False})

    assert settings["enabled"] is False
    assert settings["mode"] == "warn_then_stop"
    assert settings["min_source_height"] == 1080
    assert settings["grace_seconds"] == 0
    assert settings["correction_window_seconds"] == 120
    assert settings["poll_interval_seconds"] == 8
    assert settings["max_warnings"] == 2
    assert settings["message_cooldown_seconds"] == 40
    assert settings["message_display_mode"] == "confirmation"
    assert settings["allow_audio_only_transcode"] is False
    assert settings["allow_container_remux"] is False
    assert settings["ignore_paused"] is False
    assert settings["message_header"] == "Attenzione streaming"
    assert settings["message_text"] == "Correggi {title}"
    assert settings["excluded_users"] == ["admin"]
    assert settings["excluded_devices"] == ["Shield"]
    assert settings["excluded_ips"] == ["10.0.0.0/24"]


class _Storage:
    def __init__(self):
        self.values = {}

    def get_key_value(self, key):
        return self.values.get(key)

    def set_key_value(self, key, value):
        self.values[key] = value


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_transcode_guard_loads_legacy_octohub_settings_key():
    storage = _Storage()
    storage.set_key_value(
        "octohub_transcode_guard:settings:v1",
        {"enabled": True, "poll_interval_seconds": 9},
    )
    service = TranscodeGuardService(storage_provider=lambda: storage)

    settings = service.load_settings()

    assert settings["enabled"] is True
    assert settings["poll_interval_seconds"] == 9
    assert TRANSCODE_GUARD_SETTINGS_KEY not in storage.values


class _Tracker:
    def __init__(self):
        self.started = []
        self.finished = []
        self.failed = []

    def start(self, kind, title, summary="", details=None, total=None):
        operation = {
            "id": f"op-{len(self.started) + 1}",
            "kind": kind,
            "title": title,
            "summary": summary,
            "details": details or {},
        }
        self.started.append(operation)
        return operation

    def finish(self, operation_id, message="Completato", result=None):
        self.finished.append((operation_id, message, result or {}))

    def fail(self, operation_id, message, result=None):
        self.failed.append((operation_id, message, result or {}))


class _AliveThread:
    def is_alive(self):
        return True


def test_start_wakes_existing_monitor_thread_after_settings_change():
    service = TranscodeGuardService(storage_provider=lambda: _Storage())
    service._thread = _AliveThread()

    started = service.start()

    assert started is False
    assert service._wake_event.is_set()


def test_service_warns_then_stops_persistent_video_transcode():
    storage = _Storage()
    clock = _Clock()
    tracker = _Tracker()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    stream = {
        "session_id": "session-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    messages = []
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([stream], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append((session_id, header, text, timeout_ms)) or (True, {}),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        operation_tracker_provider=lambda: tracker,
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
        "correction_window_seconds": 5,
    })

    first = service.check_once()
    clock.advance(6)
    second = service.check_once()

    assert first["violations"] == 1
    assert second["stopped"] == 1
    assert messages and messages[0][0] == "session-1"
    assert stops == ["session-1"]
    assert tracker.started[-1]["kind"] == "transcode_guard"
    assert tracker.finished[-1][1] == "Sessione fermata da Transcode Guard"


def test_service_warns_immediately_even_when_legacy_grace_seconds_is_set():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    stream = {
        "session_id": "session-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([stream], None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "grace_seconds": 10,
        "correction_window_seconds": 60,
    })

    result = service.check_once()

    assert result["warned"] == 1
    assert messages == ["session-1"]


def test_service_status_marks_disappeared_violation_as_user_exit():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    active_stream = {
        "session_id": "session-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    current_streams = [active_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(5)
    service.check_once()

    assert service.get_status()["recent_events"][0]["action_label"] == "avviso"
    assert len(service.get_status()["active_violations"]) == 1

    clock.advance(6)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "exit"]
    assert events[0]["action"] == "exit"
    assert events[0]["action_label"] == "avviso - uscito"
    assert events[0]["title"] == "Big Movie"
    assert events[0]["user"] == "roy"
    assert events[0]["server_name"] == "Blue"
    assert events[0]["outcome"] == "Uscita riproduzione"


def test_service_status_marks_same_session_corrected_stream_as_resolved():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    active_stream = {
        "session_id": "session-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    corrected_stream = dict(active_stream, video_mode="diretta")
    current_streams = [active_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [corrected_stream]
    clock.advance(5)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved"]
    assert events[0]["action"] == "resolved"
    assert events[0]["action_label"] == "avviso - risolto"
    assert events[0]["title"] == "Big Movie"
    assert events[0]["outcome"] == "Risolta"


def test_service_updates_single_intervention_row_from_warning_to_stop():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "video_height": 1604,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([stream], None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
        "correction_window_seconds": 1,
    })

    service.check_once()
    clock.advance(6)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "stop"]
    assert events[0]["action"] == "stop"
    assert events[0]["action_label"] == "avviso - stop"
    assert events[0]["title"] == "Dragon Trainer"
    assert events[0]["user"] == "Roy"
    assert events[0]["client"] == "Emby for macOS"
    assert events[0]["server_name"] == "Green"
    assert events[0]["source_height"] == 1604
    assert stops == ["session-1"]


def test_service_marks_matching_direct_playback_as_resolved_when_session_id_changes():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "video_height": 1604,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, session_id="session-2", video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "correction_window_seconds": 10,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(5)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved"]
    assert events[0]["action_label"] == "avviso - risolto"
    assert events[0]["session_id"] == "session-1"


def test_service_treats_brief_disappearance_before_direct_playback_as_parameter_change():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, session_id="session-2", video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()

    assert service.get_status()["recent_events"][0]["action_label"] == "avviso"

    current_streams[:] = [direct_stream]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved"]
    assert events[0]["action_label"] == "avviso - risolto"


def test_service_marks_exit_after_resolution_and_never_reopens_that_row():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(1)
    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved"]

    clock.advance(6)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved", "exit"]
    assert events[0]["action_label"] == "avviso - risolto - uscito"

    current_streams[:] = [dict(transcode_stream, session_id="session-2")]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == ["warn"]
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "resolved", "exit"]


def test_service_marks_corrected_playback_with_different_resolution_as_resolution_change():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    lower_resolution_direct_stream = dict(
        transcode_stream,
        session_id="session-2",
        video_height=1080,
        video_mode="diretta",
    )
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "correction_window_seconds": 10,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [lower_resolution_direct_stream]
    clock.advance(5)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == ["resolution_change"]
    assert events[0]["action_label"] == "Cambio Ris."
    assert events[0]["outcome"] == "Cambio risoluzione"
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]


def test_service_does_not_resolve_with_corrected_playback_from_different_device():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device": "MacBook",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    other_device_direct_stream = dict(
        transcode_stream,
        session_id="session-2",
        device="Apple TV",
        device_id="device-2",
        video_mode="diretta",
    )
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [other_device_direct_stream]
    clock.advance(5)
    service.check_once()

    assert service.get_status()["recent_events"][0]["action_label"] == "avviso"

    clock.advance(11)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "exit"]
    assert events[0]["action_label"] == "avviso - uscito"


def test_service_marks_partial_resolution_when_same_playback_still_violates_later_rule():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    video_audio_transcode = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "transcodifica",
    }
    audio_only_transcode = dict(
        video_audio_transcode,
        session_id="session-2",
        video_mode="diretta",
        audio_mode="transcodifica",
    )
    current_streams = [video_audio_transcode]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [
            {
                "id": "video",
                "name": "Transcode video",
                "enabled": True,
                "server_ids": ["server-a"],
                "video_state": "transcode",
                "audio_state": "any",
                "remux_state": "any",
                "min_source_height": 1440,
                "mode": "warn",
                "grace_seconds": 0,
            },
            {
                "id": "audio",
                "name": "Transcode audio",
                "enabled": True,
                "server_ids": ["server-a"],
                "video_state": "direct",
                "audio_state": "transcode",
                "remux_state": "any",
                "min_source_height": 0,
                "mode": "warn",
                "grace_seconds": 0,
            },
        ],
    })

    service.check_once()
    current_streams[:] = [audio_only_transcode]
    clock.advance(5)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    by_rule = {event["rule_id"]: event for event in events}
    assert by_rule["audio"]["action_label"] == "avviso"
    assert [action["action"] for action in by_rule["video"]["actions"]] == ["warn", "partial_resolved"]
    assert by_rule["video"]["action_label"] == "avviso - Risolto Parz."


def test_service_marks_old_session_as_exit_when_same_playback_still_violates_same_rule():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    first_violation = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    second_violation = dict(first_violation, session_id="session-2")
    current_streams = [first_violation]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [second_violation]
    clock.advance(5)
    service.check_once()
    clock.advance(11)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    assert any(
        event["session_id"] == "session-1"
        and [action["action"] for action in event["actions"]] == ["warn", "exit"]
        for event in events
    )
    assert any(
        event["session_id"] == "session-2"
        and [action["action"] for action in event["actions"]] == ["warn"]
        for event in events
    )


def test_service_records_later_success_after_user_exit_without_duplicates():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "video_height": 1604,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, session_id="session-2", video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "correction_window_seconds": 10,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(5)
    service.check_once()
    clock.advance(11)
    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(5)
    service.check_once()
    service.check_once()

    events = service.get_status()["recent_events"]
    assert [action["action"] for action in events[0]["actions"]] == ["resolved_later"]
    assert events[0]["action_label"] == "risolto in seguito"
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]
    assert events[1]["action_label"] == "avviso - uscito"
    assert len(events) == 2


def test_service_records_later_success_after_exit_even_within_stop_delay_when_mode_warn():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, session_id="session-2", video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "correction_window_seconds": 60,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(6)
    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(5)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == ["resolved_later"]
    assert events[0]["action_label"] == "risolto in seguito"
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]
    assert events[1]["action_label"] == "avviso - uscito"


def test_service_does_not_record_later_success_after_newer_resolved_event():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    second_transcode_stream = dict(transcode_stream, session_id="session-2")
    direct_stream = dict(second_transcode_stream, video_mode="diretta")
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(6)
    service.check_once()
    current_streams[:] = [second_transcode_stream]
    clock.advance(1)
    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(1)
    service.check_once()
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved"]
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]


def test_service_records_resolution_change_after_previous_exit_without_later_suffix():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    lower_resolution_direct_stream = dict(
        transcode_stream,
        session_id="session-2",
        video_height=1080,
        video_mode="diretta",
    )
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(5)
    service.check_once()
    clock.advance(11)
    service.check_once()
    current_streams[:] = [lower_resolution_direct_stream]
    clock.advance(5)
    service.check_once()
    service.check_once()

    events = service.get_status()["recent_events"]
    assert [action["action"] for action in events[0]["actions"]] == ["resolution_change"]
    assert events[0]["action_label"] == "Cambio Ris."
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]
    assert len(events) == 2


def test_service_does_not_record_resolution_change_after_resolved_exit():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_stream = dict(transcode_stream, video_mode="diretta")
    lower_resolution_direct_stream = dict(
        transcode_stream,
        session_id="session-2",
        video_height=1080,
        video_mode="diretta",
    )
    current_streams = [transcode_stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams[:] = [direct_stream]
    clock.advance(1)
    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(6)
    service.check_once()
    current_streams[:] = [lower_resolution_direct_stream]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [action["action"] for action in events[0]["actions"]] == ["warn", "resolved", "exit"]


def test_service_prefixes_resolution_change_when_new_resolution_still_violates_after_unresolved_exit():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    high_transcode = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    lower_transcode = dict(high_transcode, session_id="session-2", video_height=1080)
    current_streams = [high_transcode]
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 720,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(2)
    service.check_once()
    current_streams[:] = [lower_transcode]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-2"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == ["resolution_change", "warn"]
    assert events[0]["action_label"] == "Cambio Ris. - avviso"
    assert events[0]["source_height"] == 1080
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]


def test_service_reuses_recent_unresolved_exit_row_when_same_resolution_violation_returns():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    high_transcode = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    lower_transcode = dict(high_transcode, session_id="session-2", video_height=1080)
    lower_transcode_recreated = dict(lower_transcode, session_id="session-3")
    current_streams = [high_transcode]
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 720,
        "grace_seconds": 0,
        "max_warnings": 3,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(2)
    service.check_once()
    current_streams[:] = [lower_transcode]
    clock.advance(1)
    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(2)
    service.check_once()
    current_streams[:] = [lower_transcode_recreated]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-2", "session-3"]
    assert len(events) == 2
    assert [action["action"] for action in events[0]["actions"]] == [
        "resolution_change",
        "warn",
        "relapse",
        "warn",
    ]
    assert events[0]["action_label"] == "Cambio Ris. - avviso - ricaduta - avviso"
    assert [action["action"] for action in events[1]["actions"]] == ["warn", "exit"]


def test_service_does_not_reopen_resolution_change_row_when_source_resolution_changes_back():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    transcode_2160 = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    direct_1080 = dict(
        transcode_2160,
        session_id="session-2",
        video_height=1080,
        video_mode="diretta",
    )
    transcode_2160_again = dict(
        direct_1080,
        video_height=2160,
        video_mode="transcodifica",
    )
    current_streams = [transcode_2160]
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    current_streams.clear()
    clock.advance(1)
    service.check_once()
    clock.advance(2)
    service.check_once()
    current_streams[:] = [direct_1080]
    clock.advance(1)
    service.check_once()
    current_streams[:] = [transcode_2160_again]
    clock.advance(1)
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-2"]
    assert len(events) == 3
    assert events[0]["session_id"] == "session-2"
    assert events[0]["source_height"] == 2160
    assert [action["action"] for action in events[0]["actions"]] == ["warn"]
    assert events[1]["session_id"] == "session-2"
    assert events[1]["source_height"] == 1080
    assert [action["action"] for action in events[1]["actions"]] == ["resolution_change"]
    assert events[2]["session_id"] == "session-1"
    assert [action["action"] for action in events[2]["actions"]] == ["warn", "exit"]


def test_service_records_warning_error_without_counting_it_as_warning():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([stream], None),
        send_message=lambda *_args: (False, "client non raggiungibile"),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
    })

    result = service.check_once()

    events = service.get_status()["recent_events"]
    assert result["warned"] == 0
    assert [action["action"] for action in events[0]["actions"]] == ["warning_error"]
    assert events[0]["action_label"] == "errore avviso"
    assert events[0]["success"] is False


def test_service_persists_and_clears_intervention_rows():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Dragon Trainer",
        "user": "Roy",
        "client": "Emby for macOS",
        "video_height": 1604,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    current_streams = [stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "min_source_height": 1440,
        "grace_seconds": 0,
    })

    service.check_once()
    restored = TranscodeGuardService(storage_provider=lambda: storage)

    assert restored.get_status()["recent_events"][0]["action_label"] == "avviso"
    assert restored.clear_events() == 1
    assert restored.get_status()["recent_events"] == []


def test_service_does_not_delay_stop_with_extra_warning_when_correction_window_expired():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    stream = {
        "session_id": "session-expired",
        "title": "Big Movie",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    messages = []
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([stream], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append(session_id) or (True, {}),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
        "correction_window_seconds": 60,
        "message_cooldown_seconds": 30,
        "max_warnings": 4,
    })

    service.check_once()
    clock.advance(30)
    service.check_once()
    clock.advance(30)
    result = service.check_once()

    assert result["stopped"] == 1
    assert messages == ["session-expired", "session-expired"]
    assert stops == ["session-expired"]


def test_service_message_template_supports_device_and_reasons_placeholders():
    storage = _Storage()
    tracker = _Tracker()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([{
            "session_id": "session-template",
            "title": "Big Movie",
            "user": "roy",
            "client": "Emby Web",
            "device": "MacBook",
            "video_height": 2160,
            "video_mode": "transcodifica",
            "audio_mode": "diretta",
            "transcode_reasons": ["VideoCodecNotSupported"],
        }], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append((session_id, header, text, timeout_ms)) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        operation_tracker_provider=lambda: tracker,
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
        "message_header": "Guard {server}",
        "message_text": "{user} {title} {quality} {client} {device} {reasons} {seconds}",
    })

    service.check_once()

    assert messages[0][1] == "Guard Blue"
    assert messages[0][2] == "roy Big Movie 2160p Emby Web MacBook VideoCodecNotSupported 0"


def test_service_message_template_uses_stop_delay_only_when_rule_can_stop():
    storage = _Storage()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([{
            "session_id": "session-template-stop",
            "title": "Big Movie",
            "user": "roy",
            "client": "Emby Web",
            "device": "MacBook",
            "video_height": 2160,
            "video_mode": "transcodifica",
            "audio_mode": "diretta",
        }], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append((session_id, header, text, timeout_ms)) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn_then_stop",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
        "correction_window_seconds": 45,
        "message_text": "Stop tra {seconds}s",
    })

    service.check_once()

    assert messages[0][2] == "Stop tra 45s"


def test_service_can_send_confirmation_message_without_timeout():
    storage = _Storage()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([{
            "session_id": "session-confirm",
            "title": "Big Movie",
            "video_height": 2160,
            "video_mode": "transcodifica",
            "audio_mode": "diretta",
        }], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append((session_id, timeout_ms)) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
    )
    service.save_settings({
        "enabled": True,
        "mode": "warn",
        "server_ids": ["server-a"],
        "grace_seconds": 0,
        "message_display_mode": "confirmation",
        "warning_timeout_ms": 90000,
    })

    service.check_once()

    assert messages == [("session-confirm", None)]


def test_service_maps_legacy_pause_mode_to_stop():
    storage = _Storage()
    tracker = _Tracker()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([{
            "session_id": "session-pause",
            "title": "Big Movie",
            "video_height": 2160,
            "video_mode": "transcodifica",
            "audio_mode": "diretta",
        }], None),
        send_message=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected message")),
        pause_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected pause")),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        operation_tracker_provider=lambda: tracker,
    )
    service.save_settings({"enabled": True, "mode": "pause", "server_ids": ["server-a"], "grace_seconds": 0})

    result = service.check_once()

    assert result["stopped"] == 1
    assert result["paused"] == 0
    assert stops == ["session-pause"]
    assert tracker.finished[-1][1] == "Sessione fermata da Transcode Guard"


def test_service_does_not_act_when_only_audio_is_transcoded():
    storage = _Storage()
    tracker = _Tracker()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([{
            "session_id": "session-2",
            "title": "Audio Only",
            "video_height": 2160,
            "video_mode": "diretta",
            "audio_mode": "transcodifica",
            "play_method": "Transcode",
        }], None),
        send_message=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected message")),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        operation_tracker_provider=lambda: tracker,
    )
    service.save_settings({"enabled": True, "mode": "stop", "server_ids": ["server-a"]})

    result = service.check_once()

    assert result["checked"] == 1
    assert result["violations"] == 0
    assert tracker.started == []


def test_emby_session_message_and_stop_use_expected_api_paths(monkeypatch):
    from emby_runtime import api_clients_emby

    calls = []

    def fake_call(server, path, method="GET", params=None, json_payload=None):
        calls.append((server, path, method, params, json_payload))
        return True, {}

    monkeypatch.setattr(api_clients_emby, "_call_emby_api", fake_call)

    server = {"id": "server-a"}
    assert api_clients_emby._send_emby_session_message(server, "session-1", "Titolo", "Test", 5000) == (True, {})
    assert api_clients_emby._send_emby_session_message(server, "session-confirm", "Titolo", "Test", None) == (True, {})
    assert api_clients_emby._stop_emby_playback_session(server, "session-1") == (True, {})
    assert api_clients_emby._pause_emby_playback_session(server, "session-1") == (True, {})

    assert calls[0] == (
        server,
        "Sessions/session-1/Message",
        "POST",
        {"Header": "Titolo", "Text": "Test", "TimeoutMs": 5000},
        None,
    )
    assert calls[1] == (
        server,
        "Sessions/session-confirm/Message",
        "POST",
        {"Header": "Titolo", "Text": "Test"},
        None,
    )
    assert calls[2] == (
        server,
        "Sessions/session-1/Playing/Stop",
        "POST",
        None,
        None,
    )
    assert calls[3] == (
        server,
        "Sessions/session-1/Playing/Pause",
        "POST",
        None,
        None,
    )


def test_active_sessions_expose_structured_video_and_audio_fields(monkeypatch):
    from emby_runtime import api_clients_emby

    def fake_call(_server, _path, method="GET", params=None, json_payload=None):
        return True, [{
            "Id": "session-1",
            "PlaySessionId": "play-1",
            "UserName": "roy",
            "Client": "Emby Web",
            "PlayState": {
                "PositionTicks": 1,
                "PlayMethod": "Transcode",
                "IsPaused": False,
                "AudioStreamIndex": 3,
                "SubtitleStreamIndex": 5,
            },
            "TranscodingInfo": {
                "IsVideoDirect": False,
                "IsAudioDirect": True,
                "MediaSourceId": "source-transcode",
            },
            "NowPlayingItem": {
                "Id": "item-1",
                "MediaSourceId": "source-item",
                "Name": "Big Movie",
                "Type": "Movie",
                "RunTimeTicks": 100,
                "MediaStreams": [
                    {"Type": "Video", "Width": 3840, "Height": 2160, "Codec": "hevc"},
                    {"Type": "Audio", "Codec": "eac3", "DisplayTitle": "Italian EAC3 5.1", "IsDefault": True},
                ],
            },
        }]

    monkeypatch.setattr(api_clients_emby, "_call_emby_api", fake_call)

    sessions, error = api_clients_emby._fetch_emby_active_sessions({"id": "server-a"})

    assert error is None
    assert sessions[0]["item_id"] == "item-1"
    assert sessions[0]["video_height"] == 2160
    assert sessions[0]["video_width"] == 3840
    assert sessions[0]["video_codec"] == "hevc"
    assert sessions[0]["audio_codec"] == "eac3"
    assert sessions[0]["play_session_id"] == "play-1"
    assert sessions[0]["media_source_id"] == "source-item"
    assert sessions[0]["audio_stream_index"] == 3
    assert sessions[0]["subtitle_stream_index"] == 5


def test_service_records_every_stream_with_technical_violation_tags():
    storage = _Storage()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    streams = [
        {
            "session_id": "direct-1",
            "item_id": "movie-1",
            "title": "Direct Movie",
            "user": "roy",
            "client": "Infuse",
            "device": "Apple TV",
            "device_id": "device-direct",
            "media_type": "Movie",
            "video_height": 2160,
            "video_width": 3840,
            "video_mode": "diretta",
            "audio_mode": "diretta",
            "play_method": "DirectPlay",
            "video_codec": "hevc",
            "audio_codec": "eac3",
        },
        {
            "session_id": "audio-1",
            "item_id": "movie-2",
            "title": "Audio Transcode",
            "user": "roy",
            "client": "Emby Web",
            "device": "Mac",
            "device_id": "device-audio",
            "media_type": "Movie",
            "video_height": 1080,
            "video_mode": "diretta",
            "audio_mode": "transcodifica",
            "play_method": "Transcode",
            "transcode_reasons": ["AudioCodecNotSupported"],
        },
    ]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (streams, None),
        send_message=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected message")),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
    )
    service.save_settings({
        "enabled": True,
        "stream_history_retention_days": 0,
        "rules": [{
            "id": "video-rule",
            "name": "Solo video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 2160,
            "mode": "monitor",
        }],
    })

    service.check_once()

    history = service.get_status()["stream_history"]
    by_session = {row["session_id"]: row for row in history["rows"]}
    assert history["total"] == 2
    assert by_session["direct-1"]["tags"] == ["corretta", "direct play"]
    assert by_session["direct-1"]["violations_committed"] == []
    assert by_session["direct-1"]["video_codec"] == "hevc"
    assert by_session["audio-1"]["tags"] == ["transcode audio", "browser", "non monitorata"]
    assert by_session["audio-1"]["violations_committed"] == ["audio_transcode", "browser_playback"]
    assert by_session["audio-1"]["transcode_reasons"] == ["AudioCodecNotSupported"]


def test_service_stream_history_retention_keeps_forever_when_zero_and_prunes_when_saved_positive():
    storage = _Storage()
    storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, [{
        "id": "old-row",
        "playback_key": "server-a|roy|device|item:old",
        "session_id": "old-session",
        "title": "Old Movie",
        "started_at": "2000-01-01T00:00:00+00:00",
        "updated_at": "2000-01-01T00:00:00+00:00",
        "tags": ["corretta"],
    }])
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([], None),
    )
    service.save_settings({
        "enabled": True,
        "stream_history_retention_days": 0,
        "rules": [{"id": "disabled", "enabled": False, "server_ids": []}],
    })

    service.check_once()
    assert service.get_status()["stream_history"]["total"] == 1

    service.save_settings({
        "enabled": True,
        "stream_history_retention_days": 1,
        "rules": [{"id": "disabled", "enabled": False, "server_ids": []}],
    })
    service.check_once()

    assert service.get_status()["stream_history"]["total"] == 0


def test_service_marks_relapse_on_same_playback_after_resolution():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Blue", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "movie-1",
        "title": "Big Movie",
        "user": "roy",
        "client": "Emby Web",
        "device": "Mac",
        "device_id": "device-1",
        "video_height": 2160,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([current_stream], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 2160,
            "mode": "warn",
            "grace_seconds": 0,
            "max_warnings": 1,
        }],
    })

    service.check_once()
    clock.advance(1)
    current_stream["video_mode"] = "diretta"
    service.check_once()
    clock.advance(1)
    current_stream["video_mode"] = "transcodifica"
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-1"]
    assert len(events) == 1
    assert [item["action"] for item in events[0]["actions"]] == ["warn", "resolved", "relapse", "warn"]
    assert events[0]["action_label"] == "avviso - risolto - ricaduta - avviso"
    stream_row = service.get_status()["stream_history"]["rows"][0]
    assert "ricaduta" in stream_row["tags"]
    assert stream_row["violation_count"] == 2


def test_service_starts_new_event_for_new_session_after_resolution():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 872,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    messages = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([current_stream], None),
        send_message=lambda _server, session_id, header, text, timeout_ms: messages.append(session_id) or (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 720,
            "mode": "warn",
            "grace_seconds": 0,
            "max_warnings": 1,
        }],
    })

    service.check_once()
    clock.advance(1)
    current_stream["video_mode"] = "diretta"
    service.check_once()
    clock.advance(1)
    current_stream["session_id"] = "session-2"
    current_stream["video_mode"] = "transcodifica"
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-2"]
    assert len(events) == 2
    assert [item["action"] for item in events[0]["actions"]] == ["warn"]
    assert [item["action"] for item in events[1]["actions"]] == ["warn", "resolved"]


def test_service_playback_stopped_event_closes_violation_and_next_session_warns_again_immediately():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_streams = [{
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }]
    messages = []
    stops = []
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda _server, session_id, *_args: messages.append(session_id) or (True, {}),
        stop_session=lambda _server, session_id: stops.append(session_id) or (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn_then_stop",
            "correction_window_seconds": 60,
            "max_warnings": 1,
        }],
    })

    service.check_once()
    service.record_playback_event("server-a", {
        "MessageType": "PlaybackStopped",
        "Data": {"SessionId": "session-1", "EventName": "Stopped"},
    })
    current_streams[:] = [dict(current_streams[0], session_id="session-2")]
    service.check_once()

    events = service.get_status()["recent_events"]
    assert messages == ["session-1", "session-2"]
    assert stops == []
    assert len(events) == 2
    assert [item["action"] for item in events[0]["actions"]] == ["warn"]
    assert [item["action"] for item in events[1]["actions"]] == ["warn", "exit"]


def test_service_persists_playback_events_even_without_matching_stream_row():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)

    result = service.record_playback_event("server-a", {
        "MessageType": "PlaybackProgress",
        "Data": {
            "SessionId": "session-1",
            "EventName": "AudioTrackChange",
            "PlaySessionId": "play-1",
            "MediaSourceId": "source-1",
            "AudioStreamIndex": 2,
        },
    })

    rows = storage.values[TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY]
    status_events = service.get_status()["playback_events"]["rows"]
    assert result == {"ok": True, "action": "audio_change", "matched": 0}
    assert len(rows) == 1
    assert status_events[0]["action"] == "audio_change"
    assert rows[0]["server_id"] == "server-a"
    assert rows[0]["session_id"] == "session-1"
    assert rows[0]["action"] == "audio_change"
    assert rows[0]["play_session_id"] == "play-1"
    assert rows[0]["media_source_id"] == "source-1"
    assert rows[0]["audio_stream_index"] == 2


def test_service_records_quality_audio_and_subtitle_changes_without_marking_exit():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([current_stream], None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    for event_name in ("QualityChange", "AudioTrackChange", "SubtitleTrackChange"):
        service.record_playback_event("server-a", {
            "MessageType": "PlaybackProgress",
            "Data": {"SessionId": "session-1", "EventName": event_name},
        })
    current_stream["video_mode"] = "diretta"
    service.check_once()

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [item["action"] for item in events[0]["actions"]] == [
        "warn",
        "quality_change",
        "audio_change",
        "subtitle_change",
        "resolved",
    ]
    assert events[0]["action_label"] == "avviso - cambio qualità - cambio audio - cambio sottotitoli - risolto"


def test_service_records_observed_stream_changes_only_in_stream_history():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "media_source_id": "source-2160",
        "audio_stream_index": 1,
        "subtitle_stream_index": None,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([dict(current_stream)], None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    current_stream["media_source_id"] = "source-1080"
    current_stream["video_height"] = 872
    current_stream["audio_stream_index"] = 2
    current_stream["subtitle_stream_index"] = 3
    clock.advance(1)
    service.check_once()

    status = service.get_status()
    playback_actions = [item["action"] for item in status["playback_events"]["rows"]]
    stream_actions = [item["action"] for item in status["stream_history"]["rows"][0]["actions"]]
    stream_sources = [item.get("source") for item in status["stream_history"]["rows"][0]["actions"][-3:]]
    assert playback_actions == []
    assert stream_actions[-3:] == ["quality_change", "audio_change", "subtitle_change"]
    assert stream_sources == ["observed", "observed", "observed"]


def test_service_does_not_write_observed_audio_subtitle_to_player_events_from_initial_hydration():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([dict(current_stream)], None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    current_stream["audio_stream_index"] = 1
    current_stream["subtitle_stream_index"] = None
    clock.advance(1)
    service.check_once()
    clock.advance(1)
    service.check_once()

    assert service.get_status()["playback_events"]["rows"] == []


def test_service_keeps_observed_quality_change_out_of_recent_intervention_and_player_events():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    current_stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "media_source_id": "source-a",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: ([dict(current_stream)], None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    current_stream["media_source_id"] = "source-b"
    current_stream["video_height"] = 1604
    clock.advance(1)
    service.check_once()

    status = service.get_status()
    event_actions = [item["action"] for item in status["recent_events"][0]["actions"]]
    stream_actions = [item["action"] for item in status["stream_history"]["rows"][0]["actions"]]
    assert event_actions == ["warn"]
    assert stream_actions[-1] == "quality_change"
    assert status["stream_history"]["rows"][0]["actions"][-1]["source"] == "observed"
    assert status["playback_events"]["rows"] == []


def test_service_records_real_quality_change_from_session_playstate_event():
    storage = _Storage()
    clock = _Clock()
    service = TranscodeGuardService(storage_provider=lambda: storage, now=clock)

    result = service.record_playback_event("server-a", {
        "MessageType": "Sessions",
        "Data": [{
            "Id": "session-1",
            "PlayState": {
                "EventName": "QualityChange",
                "PlaySessionId": "play-1",
                "MediaSourceId": "source-1080",
                "AudioStreamIndex": 2,
                "SubtitleStreamIndex": 3,
            },
        }],
    })

    rows = service.get_status()["playback_events"]["rows"]
    assert result == {"ok": True, "action": "quality_change", "matched": 0}
    assert rows[0]["action"] == "quality_change"
    assert rows[0]["event_name"] == "QualityChange"
    assert rows[0]["message_type"] == "Sessions"
    assert rows[0]["media_source_id"] == "source-1080"


def test_service_marks_resolved_intervention_as_exit_when_real_stop_arrives():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    current_streams = [stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    current_streams[:] = [dict(stream, video_mode="diretta")]
    clock.advance(1)
    service.check_once()

    service.record_event_bridge_event({
        "schema": "octohubs.emby.event.v1",
        "source": "OctoHubs.EventBridge",
        "server": {"id": "server-a", "name": "Green"},
        "event": {"type": "playback.stopped", "name": "Stopped"},
        "session": {"id": "session-1", "playSessionId": "play-1"},
        "media": {"mediaSourceId": "source-1746"},
    })

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [item["action"] for item in events[0]["actions"]] == ["warn", "resolved", "exit"]


def test_service_deduplicates_repeated_real_player_events():
    storage = _Storage()
    clock = _Clock()
    service = TranscodeGuardService(storage_provider=lambda: storage, now=clock)
    event = {
        "MessageType": "PlaybackProgress",
        "Data": {
            "SessionId": "session-1",
            "EventName": "AudioTrackChange",
            "AudioStreamIndex": 2,
        },
    }

    service.record_playback_event("server-a", event)
    clock.advance(1)
    service.record_playback_event("server-a", event)

    rows = service.get_status()["playback_events"]["rows"]
    assert len(rows) == 1
    assert rows[0]["action"] == "audio_change"


def test_service_filters_legacy_inferred_events_from_player_event_payload():
    storage = _Storage()
    storage.values[TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY] = [
        {
            "id": "old-inferred",
            "server_id": "server-a",
            "session_id": "session-1",
            "event_name": "InferredAudioChange",
            "message_type": "Inferred",
            "action": "audio_change",
            "outcome": "cambio audio",
            "at": "2026-07-23T10:00:00+00:00",
        },
        {
            "id": "real-event",
            "server_id": "server-a",
            "session_id": "session-1",
            "event_name": "AudioTrackChange",
            "message_type": "PlaybackProgress",
            "action": "audio_change",
            "outcome": "cambio audio",
            "source": "player",
            "at": "2026-07-23T10:01:00+00:00",
        },
    ]
    service = TranscodeGuardService(storage_provider=lambda: storage)

    rows = service.get_status()["playback_events"]["rows"]

    assert [row["id"] for row in rows] == ["real-event"]


def test_service_exposes_real_plugin_events_in_player_event_log():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)

    result = service.record_event_bridge_event({
        "schema": "octohubs.emby.event.v1",
        "source": "OctoHubs.EventBridge",
        "server": {"id": "server-a", "name": "Green"},
        "event": {"type": "playback.progress", "name": "QualityChange"},
        "session": {"id": "session-1", "playSessionId": "play-1"},
        "media": {
            "mediaSourceId": "source-1080",
            "audioStreamIndex": 2,
            "subtitleStreamIndex": 3,
        },
    })

    rows = service.get_status()["playback_events"]["rows"]

    assert result == {"ok": True, "action": "quality_change", "matched": 0}
    assert len(rows) == 1
    assert rows[0]["source"] == "plugin"
    assert rows[0]["server_id"] == "server-a"
    assert rows[0]["session_id"] == "session-1"
    assert rows[0]["action"] == "quality_change"
    assert rows[0]["event_name"] == "QualityChange"
    assert rows[0]["media_source_id"] == "source-1080"
    assert rows[0]["audio_stream_index"] == 2
    assert rows[0]["subtitle_stream_index"] == 3


def test_service_exposes_event_bridge_plugin_diagnostics_in_player_event_log():
    storage = _Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)

    result = service.record_event_bridge_event({
        "schema": "octohubs.emby.event.v1",
        "source": "OctoHubs.EventBridge",
        "server": {"id": "server-a", "name": "Green"},
        "event": {"type": "plugin.start", "name": "PluginStart"},
        "plugin": {"version": "0.1.1", "enabled": True},
    })

    rows = service.get_status()["playback_events"]["rows"]

    assert result == {"ok": True, "action": "plugin_event", "recorded": True, "event_type": "plugin.start"}
    assert len(rows) == 1
    assert rows[0]["source"] == "plugin"
    assert rows[0]["server_id"] == "server-a"
    assert rows[0]["session_id"] == "server-a:plugin"
    assert rows[0]["action"] == "plugin_event"
    assert rows[0]["outcome"] == "evento plugin"
    assert rows[0]["event_name"] == "PluginStart"


def test_service_playback_stopped_event_does_not_append_exit_after_guard_stop():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    streams = [{
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (streams, None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (True, {}),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "stop",
        }],
    })

    service.check_once()
    service.record_playback_event("server-a", {
        "MessageType": "PlaybackStopped",
        "Data": {"SessionId": "session-1", "EventName": "Stopped"},
    })

    events = service.get_status()["recent_events"]
    assert len(events) == 1
    assert [item["action"] for item in events[0]["actions"]] == ["stop"]


def test_service_marks_missing_stream_as_exit_after_four_second_fallback_settle():
    storage = _Storage()
    clock = _Clock()
    server = {"id": "server-a", "name": "Green", "enabled": True}
    stream = {
        "session_id": "session-1",
        "item_id": "episode-1",
        "title": "Star City S1:E6",
        "user": "RedPrimrose",
        "client": "Emby Web",
        "device": "Chrome",
        "device_id": "device-1",
        "video_height": 1746,
        "video_mode": "transcodifica",
        "audio_mode": "diretta",
    }
    current_streams = [stream]
    service = TranscodeGuardService(
        storage_provider=lambda: storage,
        load_config=lambda: ({"EMBY": {"SERVERS": [server]}}, True),
        fetch_sessions=lambda _server: (list(current_streams), None),
        send_message=lambda *_args: (True, {}),
        stop_session=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected stop")),
        now=clock,
    )
    service.save_settings({
        "enabled": True,
        "rules": [{
            "id": "video-rule",
            "name": "Transcode video",
            "enabled": True,
            "server_ids": ["server-a"],
            "video_state": "transcode",
            "audio_state": "any",
            "remux_state": "any",
            "min_source_height": 1440,
            "mode": "warn",
            "max_warnings": 1,
        }],
    })

    service.check_once()
    current_streams.clear()
    service.check_once()
    clock.advance(3)
    service.check_once()
    assert [item["action"] for item in service.get_status()["recent_events"][0]["actions"]] == ["warn"]

    clock.advance(1)
    service.check_once()

    assert [item["action"] for item in service.get_status()["recent_events"][0]["actions"]] == ["warn", "exit"]


def test_service_builds_user_stream_stats_from_shared_stream_history():
    storage = _Storage()
    storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, [
        {
            "id": "row-stop",
            "playback_key": "green|roy|mac|item:movie-1",
            "session_id": "session-stop",
            "title": "Dragon Trainer",
            "user": "Roy",
            "client": "Emby for macOS",
            "device": "MacBook",
            "server_id": "green",
            "server_name": "Green",
            "quality": "2160p",
            "source_height": 2160,
            "started_at": "2026-07-22T10:00:00+00:00",
            "updated_at": "2026-07-22T10:03:00+00:00",
            "duration_seconds": 180,
            "tags": ["transcode video", "violazione", "avviso", "stop"],
            "violations_committed": ["video_transcode"],
            "actions": [
                {"action": "warn", "outcome": "Avviso inviato", "success": True, "at": "2026-07-22T10:01:00+00:00"},
                {"action": "stop", "outcome": "Sessione fermata", "success": True, "at": "2026-07-22T10:03:00+00:00"},
            ],
        },
        {
            "id": "row-resolved",
            "playback_key": "green|roy|mac|item:movie-2",
            "session_id": "session-resolved",
            "title": "Dune",
            "user": "Roy",
            "client": "Emby for macOS",
            "device": "MacBook",
            "server_id": "green",
            "server_name": "Green",
            "quality": "2160p",
            "source_height": 2160,
            "started_at": "2026-07-22T09:00:00+00:00",
            "updated_at": "2026-07-22T09:02:00+00:00",
            "tags": ["transcode video", "violazione", "avviso", "risolto"],
            "violations_committed": ["video_transcode"],
            "actions": [
                {"action": "warn", "outcome": "Avviso inviato", "success": True, "at": "2026-07-22T09:01:00+00:00"},
                {"action": "resolved", "outcome": "Risolta", "success": True, "at": "2026-07-22T09:02:00+00:00"},
            ],
        },
        {
            "id": "row-correct",
            "playback_key": "blue|anna|tv|item:movie-3",
            "session_id": "session-correct",
            "title": "Arrival",
            "user": "Anna",
            "client": "Infuse",
            "device": "Apple TV",
            "server_id": "blue",
            "server_name": "Blue",
            "quality": "1080p",
            "source_height": 1080,
            "started_at": "2026-07-22T08:00:00+00:00",
            "updated_at": "2026-07-22T08:10:00+00:00",
            "tags": ["corretta", "direct play"],
            "violations_committed": [],
            "actions": [],
        },
        {
            "id": "row-browser",
            "playback_key": "blue|anna|browser|item:movie-4",
            "session_id": "session-browser",
            "title": "Interstellar",
            "user": "Anna",
            "client": "Chrome",
            "device": "Laptop",
            "server_id": "blue",
            "server_name": "Blue",
            "quality": "1080p",
            "source_height": 1080,
            "started_at": "2026-07-21T08:00:00+00:00",
            "updated_at": "2026-07-21T08:05:00+00:00",
            "tags": ["browser", "non monitorata"],
            "violations_committed": ["browser_playback"],
            "actions": [],
        },
    ])
    service = TranscodeGuardService(storage_provider=lambda: storage)

    stats = service.get_user_stats({"period": "all", "sort": "issues_desc"})

    assert stats["ok"] is True
    assert stats["summary"]["users"] == 2
    assert stats["summary"]["streams"] == 4
    assert stats["summary"]["correct"] == 1
    assert stats["summary"]["issue_streams"] == 3
    assert stats["summary"]["warnings"] == 2
    assert stats["summary"]["stops"] == 1
    assert stats["summary"]["resolved"] == 1
    assert stats["summary"]["problem_rate"] == 75.0
    assert [user["user"] for user in stats["users"]] == ["Roy", "Anna"]
    assert stats["users"][0]["streams"] == 2
    assert stats["users"][0]["issue_streams"] == 2
    assert stats["users"][0]["stops"] == 1
    assert stats["users"][0]["trend"][0]["status"] == "stop"
    assert stats["users"][1]["correct"] == 1
    assert stats["facets"]["servers"] == [
        {"id": "blue", "name": "Blue", "count": 2},
        {"id": "green", "name": "Green", "count": 2},
    ]
    assert stats["history"][0]["title"] == "Dragon Trainer"
    assert stats["history"][0]["outcome"] == "stop"


def test_service_user_stream_stats_support_filters_and_issue_only_history():
    storage = _Storage()
    storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, [
        {
            "id": "row-green",
            "title": "Problem",
            "user": "Roy",
            "client": "Emby Web",
            "server_id": "green",
            "server_name": "Green",
            "started_at": "2026-07-22T10:00:00+00:00",
            "updated_at": "2026-07-22T10:00:00+00:00",
            "tags": ["transcode video", "violazione"],
            "violations_committed": ["video_transcode"],
        },
        {
            "id": "row-blue",
            "title": "Correct",
            "user": "Roy",
            "client": "Infuse",
            "server_id": "blue",
            "server_name": "Blue",
            "started_at": "2026-07-22T09:00:00+00:00",
            "updated_at": "2026-07-22T09:00:00+00:00",
            "tags": ["corretta", "direct play"],
            "violations_committed": [],
        },
    ])
    service = TranscodeGuardService(storage_provider=lambda: storage)

    stats = service.get_user_stats({"period": "all", "server_id": "green", "issues_only": "true", "limit": "10"})

    assert stats["summary"]["streams"] == 1
    assert stats["summary"]["issue_streams"] == 1
    assert stats["users"][0]["user"] == "Roy"
    assert len(stats["history"]) == 1
    assert stats["history"][0]["server_id"] == "green"


def test_service_user_stream_stats_does_not_count_plain_exit_as_issue():
    storage = _Storage()
    storage.set_key_value(TRANSCODE_GUARD_STREAM_LOG_KEY, [
        {
            "id": "row-exit",
            "title": "Correct Exit",
            "user": "Roy",
            "client": "Infuse",
            "server_id": "green",
            "server_name": "Green",
            "started_at": "2026-07-22T10:00:00+00:00",
            "updated_at": "2026-07-22T10:05:00+00:00",
            "tags": ["corretta", "direct play"],
            "violations_committed": [],
            "actions": [
                {"action": "exit", "outcome": "Uscita riproduzione", "success": True, "at": "2026-07-22T10:05:00+00:00"},
            ],
        },
        {
            "id": "row-warn-exit",
            "title": "Warn Then Exit",
            "user": "Roy",
            "client": "Emby Web",
            "server_id": "green",
            "server_name": "Green",
            "started_at": "2026-07-22T09:30:00+00:00",
            "updated_at": "2026-07-22T09:35:00+00:00",
            "tags": ["transcode video", "violazione", "avviso", "uscito"],
            "violations_committed": ["video_transcode"],
            "actions": [
                {"action": "warn", "outcome": "Avviso inviato", "success": True, "at": "2026-07-22T09:31:00+00:00"},
                {"action": "exit", "outcome": "Uscita riproduzione", "success": True, "at": "2026-07-22T09:35:00+00:00"},
            ],
        },
        {
            "id": "row-stop",
            "title": "Guard Stop",
            "user": "Roy",
            "client": "Emby Web",
            "server_id": "green",
            "server_name": "Green",
            "started_at": "2026-07-22T09:00:00+00:00",
            "updated_at": "2026-07-22T09:03:00+00:00",
            "tags": ["stop"],
            "violations_committed": [],
            "actions": [
                {"action": "stop", "outcome": "Sessione fermata", "success": True, "at": "2026-07-22T09:03:00+00:00"},
            ],
        },
    ])
    service = TranscodeGuardService(storage_provider=lambda: storage)

    stats = service.get_user_stats({"period": "all", "issues_only": "false"})
    issue_stats = service.get_user_stats({"period": "all", "issues_only": "true"})

    assert stats["summary"]["streams"] == 3
    assert stats["summary"]["correct"] == 1
    assert stats["summary"]["issue_streams"] == 2
    assert stats["summary"]["exits"] == 2
    assert stats["summary"]["stops"] == 1
    assert stats["summary"]["problem_rate"] == 66.7
    assert stats["history"][0]["id"] == "row-exit"
    assert stats["history"][0]["outcome"] == "correct"
    assert stats["history"][1]["id"] == "row-warn-exit"
    assert stats["history"][1]["outcome"] == "warning"
    assert issue_stats["summary"]["streams"] == 2
    assert [row["id"] for row in issue_stats["history"]] == ["row-warn-exit", "row-stop"]
