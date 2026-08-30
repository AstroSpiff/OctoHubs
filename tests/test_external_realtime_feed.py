"""Tests for the external realtime invalidation journal."""

from realtime.external_change_feed import (
    EXTERNAL_CHANGE_RETENTION,
    publish_external_change,
    read_external_changes,
    reset_external_change_feed_for_tests,
)


def setup_function():
    reset_external_change_feed_for_tests()


def test_external_realtime_feed_exposes_safe_topic_without_raw_event_data():
    publish_external_change(
        {
            "server_id": "green",
            "MessageType": "RefreshProgress",
            "Data": {"UserName": "private", "RefreshProgress": 42},
        }
    )

    payload = read_external_changes(after=0, limit=10)
    event = payload["events"][0]

    assert payload["next_cursor"] == 1
    assert payload["latest_cursor"] == 1
    assert payload["reset_required"] is False
    assert event["topic"] == "libraries.scan"
    assert event["server_id"] == "green"
    assert event["details"] == {}
    assert "private" not in event.values()


def test_external_realtime_feed_preserves_configuration_scope_only():
    publish_external_change(
        {
            "MessageType": "OctoHubsConfigurationUpdated",
            "Data": {"scope": "probe", "password": "must-not-leak"},
        }
    )

    event = read_external_changes(after=0, limit=1)["events"][0]

    assert event["topic"] == "configuration"
    assert event["details"] == {"scope": "probe"}


def test_external_realtime_feed_pages_from_a_cursor():
    for message_type in ("SessionsUpdate", "ConnectionClosed", "LibraryChanged"):
        publish_external_change({"MessageType": message_type})

    first_page = read_external_changes(after=0, limit=2)
    second_page = read_external_changes(after=first_page["next_cursor"], limit=2)

    assert [event["cursor"] for event in first_page["events"]] == [1, 2]
    assert first_page["has_more"] is True
    assert [event["cursor"] for event in second_page["events"]] == [3]
    assert second_page["has_more"] is False


def test_external_realtime_feed_marks_a_stale_cursor_for_snapshot_reset(monkeypatch):
    import realtime.external_change_feed as feed

    monkeypatch.setattr(feed, "EXTERNAL_CHANGE_RETENTION", 2)
    monkeypatch.setattr(feed, "_changes", feed.deque(maxlen=2))
    for message_type in ("SessionsUpdate", "ConnectionClosed", "LibraryChanged"):
        publish_external_change({"MessageType": message_type})

    payload = read_external_changes(after=0, limit=EXTERNAL_CHANGE_RETENTION)

    assert payload["reset_required"] is True
    assert [event["cursor"] for event in payload["events"]] == [2, 3]


def test_external_realtime_feed_marks_a_pre_restart_future_cursor_for_reset():
    publish_external_change({"MessageType": "LibraryChanged"})

    payload = read_external_changes(after=3, limit=10)

    assert payload["reset_required"] is True
    assert payload["latest_cursor"] == 1
    assert [event["cursor"] for event in payload["events"]] == [1]
