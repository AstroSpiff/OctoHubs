from __future__ import annotations

from unittest.mock import Mock

from fastapi.exceptions import RequestValidationError
import pytest


class _JsonRequest:
    headers: dict[str, str] = {}

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def _initialize_service_routes() -> None:
    from services.routes import init_service_routes

    init_service_routes(require_auth=lambda _request: {"username": "admin"})


@pytest.mark.anyio
async def test_trakt_rejects_numeric_client_id_before_calling_manager(monkeypatch):
    from services import manager
    from services.routes import trakt_device_start_api

    _initialize_service_routes()
    build_snapshot = Mock()
    monkeypatch.setattr(manager, "_build_trakt_device_start_snapshot", build_snapshot)

    with pytest.raises(RequestValidationError) as raised:
        await trakt_device_start_api(_JsonRequest({"client_id": 1}))

    assert raised.value.errors()[0]["loc"] == ("body", "client_id")
    build_snapshot.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "an", "object"],
        {"client_id": "client", "unexpected": True},
    ],
)
@pytest.mark.anyio
async def test_trakt_rejects_non_object_and_unknown_fields(payload):
    from services.routes import trakt_device_start_api

    _initialize_service_routes()
    with pytest.raises(RequestValidationError):
        await trakt_device_start_api(_JsonRequest(payload))


@pytest.mark.anyio
async def test_trakt_device_start_returns_revision_without_cacheable_credentials(monkeypatch):
    from services import manager
    from services.routes import trakt_device_start_api

    _initialize_service_routes()
    monkeypatch.setattr(
        manager,
        "_build_trakt_device_start_snapshot",
        lambda _payload: ({
            "success": True,
            "device_code": "device-code",
            "user_code": "USER-CODE",
            "verification_url": "https://trakt.tv/activate",
            "expires_in": 600,
            "interval": 5,
            "config_revision": "opaque-revision",
        }, 200),
    )

    response = await trakt_device_start_api(_JsonRequest({"client_id": "client"}))

    assert response.headers["cache-control"] == "no-store"
    assert b'"config_revision":"opaque-revision"' in response.body


@pytest.mark.anyio
async def test_trakt_device_poll_requires_configuration_revision():
    from services.routes import trakt_device_poll_api

    _initialize_service_routes()
    with pytest.raises(RequestValidationError):
        await trakt_device_poll_api(_JsonRequest({
            "client_id": "client",
            "client_secret": "secret",
            "device_code": "device",
        }))


@pytest.mark.anyio
async def test_collection_rejects_string_boolean_before_storage(monkeypatch):
    from emby_collections import routes

    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(routes, "_logger_dep", lambda: _Logger())
    save_definition = Mock()
    monkeypatch.setattr(routes, "save_collection_definition", save_definition)

    with pytest.raises(RequestValidationError) as raised:
        await routes.api_emby_collections_save(
            _JsonRequest(
                {
                    "name": "Film",
                    "source_type": "trakt",
                    "source_value": "popular",
                    "server_ids": ["server-1"],
                    "enabled": "false",
                }
            ),
            user={"username": "admin"},
        )

    assert raised.value.errors()[0]["loc"] == ("body", "enabled")
    save_definition.assert_not_called()


@pytest.mark.anyio
async def test_collection_preserves_valid_false_boolean(monkeypatch):
    from emby_collections import routes

    class _Logger:
        def info(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(routes, "_logger_dep", lambda: _Logger())
    save_definition = Mock(return_value={"id": "collection-1"})
    monkeypatch.setattr(routes, "save_collection_definition", save_definition)
    monkeypatch.setattr(routes, "publish_application_event", lambda *_args, **_kwargs: None)

    response = await routes.api_emby_collections_save(
        _JsonRequest(
            {
                "name": "Film",
                "source_type": "trakt",
                "source_value": "popular",
                "server_ids": ["server-1"],
                "enabled": False,
            }
        ),
        user={"username": "admin"},
    )

    assert response["success"] is True
    assert save_definition.call_args.args[0]["enabled"] is False
