import json
from types import SimpleNamespace

import pytest


def test_configuration_snapshot_keeps_credentials_out_of_the_browser_payload():
    from services.configuration_settings import (
        configuration_automation_snapshot,
        configuration_services_snapshot,
    )

    config = {
        "AUTO_TASKS": {"scan": {"enabled": True, "mode": "fixed", "interval_minutes": 30, "times": ["7", "22:30"]}},
        "DATABASE": {"ENABLED": True, "HOST": "postgres", "PASSWORD": "database-secret"},
        "JELLYSEERR_URL": "http://jellyseerr:5055",
        "JELLYSEERR_API_KEY": "jellyseerr-secret",
        "QBITTORRENT_PASSWORD": "qb-secret",
        "TRAKT": {"CLIENT_ID": "trakt-id", "CLIENT_SECRET": "trakt-secret", "ACCESS_TOKEN": "token"},
    }

    payload = {
        "automations": configuration_automation_snapshot(config),
        "services": configuration_services_snapshot(config),
    }
    serialized = json.dumps(payload)

    assert payload["automations"]["tasks"]["scan"]["times"] == ["07:00", "22:30"]
    assert payload["services"]["connections"]["jellyseerr"]["api_key_configured"] is True
    assert payload["services"]["trakt"]["client_id"] == "trakt-id"
    assert "database-secret" not in serialized
    assert "jellyseerr-secret" not in serialized
    assert "qb-secret" not in serialized
    assert "trakt-secret" not in serialized


def test_configuration_snapshot_includes_the_latest_request_refresh_state(monkeypatch):
    from web import configuration_api_routes

    monkeypatch.setattr(
        configuration_api_routes,
        "get_jellyseerr_refresh_state",
        lambda: {
            "running": False,
            "last_status": "skipped",
            "last_warning": "Jellyseerr non risponde",
            "last_warning_at": "2026-08-12T09:15:22+00:00",
            "last_error": None,
            "completed_at": "2026-08-12T09:15:22+00:00",
        },
    )

    snapshot = configuration_api_routes._snapshot({}, True)

    assert snapshot["request_refresh"]["last_status"] == "skipped"
    assert snapshot["request_refresh"]["last_warning"] == "Jellyseerr non risponde"


def test_update_automation_settings_normalizes_and_persists(monkeypatch):
    from core import config_manager
    from services import configuration_settings

    saved = {}
    synchronized = []
    config = {
        "AUTO_TASKS": {"scan": {"enabled": False, "mode": "interval", "interval_minutes": 240, "times": []}},
        "COLLECTIONS": {},
    }
    monkeypatch.setattr(configuration_settings, "_update_app_settings_overrides", lambda payload: saved.update(payload))
    monkeypatch.setattr(configuration_settings, "sync_auto_scheduler", lambda ready: synchronized.append(ready))
    monkeypatch.setattr(config_manager, "_ACTIVE_CONFIG", {}, raising=False)

    snapshot = configuration_settings.update_automation_settings(
        {
            "tasks": {"scan": {"enabled": True, "mode": "fixed", "interval_minutes": 0, "times": ["7", "22:70"]}},
            "collections": {"enabled": True, "mode": "fixed", "interval_minutes": 1, "times": ["9:05", "9:05"]},
        },
        config,
    )

    assert saved["AUTO_TASKS"]["scan"] == {
        "enabled": True,
        "mode": "fixed",
        "interval_minutes": 1,
        "times": ["07:00", "22:59"],
    }
    assert saved["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"] == 5
    assert snapshot["collections"]["times"] == ["09:05"]
    assert synchronized == [True]


