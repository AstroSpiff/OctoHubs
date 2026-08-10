"""Transcode Guard API routes."""

from __future__ import annotations

import json

import pytest

from emby_runtime.transcode_guard_routes import (
    api_transcode_guard_check_now,
    api_transcode_guard_events_cleanup,
    api_transcode_guard_plugin_event,
    api_transcode_guard_settings,
    api_transcode_guard_settings_save,
    api_transcode_guard_start,
    api_transcode_guard_status,
    api_transcode_guard_stop,
    api_transcode_guard_streams_cleanup,
    api_transcode_guard_user_stats,
    init_transcode_guard_routes,
)


class _Request:
    def __init__(self, payload=None, query_params=None, headers=None):
        self._payload = payload or {}
        self.query_params = query_params or {}
        self.headers = headers or {}

    async def json(self):
        return self._payload


class _Service:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.saved = None
        self.settings = {"enabled": False, "mode": "monitor"}
        self.cleaned_before = None
        self.cleaned_streams_before = None
        self.stats_filters = None
        self.plugin_event_payload = None
        self.plugin_event_payloads = []

    def load_settings(self):
        return self.settings

    def save_settings(self, payload):
        self.saved = payload
        self.settings = {
            "enabled": bool(payload.get("enabled")),
            "mode": payload.get("mode") or "monitor",
        }
        return self.settings

    def get_status(self):
        return {"ok": True, "running": self.started, "settings": self.load_settings()}

    def check_once(self):
        return {"checked": 1, "violations": 0, "warned": 0, "stopped": 0, "errors": []}

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True
        self.started = False
        return True

    def clear_events(self, before=None):
        self.cleaned_before = before
        return 3

    def clear_stream_history(self, before=None):
        self.cleaned_streams_before = before
        return 4

    def get_user_stats(self, filters=None):
        self.stats_filters = filters or {}
        return {
            "ok": True,
            "summary": {"users": 1, "streams": 2, "issue_streams": 1},
            "users": [{"user": "roy", "streams": 2, "issue_streams": 1}],
            "history": [],
            "facets": {"servers": [], "users": [], "clients": []},
        }

    def record_plugin_playback_event(self, payload):
        self.plugin_event_payload = payload
        self.plugin_event_payloads.append(payload)
        return {"ok": True, "action": "quality_change", "recorded": True}

    def record_event_bridge_event(self, payload):
        return self.record_plugin_playback_event(payload)


class _RejectingService(_Service):
    def save_settings(self, payload):
        self.saved = payload
        raise ValueError('Seleziona almeno un server per "Senza server" o disattiva la regola.')


@pytest.mark.anyio
async def test_transcode_guard_settings_status_and_manual_check_routes():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    settings = await api_transcode_guard_settings(_Request())
    saved_response = await api_transcode_guard_settings_save(_Request({"enabled": True, "mode": "warn_then_stop"}))
    status = await api_transcode_guard_status(_Request())
    check_response = await api_transcode_guard_check_now(_Request())

    saved = json.loads(saved_response.body.decode("utf-8"))
    checked = json.loads(check_response.body.decode("utf-8"))
    assert settings["ok"] is True
    assert settings["settings"]["mode"] == "monitor"
    assert saved["settings"]["mode"] == "warn_then_stop"
    assert status["ok"] is True
    assert checked["result"]["checked"] == 1


@pytest.mark.anyio
async def test_transcode_guard_start_and_stop_routes():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    start_response = await api_transcode_guard_start(_Request())
    stop_response = await api_transcode_guard_stop(_Request())

    started = json.loads(start_response.body.decode("utf-8"))
    stopped = json.loads(stop_response.body.decode("utf-8"))
    assert started["ok"] is True
    assert started["started"] is True
    assert stopped["ok"] is True
    assert stopped["stopped"] is True


@pytest.mark.anyio
async def test_saving_enabled_policy_starts_monitor_and_disabling_stops_it():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    await api_transcode_guard_settings_save(_Request({"enabled": True, "mode": "warn_then_stop"}))
    assert service.started is True
    assert service.stopped is False

    await api_transcode_guard_settings_save(_Request({"enabled": False, "mode": "warn_then_stop"}))
    assert service.stopped is True
    assert service.started is False


@pytest.mark.anyio
async def test_transcode_guard_settings_save_returns_validation_error():
    service = _RejectingService()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    response = await api_transcode_guard_settings_save(_Request({"enabled": True}))

    payload = json.loads(response.body.decode("utf-8"))
    assert response.status_code == 400
    assert payload["ok"] is False
    assert "Seleziona almeno un server" in payload["error"]
    assert service.started is False


@pytest.mark.anyio
async def test_transcode_guard_events_cleanup_route():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    response = await api_transcode_guard_events_cleanup(_Request({"before": "2026-07-21T10:00:00"}))

    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {"ok": True, "deleted": 3}
    assert service.cleaned_before == "2026-07-21T10:00:00"


