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
        "DATABASE": {
            "ENABLED": True,
            "HOST": "postgres",
            "PASSWORD": "database-secret",
            "PARAMS": "sslmode=require&sslpassword=database-tls-secret&application_name=OctoHubs",
        },
        "JELLYSEERR_URL": "http://jellyseerr:5055",
        "JELLYSEERR_API_KEY": "jellyseerr-secret",
        "PROWLARR_URL": "https://reader:prowlarr-url-secret@prowlarr:9696/base?safe=1&access_token=prowlarr-token",
        "JACKETT_URL": "https://jackett:9117/base?safe=hello%20world",
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
    assert payload["services"]["connections"]["jackett"]["url"] == "https://jackett:9117/base?safe=hello%20world"
    assert payload["services"]["connections"]["prowlarr"]["url"] == (
        "https://[REDACTED]@prowlarr:9696/base?safe=1&access_token=[REDACTED]"
    )
    assert payload["services"]["database"]["params"] == (
        "sslmode=require&sslpassword=[REDACTED]&application_name=OctoHubs"
    )
    assert payload["services"]["trakt"]["client_id"] == "trakt-id"
    assert "database-secret" not in serialized
    assert "jellyseerr-secret" not in serialized
    assert "qb-secret" not in serialized
    assert "trakt-secret" not in serialized
    assert "database-tls-secret" not in serialized
    assert "prowlarr-url-secret" not in serialized
    assert "prowlarr-token" not in serialized


def test_service_settings_reject_new_url_credentials_but_keep_existing_redacted_echo(monkeypatch):
    from services import configuration_settings, manager

    existing_url = "https://reader:existing-secret@prowlarr:9696/base?access_token=existing-token"
    safe_snapshot = configuration_settings.configuration_services_snapshot(
        {"PROWLARR_URL": existing_url}
    )["connections"]["prowlarr"]["url"]
    saved = {}
    monkeypatch.setattr(manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(
        manager,
        "_save_app_settings_snapshot",
        lambda settings: saved.update(settings) or True,
    )

    configuration_settings.update_service_settings(
        {"connections": {"prowlarr": {"url": safe_snapshot}}},
        {"PROWLARR_URL": existing_url},
    )

    assert saved["PROWLARR_URL"] == existing_url
    with pytest.raises(ValueError, match="campo dedicato"):
        configuration_settings.update_service_settings(
            {
                "connections": {
                    "prowlarr": {
                        "url": "https://new-user:new-secret@prowlarr:9696?token=new-token"
                    }
                }
            },
            {"PROWLARR_URL": existing_url},
        )


@pytest.mark.parametrize(
    "parameter_name",
    [
        "x-api-key",
        "api-token",
        "private_key",
        "id_token",
        "refresh-token",
        "X-Amz-Credential",
        "X-Amz-Signature",
        "db_password",
        "api_token_value",
        "private_key_file",
    ],
)
def test_connection_urls_reject_compound_credential_parameter_names(parameter_name):
    from core.configuration_redaction import (
        connection_url_has_credentials,
        public_connection_url,
        submitted_connection_url,
    )

    canary = "R18_COMPOUND_CREDENTIAL_CANARY"
    url = f"https://service.invalid/base?mode=safe&{parameter_name}={canary}"

    assert connection_url_has_credentials(url) is True
    assert canary not in public_connection_url(url)
    with pytest.raises(ValueError, match="campo dedicato"):
        submitted_connection_url(url)


@pytest.mark.parametrize(
    "parameter_name",
    ["obsession", "monkey", "keyboard", "keyframe"],
)
def test_connection_urls_keep_non_credential_key_words(parameter_name):
    from core.configuration_redaction import (
        connection_url_has_credentials,
        public_connection_url,
        submitted_connection_url,
    )

    url = f"https://service.invalid/base?{parameter_name}=ordinary-value"

    assert connection_url_has_credentials(url) is False
    assert public_connection_url(url) == url
    assert submitted_connection_url(url) == url


def test_connection_urls_fail_closed_when_url_parsing_fails():
    from core.configuration_redaction import (
        PUBLIC_REDACTION,
        connection_url_has_credentials,
        public_connection_url,
        submitted_connection_url,
    )

    canary = "R18_MALFORMED_URL_SECRET_CANARY"
    malformed = f"https://reader:{canary}@[invalid"

    assert public_connection_url(malformed) == PUBLIC_REDACTION
    assert canary not in public_connection_url(malformed)
    assert connection_url_has_credentials(malformed) is True
    with pytest.raises(ValueError, match="URL non valido"):
        submitted_connection_url(malformed)


def test_connection_urls_allow_replacing_or_clearing_a_malformed_existing_fallback():
    from core.configuration_redaction import PUBLIC_REDACTION, submitted_connection_url

    malformed = "https://reader:legacy-secret@[invalid"

    assert submitted_connection_url(PUBLIC_REDACTION, malformed) == malformed
    assert submitted_connection_url("", malformed) == ""
    assert submitted_connection_url("https://service.invalid", malformed) == (
        "https://service.invalid"
    )


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


def test_app_settings_cache_is_not_changed_when_storage_write_fails(monkeypatch):
    from core import config_manager
    from core.storage import StorageError
    from services import app_settings

    class _Backend:
        def update_app_settings(self, _updates):
            raise StorageError("write failed")

    monkeypatch.setattr(
        config_manager,
        "_ACTIVE_CONFIG",
        {"AUTO_TASKS": {"enabled": False}},
    )
    monkeypatch.setattr(app_settings, "_ensure_db_backend", lambda: _Backend())

    with pytest.raises(StorageError):
        app_settings._update_app_settings_overrides(
            {"AUTO_TASKS": {"enabled": True}},
        )

    assert config_manager._ACTIVE_CONFIG["AUTO_TASKS"] == {"enabled": False}


def test_app_settings_read_failure_is_propagated_without_attempting_a_write(
    monkeypatch,
):
    from core import config_manager
    from core.storage import StorageError
    from services import configuration_settings, manager

    calls = {"save": 0}

    class _Backend:
        def load_app_settings(self):
            raise StorageError("temporary read failure")

        def save_app_settings(self, _settings):
            calls["save"] += 1

    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: _Backend())

    with pytest.raises(StorageError, match="temporary read failure"):
        configuration_settings.update_service_settings({}, {})

    assert calls["save"] == 0
    with pytest.raises(StorageError, match="temporary read failure"):
        manager._load_app_settings_snapshot()