def test_update_service_settings_preserves_omitted_credentials(monkeypatch):
    from services import configuration_settings
    from services import manager

    saved = {}
    written_database = {}

    class _Database:
        def __init__(self, settings):
            self.settings = settings

        def ensure_ready(self):
            return None

    monkeypatch.setattr(configuration_settings, "DatabaseStorage", _Database)
    monkeypatch.setattr(configuration_settings, "read_raw_config", lambda: {"DATABASE": {}})
    monkeypatch.setattr(manager, "_apply_db_env_overrides", lambda settings: settings)
    monkeypatch.setattr(manager, "_seed_db_from_legacy_config", lambda _legacy, _backend: None)
    monkeypatch.setattr(manager, "_write_database_config", lambda settings: written_database.update(settings))
    monkeypatch.setattr(manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(manager, "_save_app_settings_snapshot", lambda settings: saved.update(settings) or True)

    configuration_settings.update_service_settings(
        {
            "database": {
                "host": "postgres",
                "port": "5432",
                "name": "octohubs",
                "user": "octohubs",
                "driver": "postgresql+psycopg2",
                "params": "",
            },
            "connections": {
                "jellyseerr": {"url": "http://jellyseerr:5055"},
                "prowlarr": {"url": "http://prowlarr:9696"},
                "jackett": {"url": ""},
                "qbittorrent": {"url": "", "username": ""},
                "tmdb": {"language": "it-IT"},
                "mdblist": {},
                "omdb": {},
            },
            "trakt": {"enabled": True, "client_id": "client-id"},
            "justwatch": {"enabled": True, "locale": "it_IT"},
        },
        {
            "DATABASE": {"PASSWORD": "database-secret"},
            "JELLYSEERR_API_KEY": "jelly-secret",
            "TMDB_API_KEY": "tmdb-secret",
            "MDBLIST_API_KEYS": ["mdb-secret"],
            "OMDB_API_KEYS": ["omdb-secret"],
            "TRAKT": {"CLIENT_ID": "old-client", "CLIENT_SECRET": "trakt-secret", "ACCESS_TOKEN": "access", "REFRESH_TOKEN": "refresh"},
            "JUSTWATCH": {"ENABLED": False, "LOCALE": "it_IT"},
        },
    )

    assert written_database["PASSWORD"] == "database-secret"
    assert saved["JELLYSEERR_API_KEY"] == "jelly-secret"
    assert saved["TMDB_API_KEY"] == "tmdb-secret"
    assert saved["MDBLIST_API_KEYS"] == ["mdb-secret"]
    assert saved["OMDB_API_KEYS"] == ["omdb-secret"]
    assert saved["TRAKT"]["CLIENT_SECRET"] == "trakt-secret"
    assert saved["TRAKT"]["REFRESH_TOKEN"] == "refresh"


def test_update_service_settings_can_explicitly_clear_saved_credentials(monkeypatch):
    from services import configuration_settings
    from services import manager

    saved = {}

    class _Database:
        def __init__(self, _settings):
            pass

        def ensure_ready(self):
            return None

    monkeypatch.setattr(configuration_settings, "DatabaseStorage", _Database)
    monkeypatch.setattr(configuration_settings, "read_raw_config", lambda: {"DATABASE": {}})
    monkeypatch.setattr(manager, "_apply_db_env_overrides", lambda settings: settings)
    monkeypatch.setattr(manager, "_seed_db_from_legacy_config", lambda _legacy, _backend: None)
    monkeypatch.setattr(manager, "_write_database_config", lambda _settings: None)
    monkeypatch.setattr(manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(manager, "_save_app_settings_snapshot", lambda settings: saved.update(settings) or True)

    configuration_settings.update_service_settings(
        {
            "database": {"host": "postgres", "port": "5432", "name": "octohubs", "user": "octohubs", "clear_password": True},
            "connections": {
                "jellyseerr": {"url": "", "clear_api_key": True},
                "prowlarr": {"url": ""},
                "jackett": {"url": ""},
                "qbittorrent": {"url": "", "username": "", "clear_password": True},
                "tmdb": {"language": "it-IT", "clear_api_key": True},
                "mdblist": {"clear_api_keys": True},
                "omdb": {"clear_api_keys": True},
            },
            "trakt": {"enabled": False, "client_id": "", "clear_client_secret": True},
            "justwatch": {"enabled": False, "locale": "it_IT"},
        },
        {
            "DATABASE": {"PASSWORD": "database-secret"},
            "JELLYSEERR_API_KEY": "jelly-secret",
            "QBITTORRENT_PASSWORD": "qb-secret",
            "TMDB_API_KEY": "tmdb-secret",
            "MDBLIST_API_KEYS": ["mdb-secret"],
            "OMDB_API_KEYS": ["omdb-secret"],
            "TRAKT": {"CLIENT_SECRET": "trakt-secret"},
        },
    )

    assert saved["JELLYSEERR_API_KEY"] == ""
    assert saved["QBITTORRENT_PASSWORD"] == ""
    assert saved["TMDB_API_KEY"] == ""
    assert saved["MDBLIST_API_KEYS"] == []
    assert saved["OMDB_API_KEYS"] == []
    assert saved["TRAKT"]["CLIENT_SECRET"] == ""


@pytest.mark.anyio
async def test_configuration_api_updates_automations_with_csrf(monkeypatch):
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationAutomationsPayload

    config = {"AUTO_TASKS": {}, "COLLECTIONS": {}}
    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: (config, True),
    )
    saved = []
    published = []
    monkeypatch.setattr(configuration_api_routes, "update_automation_settings", lambda payload, target: saved.append((payload, target)))
    monkeypatch.setattr(configuration_api_routes, "publish_configuration_update", published.append)

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}

        async def json(self):
            return {"tasks": {"scan": {"enabled": True}}}

    response = await configuration_api_routes.update_configuration_automations_api_route(
        _Request(),
        ConfigurationAutomationsPayload.model_validate({"tasks": {"scan": {"enabled": True}}}),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert saved == [({"tasks": {"scan": {"enabled": True}}}, config)]
    assert published == ["automations"]
    assert payload["success"] is True
    assert payload["message"] == "Automazioni aggiornate"


@pytest.mark.anyio
async def test_configuration_api_allows_service_save_to_bootstrap_an_invalid_database_config(monkeypatch):
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    config = {"DATABASE": {"ENABLED": False}}

    def load_config():
        return config, bool(config["DATABASE"].get("ENABLED"))

    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=load_config,
    )
    saved = []
    published = []

    def update_services(payload, target):
        saved.append((payload, target))
        target["DATABASE"] = {"ENABLED": True, "HOST": "postgres", "NAME": "octohubs", "USER": "octohubs"}

    monkeypatch.setattr(configuration_api_routes, "update_service_settings", update_services)
    monkeypatch.setattr(configuration_api_routes, "publish_configuration_update", published.append)

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}

        async def json(self):
            return {
                "database": {
                    "host": "postgres",
                    "name": "octohubs",
                    "user": "octohubs",
                }
            }

    request = _Request()
    response = await configuration_api_routes.update_configuration_services_api_route(
        request,
        ConfigurationServicesUpdateRequest.model_validate(await request.json()),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert saved == [
        (
            {"database": {"host": "postgres", "name": "octohubs", "user": "octohubs"}},
            config,
        )
    ]
    assert payload["success"] is True
    assert payload["has_config"] is True
    assert payload["services"]["database"]["host"] == "postgres"
    assert payload["message"] == "Configurazione servizi aggiornata"
    assert published == ["services"]


@pytest.mark.anyio
async def test_configuration_api_rejects_invalid_csrf():
    from fastapi import HTTPException
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationAutomationsPayload

    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: False,
        load_config=lambda: ({}, True),
    )

    with pytest.raises(HTTPException, match="CSRF token non valido"):
        await configuration_api_routes.update_configuration_automations_api_route(
            SimpleNamespace(headers={}, json=lambda: {}),
            ConfigurationAutomationsPayload(),
        )


