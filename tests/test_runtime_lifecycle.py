import asyncio

import pytest


@pytest.mark.anyio
async def test_application_lifespan_owns_startup_and_shutdown(monkeypatch):
    from runtime import app_setup, health

    calls = []

    monkeypatch.setenv("PASSWORD_SECRET", "test-password-secret-that-is-long-enough")
    monkeypatch.setattr(app_setup, "load_config_env_file", lambda: None)
    monkeypatch.setattr(app_setup, "password_cipher_from_environment", lambda _env: None)
    monkeypatch.setattr(app_setup, "init_template_helpers", lambda _templates: None)
    monkeypatch.setattr(app_setup, "register_routes", lambda *_args: None)
    monkeypatch.setattr(app_setup, "init_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(app_setup, "init_auth", lambda **_kwargs: calls.append("auth"))
    storage = object()
    monkeypatch.setattr(app_setup, "load_config", lambda: ({"DATABASE": {}}, True))
    monkeypatch.setattr(app_setup, "_ensure_db_backend", lambda: storage)

    async def register_loop(received_storage):
        assert received_storage is storage
        calls.append("loop")

    async def shutdown():
        calls.append("shutdown")
        return True

    monkeypatch.setattr(app_setup, "register_runtime_event_loop", register_loop)
    monkeypatch.setattr(
        app_setup,
        "initialize_runtime_services",
        lambda **kwargs: calls.append(("services", kwargs)),
    )
    monkeypatch.setattr(app_setup, "shutdown_runtime_services", shutdown)

    app = app_setup.create_app()

    assert calls == []
    assert app.router.on_startup == []
    assert app.router.on_shutdown == []
    assert health.runtime_started() is False
    async with app.router.lifespan_context(app):
        assert calls == [
            "scheduler",
            "auth",
            "loop",
            (
                "services",
                {"config": {"DATABASE": {}}, "is_valid": True, "db_storage": storage},
            ),
        ]
        assert health.runtime_started() is True

    assert calls[-1] == "shutdown"
    assert health.runtime_started() is False


@pytest.mark.anyio
async def test_application_lifespan_runs_shutdown_after_startup_failure(monkeypatch):
    from runtime import app_setup, health

    shutdown_calls = []
    monkeypatch.setattr(app_setup, "init_scheduler", lambda: None)
    monkeypatch.setattr(app_setup, "init_auth", lambda **_kwargs: None)
    monkeypatch.setattr(app_setup, "load_config", lambda: ({"DATABASE": {}}, True))
    monkeypatch.setattr(app_setup, "_ensure_db_backend", lambda: object())
    monkeypatch.setattr(app_setup, "register_runtime_event_loop", _async_noop)
    monkeypatch.setattr(
        app_setup,
        "initialize_runtime_services",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )

    async def shutdown():
        shutdown_calls.append(True)
        return True

    monkeypatch.setattr(app_setup, "shutdown_runtime_services", shutdown)

    with pytest.raises(RuntimeError, match="startup failed"):
        async with app_setup._application_lifespan(object()):
            pass

    assert shutdown_calls == [True]
    assert health.runtime_started() is False


@pytest.mark.anyio
async def test_runtime_shutdown_waits_for_all_steps_before_closing_database(monkeypatch):
    import app_state
    from app_state import (
        get_app_event_loop,
        get_connection_check_state,
        register_app_event_loop,
        set_connection_check_state,
    )
    from core import auth, config_manager
    from runtime import bootstrap

    calls = []

    def threaded_stop(timeout_seconds):
        calls.append(("threaded", timeout_seconds))
        return True

    async def async_stop():
        await asyncio.sleep(0)
        calls.append(("async",))

    monkeypatch.setattr(
        bootstrap,
        "_threaded_shutdown_steps",
        lambda: (("threaded", threaded_stop),),
    )
    monkeypatch.setattr(
        bootstrap,
        "_async_shutdown_steps",
        lambda: (("async", async_stop),),
    )
    monkeypatch.setattr(auth, "shutdown_auth", lambda: calls.append(("auth",)))
    monkeypatch.setattr(
        app_state,
        "shutdown_operation_tracker",
        lambda timeout_seconds: calls.append(("tracker", timeout_seconds)) or True,
    )
    monkeypatch.setattr(
        config_manager,
        "close_database_backend",
        lambda: calls.append(("database",)),
    )
    register_app_event_loop(asyncio.get_running_loop())
    set_connection_check_state({"jellyseerr": {"ok": True}}, "2026-08-31T10:00:00Z")

    assert await bootstrap.shutdown_runtime_services(timeout_seconds=0.5) is True

    assert ("threaded", 0.5) in calls
    assert ("async",) in calls
    assert calls[-3:] == [("tracker", 0.5), ("auth",), ("database",)]
    assert get_app_event_loop() is None
    assert get_connection_check_state() == {"checked_at": None, "statuses": {}}


async def _async_noop(*_args, **_kwargs):
    return None