def test_update_service_settings_preserves_unrelated_secrets_but_invalidates_tokens_for_new_client(monkeypatch):
    from services import configuration_settings
    from services import manager

    saved = {}
    monkeypatch.setattr(manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(manager, "_save_app_settings_snapshot", lambda settings: saved.update(settings) or True)

    configuration_settings.update_service_settings(
        {
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

    assert saved["JELLYSEERR_API_KEY"] == "jelly-secret"
    assert saved["TMDB_API_KEY"] == "tmdb-secret"
    assert saved["MDBLIST_API_KEYS"] == ["mdb-secret"]
    assert saved["OMDB_API_KEYS"] == ["omdb-secret"]
    assert saved["TRAKT"]["CLIENT_SECRET"] == "trakt-secret"
    assert saved["TRAKT"]["ACCESS_TOKEN"] == ""
    assert saved["TRAKT"]["REFRESH_TOKEN"] == ""
    assert saved["TRAKT"]["EXPIRES_AT"] == ""
    assert saved["TRAKT"]["ENABLED"] is False


def test_update_service_settings_can_explicitly_clear_saved_credentials(monkeypatch):
    from services import configuration_settings
    from services import manager

    saved = {}
    monkeypatch.setattr(manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(manager, "_save_app_settings_snapshot", lambda settings: saved.update(settings) or True)

    configuration_settings.update_service_settings(
        {
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
async def test_configuration_api_rejects_service_save_until_deployment_database_is_valid(monkeypatch):
    from fastapi import HTTPException
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    config = {"DATABASE": {"ENABLED": False}}
    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: (config, False),
    )
    saved = []
    monkeypatch.setattr(configuration_api_routes, "update_service_settings", lambda payload, target: saved.append((payload, target)))

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}

    with pytest.raises(HTTPException) as exc_info:
        await configuration_api_routes.update_configuration_services_api_route(
            _Request(),
            ConfigurationServicesUpdateRequest(),
        )

    assert exc_info.value.status_code == 409
    assert saved == []


@pytest.mark.anyio
async def test_configuration_api_does_not_publish_when_service_storage_write_fails(
    monkeypatch,
):
    from fastapi import HTTPException

    from core.storage import StorageError
    from web import configuration_api_routes
    from web.configuration_api_models import ConfigurationServicesUpdateRequest

    config = {"DATABASE": {"ENABLED": True}}
    configuration_api_routes.init_configuration_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: (config, True),
    )
    published = []
    monkeypatch.setattr(
        configuration_api_routes,
        "update_service_settings",
        lambda *_args: (_ for _ in ()).throw(StorageError("write failed")),
    )
    monkeypatch.setattr(
        configuration_api_routes,
        "publish_configuration_update",
        published.append,
    )

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}

    with pytest.raises(HTTPException) as exc_info:
        await configuration_api_routes.update_configuration_services_api_route(
            _Request(),
            ConfigurationServicesUpdateRequest(),
        )

    assert exc_info.value.status_code == 500
    assert published == []


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
        {"database": {"host": "postgres"}},
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

    assert route.body_field.field_info.annotation is ConfigurationServicesUpdateRequest
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
