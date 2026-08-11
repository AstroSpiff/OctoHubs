import json

import pytest


def test_event_bridge_merge_preserves_hidden_server_settings():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config
    from web.config_routes import _merged_event_bridge_config

    current = normalize_event_bridge_config(
        {
            "SERVERS": {
                "green": {"ENABLED": False, "RETRY_COUNT": 7},
                "purple": {"ENABLED": True, "RETRY_COUNT": 1},
            }
        }
    )
    submitted = {
        "purple": current["SERVERS"]["purple"] | {"RETRY_COUNT": 3},
    }

    merged = _merged_event_bridge_config(current, submitted)

    assert merged["SERVERS"]["green"]["ENABLED"] is False
    assert merged["SERVERS"]["green"]["RETRY_COUNT"] == 7
    assert merged["SERVERS"]["purple"]["RETRY_COUNT"] == 3


def test_event_bridge_server_settings_are_hidden_until_plugin_seen():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config
    from web.config_routes import _event_bridge_servers_for_view

    servers = [
        {"id": "green", "alias": "Green"},
        {"id": "purple", "alias": "Purple"},
        {"id": "blue", "alias": "Blue"},
        {"id": "orange", "alias": "Orange"},
    ]
    status = {
        "servers": [
            {"server_id": "purple", "connected": False, "received_count": 1},
            {"server_id": "blue", "connected": True, "received_count": 0},
            {"server_id": "orange", "connected": False, "received_count": 0, "plugin_settings": {"ENABLED": True}},
        ]
    }

    items = _event_bridge_servers_for_view(servers, normalize_event_bridge_config({}), status)
    by_id = {item["id"]: item for item in items}

    assert by_id["green"]["settings_editable"] is False
    assert by_id["purple"]["settings_editable"] is True
    assert by_id["blue"]["settings_editable"] is True
    assert by_id["orange"]["settings_editable"] is True


def test_system_status_items_use_english_codes_and_italian_labels():
    from web.config_routes import _system_item, _system_rollup_severity, _system_section

    item = _system_item(
        "bridge-green",
        "Green",
        "warning",
        "Config diversa",
        status_code="mismatch",
    )

    assert item["status_code"] == "mismatch"
    assert item["status_label"] == "Disallineato"
    assert item["severity"] == "warning"
    assert _system_rollup_severity([{"severity": "unknown"}]) == "unknown"
    assert _system_rollup_severity([{"severity": "unknown"}, {"severity": "ok"}]) == "ok"

    section = _system_section("event-bridge", "Event Bridge", [item])
    assert section["status_code"] == "warning"
    assert section["status_label"] == "Avviso"


def test_system_services_reuse_the_last_native_connection_check():
    from app_state import set_connection_check_state
    from web.config_routes import _system_services_section

    config = {
        "JELLYSEERR_URL": "http://jellyseerr:5055",
        "JELLYSEERR_API_KEY": "token",
        "DATABASE": {"ENABLED": True},
    }
    set_connection_check_state(
        {
            "jellyseerr": {
                "ok": True,
                "message": "Jellyseerr raggiungibile (HTTP 200)",
            }
        },
        "2026-08-11T11:30:45+00:00",
    )
    try:
        section = _system_services_section(config, check_services=False)
    finally:
        set_connection_check_state({}, None)

    jellyseerr = next(item for item in section["items"] if item["id"] == "service-jellyseerr")
    assert jellyseerr["status_code"] == "online"
    assert jellyseerr["summary"] == "Online"
    assert jellyseerr["detail"] == "Jellyseerr raggiungibile (HTTP 200)"
    assert section["checked_at"] == "2026-08-11 11:30:45 UTC"


def test_system_status_can_return_one_operational_section(monkeypatch):
    from web import config_routes

    monkeypatch.setattr(config_routes, "load_config", lambda: ({"DATABASE": {}}, True))

    payload = config_routes._build_system_status_snapshot(section_id="app")

    assert payload["ok"] is True
    assert [section["id"] for section in payload["sections"]] == ["app"]
    assert payload["section"]["refresh_interval_seconds"] == 60


