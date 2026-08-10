"""Event Bridge Emby plugin HTTP client."""

from __future__ import annotations


def test_push_event_bridge_settings_to_plugin_posts_emby_plugin_configuration(monkeypatch):
    from emby_runtime import event_bridge_plugin_client as client

    calls = []

    def fake_call(server, path, method="GET", params=None, json_payload=None):
        calls.append((server, path, method, json_payload))
        return True, {"Ok": True, "Applied": True}

    monkeypatch.setattr(client, "_call_emby_api", fake_call)

    ok, error, response = client.push_event_bridge_settings_to_plugin(
        {"id": "green", "url": "http://emby-green:8096", "api_key": "secret"},
        "green",
        {
            "WEBSOCKET_ENABLED": False,
            "HTTP_FALLBACK_ENABLED": True,
            "PLAYBACK_EVENT_NAMES": ["Pause", "Unpause"],
        },
    )

    assert ok is True
    assert error == ""
    assert response == {"Ok": True, "Applied": True}
    server, path, method, payload = calls[0]
    assert server["id"] == "green"
    assert path == "OctoHubs/EventBridge/Configuration"
    assert method == "POST"
    assert payload["ServerId"] == "green"
    assert payload["UseWebSocket"] is False
    assert payload["UseHttpFallback"] is True
    assert payload["PlaybackEventNames"] == "Pause\nUnpause"


def test_push_event_bridge_settings_to_plugin_reports_plugin_errors(monkeypatch):
    from emby_runtime import event_bridge_plugin_client as client

    monkeypatch.setattr(
        client,
        "_call_emby_api",
        lambda *_args, **_kwargs: (True, {"Ok": False, "Applied": False, "Error": "SaveOptions failed"}),
    )

    ok, error, response = client.push_event_bridge_settings_to_plugin(
        {"id": "green", "url": "http://emby-green:8096", "api_key": "secret"},
        "green",
        {},
    )

    assert ok is False
    assert error == "SaveOptions failed"
    assert response == {"Ok": False, "Applied": False, "Error": "SaveOptions failed"}
