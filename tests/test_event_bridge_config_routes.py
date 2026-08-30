import json
from types import SimpleNamespace

import pytest


def test_event_bridge_merge_preserves_hidden_server_settings():
    from emby_runtime.event_bridge_settings import normalize_event_bridge_config
    from emby_runtime.event_bridge_configuration import _merged_event_bridge_config

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
    from emby_runtime.event_bridge_configuration import _event_bridge_servers_for_view

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
    config_error = _system_item(
        "bridge-config-error",
        "Green",
        "error",
        "Configurazione non applicata",
        status_code="config_error",
    )
    assert config_error["status_label"] == "Errore configurazione"
    assert _system_rollup_severity([{"severity": "unknown"}]) == "unknown"
    assert _system_rollup_severity([{"severity": "unknown"}, {"severity": "ok"}]) == "ok"

    section = _system_section("event-bridge", "Event Bridge", [item])
    assert section["status_code"] == "warning"
    assert section["status_label"] == "Avviso"


def test_event_bridge_configuration_ack_uses_the_same_italian_error_label():
    from emby_runtime.event_bridge_configuration import _event_bridge_config_ack_payload

    payload = _event_bridge_config_ack_payload(
        {"last_config_ack_status": "rejected", "last_config_ack_error": "Plugin non raggiungibile"}
    )

    assert payload["label"] == "Errore configurazione"
    assert payload["class_name"] == "status-fail"


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
    assert jellyseerr["href"] == "/app/configuration/services?focus=configuration-connections"
    by_id = {item["id"]: item for item in section["items"]}
    assert by_id["service-mdblist"]["href"] == "/app/configuration/services?focus=configuration-metadata"
    assert by_id["service-trakt"]["href"] == "/app/configuration/services?focus=configuration-catalogs"
    assert by_id["service-database"]["href"] == "/app/configuration/services?focus=configuration-database"
    assert section["checked_at"] == "2026-08-11 11:30:45 UTC"