@pytest.mark.anyio
async def test_transcode_guard_streams_cleanup_route():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    response = await api_transcode_guard_streams_cleanup(_Request({"before": "2026-07-21T10:00:00"}))

    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {"ok": True, "deleted": 4}
    assert service.cleaned_streams_before == "2026-07-21T10:00:00"


@pytest.mark.anyio
async def test_transcode_guard_user_stats_route_passes_filters():
    service = _Service()
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    response = await api_transcode_guard_user_stats(_Request(query_params={
        "period": "7d",
        "server_id": "green",
        "user": "roy",
        "client": "Emby Web",
        "issues_only": "true",
        "sort": "issues_desc",
        "limit": "50",
    }))

    assert response["ok"] is True
    assert response["summary"]["users"] == 1
    assert service.stats_filters == {
        "period": "7d",
        "server_id": "green",
        "user": "roy",
        "client": "Emby Web",
        "issues_only": "true",
        "sort": "issues_desc",
        "limit": "50",
    }


@pytest.mark.anyio
async def test_transcode_guard_plugin_event_route_uses_webhook_secret(monkeypatch):
    service = _Service()
    monkeypatch.setenv("WEBHOOK_SECRET", "bridge-secret")
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    response = await api_transcode_guard_plugin_event(_Request(
        {
            "serverId": "green",
            "eventName": "QualityChange",
            "sessionId": "session-1",
        },
        headers={"X-Webhook-Secret": "bridge-secret"},
    ))

    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["result"]["action"] == "quality_change"
    assert service.plugin_event_payload["eventName"] == "QualityChange"


@pytest.mark.anyio
async def test_transcode_guard_plugin_event_route_accepts_event_bridge_batches(monkeypatch):
    service = _Service()
    monkeypatch.setenv("WEBHOOK_SECRET", "bridge-secret")
    seen_server_ids = []

    def event_bridge_settings(server_id=None):
        seen_server_ids.append(server_id)
        return {
            "WEBSOCKET_ENABLED": True,
            "HTTP_FALLBACK_ENABLED": False,
            "PLAYBACK_EVENT_NAMES": ["QualityChange"],
        }

    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
        get_event_bridge_settings=event_bridge_settings,
    )

    response = await api_transcode_guard_plugin_event(_Request(
        {
            "schema": "octohubs.emby.event_batch.v1",
            "events": [
                {"serverId": "green", "eventName": "Pause", "sessionId": "session-1"},
                {"serverId": "green", "eventName": "Unpause", "sessionId": "session-1"},
            ],
        },
        headers={"X-Webhook-Secret": "bridge-secret"},
    ))

    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert [item["eventName"] for item in service.plugin_event_payloads] == ["Pause", "Unpause"]
    assert seen_server_ids == ["green"]
    assert payload["settings"]["useWebSocket"] is True
    assert payload["settings"]["useHttpFallback"] is False
    assert payload["settings"]["progressEventNames"] == "QualityChange"


@pytest.mark.anyio
async def test_transcode_guard_plugin_config_saved_response_echoes_reported_settings(monkeypatch):
    service = _Service()
    monkeypatch.setenv("WEBHOOK_SECRET", "bridge-secret")
    monkeypatch.setattr(
        "emby_runtime.transcode_guard_routes.apply_plugin_reported_settings",
        lambda _payload: True,
    )

    def old_event_bridge_settings(server_id=None):
        return {
            "WEBSOCKET_ENABLED": True,
            "HTTP_FALLBACK_ENABLED": True,
            "PLAYBACK_EVENT_NAMES": ["PlaybackStart"],
        }

    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
        get_event_bridge_settings=old_event_bridge_settings,
    )

    response = await api_transcode_guard_plugin_event(_Request(
        {
            "schema": "octohubs.emby.event.v1",
            "server": {"id": "green", "name": "Green"},
            "event": {"type": "plugin.config_saved", "name": "PluginConfigSaved"},
            "plugin": {
                "enabled": True,
                "useWebSocket": False,
                "useHttpFallback": False,
                "playbackEventNames": ["Pause", "Unpause"],
            },
        },
        headers={"X-Webhook-Secret": "bridge-secret"},
    ))

    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["settings"]["useWebSocket"] is False
    assert payload["settings"]["useHttpFallback"] is False
    assert payload["settings"]["progressEventNames"] == "Pause\nUnpause"


@pytest.mark.anyio
async def test_transcode_guard_plugin_event_route_rejects_bad_webhook_secret(monkeypatch):
    service = _Service()
    monkeypatch.setenv("WEBHOOK_SECRET", "bridge-secret")
    init_transcode_guard_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        get_service=lambda: service,
    )

    with pytest.raises(Exception) as raised:
        await api_transcode_guard_plugin_event(_Request(
            {"serverId": "green", "eventName": "QualityChange", "sessionId": "session-1"},
            headers={"X-Webhook-Secret": "wrong"},
        ))

    assert getattr(raised.value, "status_code", None) == 403
    assert service.plugin_event_payload is None
