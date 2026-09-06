from emby_runtime.playback_events import normalize_emby_playback_event, normalize_emby_playback_events


def test_normalize_emby_playback_event_maps_track_and_stop_events():
    changed = normalize_emby_playback_event("green", {
        "MessageType": "PlaybackProgress",
        "Data": {
            "SessionId": "session-1",
            "EventName": "SubtitleTrackChange",
            "PlaySessionId": "play-1",
            "MediaSourceId": "source-1",
            "AudioStreamIndex": 2,
            "SubtitleStreamIndex": 4,
        },
    })

    stopped = normalize_emby_playback_event("green", {
        "MessageType": "PlaybackStopped",
        "Data": {"SessionId": "session-1"},
    })

    assert changed["action"] == "subtitle_change"
    assert changed["outcome"] == "cambio sottotitoli"
    assert changed["play_session_id"] == "play-1"
    assert changed["media_source_id"] == "source-1"
    assert changed["audio_stream_index"] == 2
    assert changed["subtitle_stream_index"] == 4
    assert stopped["action"] == "exit"
    assert stopped["outcome"] == "uscito"


def test_normalize_emby_playback_event_ignores_events_without_session_identity():
    assert normalize_emby_playback_event("green", {
        "MessageType": "PlaybackProgress",
        "Data": {"EventName": "QualityChange"},
    }) is None


def test_normalize_emby_playback_events_reads_session_snapshots_with_player_event_names():
    events = normalize_emby_playback_events("green", {
        "MessageType": "Sessions",
        "Data": [
            {"Id": "session-1", "PlayState": {"EventName": "QualityChange", "MediaSourceId": "source-1080"}},
            {"Id": "session-2", "PlayState": {"EventName": "AudioTrackChange", "AudioStreamIndex": 2}},
            {"Id": "session-3", "PlayState": {}},
        ],
    })

    assert [event["action"] for event in events] == ["quality_change", "audio_change"]
    assert events[0]["media_source_id"] == "source-1080"
    assert events[1]["audio_stream_index"] == 2


def test_normalize_emby_playback_events_covers_known_player_actions():
    names = {
        "TimeUpdate": "time_update",
        "VolumeChange": "volume_change",
        "RepeatModeChange": "repeat_mode_change",
        "PlaylistItemMove": "playlist_item_move",
        "PlaylistItemRemove": "playlist_item_remove",
        "PlaylistItemAdd": "playlist_item_add",
        "StateChange": "state_change",
        "SubtitleOffsetChange": "subtitle_offset_change",
        "PlaybackRateChange": "playback_rate_change",
        "ShuffleChange": "shuffle_change",
        "SleepTimerChange": "sleep_timer_change",
    }

    for event_name, action in names.items():
        event = normalize_emby_playback_event("green", {
            "MessageType": "PlaybackProgress",
            "Data": {"SessionId": "session-1", "EventName": event_name},
        })
        assert event["action"] == action


def test_normalize_emby_playback_event_keeps_unknown_real_player_events():
    event = normalize_emby_playback_event("green", {
        "MessageType": "GeneralCommand",
        "Data": {
            "SessionId": "session-1",
            "EventName": "AudioStreamChange",
        },
    })

    assert event["action"] == "player_event"
    assert event["outcome"] == "evento player"
    assert event["event_name"] == "AudioStreamChange"


def test_normalize_emby_playback_event_accepts_octohubs_plugin_payload():
    event = normalize_emby_playback_event("green", {
        "source": "octohubs_event_bridge",
        "eventBridgeTransport": "websocket",
        "messageType": "PlaybackProgress",
        "eventName": "QualityChange",
        "sessionId": "session-1",
        "playSessionId": "play-1",
        "mediaSourceId": "source-2160",
        "audioStreamIndex": 1,
        "subtitleStreamIndex": 3,
    })

    assert event["source"] == "plugin"
    assert event["transport"] == "websocket"
    assert event["action"] == "quality_change"
    assert event["outcome"] == "cambio qualità"
    assert event["event_name"] == "QualityChange"
    assert event["session_id"] == "session-1"
    assert event["play_session_id"] == "play-1"
    assert event["media_source_id"] == "source-2160"
    assert event["audio_stream_index"] == 1
    assert event["subtitle_stream_index"] == 3


def test_normalize_emby_playback_event_rejects_removed_octohub_plugin_source_alias():
    event = normalize_emby_playback_event("green", {
        "source": "OctoHub.EventBridge",
        "messageType": "PlaybackProgress",
        "eventName": "QualityChange",
        "sessionId": "session-1",
    })

    assert event["source"] == "player"