def test_system_database_reports_a_connection_failure_without_claiming_it_is_connected(monkeypatch):
    from web import config_routes

    class _Backend:
        def get_migration_status(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(config_routes._config_manager, "_DB_BACKEND", _Backend())

    section = config_routes._system_database_section(
        {
            "DATABASE": {
                "ENABLED": True,
                "HOST": "postgres",
                "NAME": "octohubs",
                "USER": "octohubs",
            }
        },
        True,
    )
    by_id = {item["id"]: item for item in section["items"]}

    assert by_id["database-connection"]["status_code"] == "disconnected"
    assert by_id["database-connection"]["summary"] == "Connessione non disponibile"
    assert by_id["database-connection"]["detail"] == "connection refused"
    assert by_id["database-connection"]["href"] == "/app/configuration/services?focus=configuration-database"
    assert by_id["database-migrations"]["status_code"] == "unknown"
    assert by_id["database-migrations"]["summary"] == "Migrazioni non verificabili"
    assert by_id["database-migrations"]["href"] == "/app/configuration/services?focus=configuration-database"


def test_system_status_can_return_one_operational_section(monkeypatch):
    from web import config_routes

    monkeypatch.setattr(config_routes, "load_config", lambda: ({"DATABASE": {}}, True))

    payload = config_routes._build_system_status_snapshot(section_id="app")

    assert payload["ok"] is True
    assert [section["id"] for section in payload["sections"]] == ["app"]
    assert payload["section"]["refresh_interval_seconds"] == 60


def test_system_status_uses_an_italian_label_when_emby_health_is_unavailable(
    monkeypatch,
):
    from emby_runtime import snapshots
    from web import config_routes

    def fail_health_snapshot():
        raise RuntimeError("server non raggiungibile")

    monkeypatch.setattr(snapshots, "_build_emby_health_status_snapshot", fail_health_snapshot)

    section = config_routes._system_emby_section({"EMBY": {"SERVERS": [{"id": "green"}]}})

    assert section["items"][0]["label"] == "Stato server"
    assert section["items"][0]["summary"] == "Stato Emby non leggibile"
    assert section["items"][0]["href"] == "/app/emby-live?focus=emby-live-servers"


@pytest.mark.anyio
async def test_event_bridge_status_route_returns_live_diagnostics(monkeypatch):
    from web import event_bridge_api_routes

    event_bridge_api_routes.init_event_bridge_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        load_config_func=lambda: (
            {
                "EMBY": {
                    "SERVERS": [
                        {
                            "id": "green",
                            "alias": "Green",
                            "icon": "fa-film",
                            "icon_color": "#8B5CF6",
                            "icon_style": "regular",
                        }
                    ]
                },
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
                        "last_config_transport": "http",
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

    monkeypatch.setattr(event_bridge_api_routes, "get_event_bridge_manager", lambda: _Manager())
    monkeypatch.setattr(event_bridge_api_routes, "event_bridge_credential_server_ids", lambda: {"green"})

    response = await event_bridge_api_routes.event_bridge_status_route(object())
    payload = json.loads(response.body.decode("utf-8"))
    server = payload["servers"][0]

    assert payload["connected"] == 1
    assert "webhook_secret_configured" in payload
    assert payload["credential_configured"] == 1
    assert server["id"] == "green"
    assert server["icon"] == "fa-film"
    assert server["icon_color"] == "#8B5CF6"
    assert server["icon_style"] == "regular"
    assert server["transport"]["label"] == "WebSocket connesso"
    assert server["credential"]["configured"] is True
    assert server["config_ack"]["label"] == "Config applicata"
    assert server["settings"]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert server["diagnostics"]["sync_label"] == "Config diversa"
    assert server["diagnostics"]["plugin_version_label"] == "Plugin 0.4.2"
    assert server["diagnostics"]["last_seen_at"] == "2026-08-11 10:00:00 UTC"
    assert server["diagnostics"]["last_event_at"] == "2026-08-11 10:00:01 UTC"
    assert server["diagnostics"]["last_plugin_settings_at"] == "2026-08-11 10:00:02 UTC"
    assert server["diagnostics"]["last_config_ack_at"] == "2026-08-11 10:00:03 UTC"
    assert server["diagnostics"]["last_config_transport_label"] == "HTTP"
    assert server["diagnostics"]["target_count_label"] == "2"
    assert server["diagnostics"]["plugin_targets"][1]["url"] == "https://secondary.example"
    assert server["diagnostics"]["diffs"] == [
        {"label": "Reconnect WS", "octohubs": "3", "plugin": "5"}
    ]


@pytest.mark.anyio
async def test_event_bridge_settings_api_saves_and_prefers_http_push(monkeypatch):
    from emby_runtime import event_bridge_configuration
    from web import event_bridge_api_routes

    event_bridge_api_routes.init_event_bridge_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf-token",
        load_config_func=lambda: (config, True),
    )
    config = {
        "EMBY": {"SERVERS": [{"id": "green", "alias": "Green", "url": "https://emby.example"}]},
        "EVENT_BRIDGE": {"SERVERS": {"green": {"WEBSOCKET_RECONNECT_SECONDS": 5}}},
    }
    saved: dict[str, object] = {}
    http_pushes: list[tuple[str, int]] = []

    class _Manager:
        def status(self):
            return {"servers": [{"server_id": "green", "connected": True}]}

        def record_plugin_configuration_response(self, server_id, response):
            assert server_id == "green"
            assert response == {"Ok": True, "Applied": True}

        async def push_configuration(self, *_args):
            raise AssertionError("WebSocket must not be used after a successful HTTP push")

    monkeypatch.setattr(event_bridge_api_routes, "_save_event_bridge_settings", lambda settings: saved.update(settings))
    monkeypatch.setattr(event_bridge_configuration, "get_event_bridge_manager", lambda: _Manager())

    def _push_http(server, server_id, settings):
        assert server["id"] == server_id == "green"
        http_pushes.append((server_id, settings["WEBSOCKET_RECONNECT_SECONDS"]))
        return True, "", {"Ok": True, "Applied": True}

    monkeypatch.setattr(event_bridge_configuration, "push_event_bridge_settings_to_plugin", _push_http)

    request = SimpleNamespace(
        headers={"X-CSRF-Token": "csrf-token"},
        json=lambda: None,
    )

    async def _json_payload():
        return {"servers": {"green": {"WEBSOCKET_RECONNECT_SECONDS": 3}}}

    request.json = _json_payload
    response = await event_bridge_api_routes.update_event_bridge_settings_api_route(request)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["ok"] is True
    assert payload["push"]["http_pushed"] == 1
    assert payload["push"]["websocket_pushed"] == 0
    assert http_pushes == [("green", 3)]
    assert saved["SERVERS"]["green"]["WEBSOCKET_RECONNECT_SECONDS"] == 3


@pytest.mark.anyio
async def test_event_bridge_settings_api_requires_csrf_token(monkeypatch):
    from fastapi import HTTPException
    from web import event_bridge_api_routes

    event_bridge_api_routes.init_event_bridge_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: False,
        load_config_func=lambda: ({}, True),
    )

    request = SimpleNamespace(headers={}, json=lambda: None)
    with pytest.raises(HTTPException, match="CSRF token non valido") as error:
        await event_bridge_api_routes.update_event_bridge_settings_api_route(request)

    assert error.value.status_code == 403


@pytest.mark.anyio
async def test_event_bridge_credential_api_provisions_configured_server(monkeypatch):
    from emby_runtime.event_bridge_provisioning import EventBridgeProvisioningResult
    from web import event_bridge_api_routes

    config = {
        "EMBY": {"SERVERS": [{"id": "green", "url": "https://emby.example", "api_key": "key"}]},
        "EVENT_BRIDGE": {"SERVERS": {"green": {"WEBSOCKET_RECONNECT_SECONDS": 3}}},
    }
    event_bridge_api_routes.init_event_bridge_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf-token",
        load_config_func=lambda: (config, True),
    )
    calls = []
    response_payload = {
        "Ok": True,
        "ServerId": "green",
        "Settings": {"perServerCredentialSupported": True, "credentialConfigured": True},
    }
    monkeypatch.setattr(
        event_bridge_api_routes,
        "provision_event_bridge_credential",
        lambda server, server_id, settings: (
            calls.append((server, server_id, settings))
            or EventBridgeProvisioningResult(True, response=response_payload)
        ),
    )

    class _Manager:
        def record_plugin_configuration_response(self, server_id, response):
            calls.append((server_id, response))

        async def close_server_connection(self, server_id):
            calls.append(("closed", server_id))
            return True

    monkeypatch.setattr(event_bridge_api_routes, "get_event_bridge_manager", lambda: _Manager())
    request = SimpleNamespace(headers={"X-CSRF-Token": "csrf-token"})

    response = await event_bridge_api_routes.provision_event_bridge_credential_api_route("green", request)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["ok"] is True
    assert payload["configured"] is True
    assert calls[0][1] == "green"
    assert calls[0][2]["WEBSOCKET_RECONNECT_SECONDS"] == 3
    assert calls[1] == ("green", response_payload)
    assert calls[2] == ("closed", "green")
