import json

import pytest


def test_telegram_snapshot_hides_bot_tokens(monkeypatch):
    from telegram import api_routes

    api_routes.init_telegram_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, _token: True,
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )
    monkeypatch.setattr(
        api_routes,
        "_load_telegram_settings",
        lambda: {
            "BOTS": [{"id": "bot-1", "alias": "Notifiche", "token": "super-secret"}],
            "GROUPS": [],
            "CHANNELS": [],
            "PRESETS": [],
        },
    )

    payload = api_routes._telegram_snapshot()

    assert payload["ready"] is True
    assert payload["bots"] == [
        {
            "id": "bot-1",
            "alias": "Notifiche",
            "original_name": "",
            "username": "",
            "verified": False,
            "verified_at": "",
            "last_check": "",
            "last_error": "",
            "token_configured": True,
        }
    ]
    assert "super-secret" not in json.dumps(payload)


@pytest.mark.anyio
async def test_telegram_action_runs_new_service_and_publishes_update(monkeypatch):
    from telegram import api_routes

    api_routes.init_telegram_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )
    monkeypatch.setattr(api_routes, "_telegram_snapshot", lambda: {"success": True, "bots": []})
    received = []
    published = []
    monkeypatch.setattr(api_routes, "publish_configuration_update", published.append)

    def _run(action, data):
        received.append((action, data))
        return "success", "Bot Telegram aggiornato."

    monkeypatch.setattr(api_routes, "run_telegram_configuration_action", _run)

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}
        session = {}

        async def json(self):
            return {"action": "bot.save", "data": {"id": "bot-1", "alias": "Aggiornato"}}

    response = await api_routes.telegram_action_api_route(_Request())
    payload = json.loads(response.body.decode("utf-8"))

    assert received == [("bot.save", {"id": "bot-1", "alias": "Aggiornato"})]
    assert payload["message"] == "Bot Telegram aggiornato."
    assert published == ["telegram"]


@pytest.mark.anyio
async def test_telegram_action_rejects_missing_csrf_before_running_action(monkeypatch):
    from fastapi import HTTPException
    from telegram import api_routes

    api_routes.init_telegram_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )
    called = False

    def _run(_action, _data):
        nonlocal called
        called = True
        return "success", "ok"

    monkeypatch.setattr(api_routes, "run_telegram_configuration_action", _run)

    class _Request:
        headers = {}
        session = {}

        async def json(self):
            return {"action": "bot.save", "data": {"id": "bot-1"}}

    with pytest.raises(HTTPException) as exc_info:
        await api_routes.telegram_action_api_route(_Request())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "CSRF token non valido"
    assert called is False


@pytest.mark.anyio
async def test_telegram_action_does_not_publish_when_storage_write_fails(monkeypatch):
    from fastapi import HTTPException

    from core.storage import StorageError
    from telegram import api_routes

    api_routes.init_telegram_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config=lambda: ({"DATABASE": {"ENABLED": True}}, True),
        ensure_db_backend=lambda: object(),
    )
    published = []
    monkeypatch.setattr(api_routes, "ensure_telegram_ready", lambda *_args: None)
    monkeypatch.setattr(
        api_routes,
        "run_telegram_configuration_action",
        lambda *_args: (_ for _ in ()).throw(StorageError("write failed")),
    )
    monkeypatch.setattr(api_routes, "publish_configuration_update", published.append)

    class _Request:
        headers = {"X-CSRF-Token": "csrf"}
        session = {}

        async def json(self):
            return {"action": "bot.save", "data": {"id": "bot-1"}}

    with pytest.raises(HTTPException) as exc_info:
        await api_routes.telegram_action_api_route(_Request())

    assert exc_info.value.status_code == 500
    assert published == []


def test_telegram_save_bot_reuses_existing_token_without_legacy_routes(monkeypatch):
    from telegram import actions

    settings = {
        "BOTS": [{"id": "bot-1", "alias": "Prima", "token": "saved-token"}],
        "GROUPS": [],
        "CHANNELS": [],
        "PRESETS": [],
    }
    saved = {}
    checked = []

    monkeypatch.setattr(actions, "_load_telegram_settings", lambda: settings)
    monkeypatch.setattr(actions, "_save_telegram_settings", lambda payload: saved.update(payload))

    def _check(bot):
        checked.append(bot.copy())
        return True, "Bot verificato: Demo"

    monkeypatch.setattr(actions, "_telegram_check_bot_identity", _check)

    tone, message = actions.run_telegram_configuration_action(
        "bot.save",
        {"id": "bot-1", "alias": "Aggiornato"},
    )

    assert tone == "success"
    assert message == "Bot Telegram aggiornato."
    assert checked[0]["token"] == "saved-token"
    assert saved["BOTS"][0]["alias"] == "Aggiornato"
    assert saved["BOTS"][0]["token"] == "saved-token"