def test_system_status_deep_links_target_real_sections():
    from pathlib import Path

    config_source = Path("templates/configuration.html").read_text(encoding="utf-8")
    dashboard_source = Path("templates/dashboard.html").read_text(encoding="utf-8")

    assert 'id="configuration-connections"' in config_source
    assert 'id="configuration-database"' in config_source
    assert 'id="event-bridge-configuration"' in config_source
    assert 'id="requests-refresh"' in dashboard_source


def test_configuration_template_exposes_system_status_tab():
    from pathlib import Path

    source = Path("templates/configuration.html").read_text(encoding="utf-8")

    assert 'data-tab="system-status"' in source
    assert 'data-tab-panel="system-status"' in source
    assert 'data-system-status-endpoint="/api/system/status"' in source
    assert "system_status.js" in source


@pytest.mark.anyio
async def test_event_bridge_status_route_returns_live_diagnostics(monkeypatch):
    from web import config_routes

    config_routes.init_config_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        flash=lambda *_args, **_kwargs: None,
        get_flash_messages=lambda _request: [],
        get_csrf_token=lambda _request: "csrf",
        templates=object(),
        resolve_next_url=lambda _next, default: f"/{default}",
    )
    monkeypatch.setattr(
        config_routes,
        "load_config",
        lambda: (
            {
                "EMBY": {"SERVERS": [{"id": "green", "alias": "Green"}]},
                "EVENT_BRIDGE": {
                    "SERVERS": {
                        "green": {
                            "WEBSOCKET_RECONNECT_SECONDS": 3,
                            "PLAYBACK_EVENT_NAMES": ["PlaybackStart"],
                        }
                    }
                },
            },
            True,
        ),
    )

    class _Manager:
        def status(self):
            return {
                "ok": True,
                "connected": 1,
                "servers": [
                    {
                        "server_id": "green",
                        "connected": True,
                        "received_count": 4,
                        "plugin_version": "0.4.2",
                        "last_seen_at": "2026-08-11T10:00:00+00:00",
                        "last_event_at": "2026-08-11T10:00:01+00:00",
                        "last_event_type": "plugin.config_saved",
                        "last_event_name": "PluginConfigSaved",
                        "last_plugin_settings_at": "2026-08-11T10:00:02+00:00",
                        "last_config_ack_status": "applied",
                        "last_config_ack_at": "2026-08-11T10:00:03+00:00",
                        "plugin_settings": {
                            "WEBSOCKET_RECONNECT_SECONDS": 5,
                            "PLAYBACK_EVENT_NAMES": ["PlaybackStart"],
                        },
                        "plugin_target_count": 2,
                        "plugin_targets": [
                            {"name": "OctoHubs 1", "url": "https://primary.example"},
                            {"name": "OctoHubs 2", "url": "https://secondary.example"},
                        ],
                    }
                ],
            }

    monkeypatch.setattr(config_routes, "get_event_bridge_manager", lambda: _Manager())

    response = await config_routes.event_bridge_status_route(object())
    payload = json.loads(response.body.decode("utf-8"))
    server = payload["servers"][0]

    assert payload["connected"] == 1
    assert server["id"] == "green"
    assert server["transport"]["label"] == "WebSocket connesso"
    assert server["config_ack"]["label"] == "Config applicata"
    assert server["settings"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert server["diagnostics"]["sync_label"] == "Config diversa"
    assert server["diagnostics"]["plugin_version_label"] == "Plugin 0.4.2"
    assert server["diagnostics"]["last_seen_at"] == "2026-08-11 10:00:00 UTC"
    assert server["diagnostics"]["last_event_at"] == "2026-08-11 10:00:01 UTC"
    assert server["diagnostics"]["last_plugin_settings_at"] == "2026-08-11 10:00:02 UTC"
    assert server["diagnostics"]["last_config_ack_at"] == "2026-08-11 10:00:03 UTC"
    assert server["diagnostics"]["target_count_label"] == "2"
    assert server["diagnostics"]["plugin_targets"][1]["url"] == "https://secondary.example"
    assert server["diagnostics"]["diffs"] == [
        {"label": "Reconnect WS", "octohubs": "3", "plugin": "5"}
    ]