def test_configuration_automations_reject_string_booleans():
    from pydantic import ValidationError
    from web.configuration_api_models import ConfigurationAutomationsPayload

    with pytest.raises(ValidationError):
        ConfigurationAutomationsPayload.model_validate(
            {"tasks": {"scan": {"enabled": "false"}}}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"trakt": {"enabled": "false"}},
        {"justwatch": {"enabled": 0}},
        {"database": {"clear_password": "false"}},
        {"database": {"host": None}},
        {"database": {"port": 5432.5}},
        {"database": {"port": 70000}},
        {"connections": {"mdblist": {"api_keys": [123]}}},
        {"connections": {"jellyseerr": {"unexpected": True}}},
        {"unexpected": {}},
    ],
)
def test_configuration_services_reject_invalid_types_and_unknown_fields(payload):
    from pydantic import ValidationError
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    with pytest.raises(ValidationError):
        ConfigurationServicesUpdateRequest.model_validate(payload)


def test_configuration_services_route_binds_the_validated_body_model():
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    route = next(
        route
        for route in configuration_api_routes.router.routes
        if getattr(route, "path", "") == "/api/configuration/services"
    )
    value, errors = route.body_field.validate(
        {"justwatch": {"enabled": "false"}},
        {},
        loc=("body",),
    )

    assert route.body_field.type_ is ConfigurationServicesUpdateRequest
    assert value is None
    assert errors[0]["type"] == "bool_type"
    assert errors[0]["loc"] == ("body", "justwatch", "enabled")


@pytest.mark.anyio
async def test_configuration_services_preserves_explicit_false_values(monkeypatch):
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    config = {"DATABASE": {"ENABLED": True}}
    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: (config, True),
    )
    saved = []
    monkeypatch.setattr(
        configuration_api_routes,
        "update_service_settings",
        lambda payload, target: saved.append((payload, target)),
    )

    request = SimpleNamespace(headers={"X-CSRF-Token": "csrf"})
    response = await configuration_api_routes.update_configuration_services_api_route(
        request,
        ConfigurationServicesUpdateRequest.model_validate(
            {
                "trakt": {"enabled": False},
                "justwatch": {"enabled": False},
            }
        ),
    )

    assert response.status_code == 200
    assert saved == [
        (
            {
                "trakt": {"enabled": False},
                "justwatch": {"enabled": False},
            },
            config,
        )
    ]
