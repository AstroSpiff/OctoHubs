from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest


def test_latest_reservation_is_part_of_shutdown_drain(monkeypatch):
    import emby_latest
    import emby_latest.api_handlers as latest
    import emby_latest.operations as operations

    entered = threading.Event()
    release = threading.Event()
    outcome = []

    class Manager:
        def is_refreshing(self):
            return False

    class Tracker:
        def fail(self, *_args, **_kwargs):
            return None

    def reserve_then_block(**_kwargs):
        entered.set()
        assert release.wait(2)
        return Tracker(), "operation"

    with latest._latest_refresh_lifecycle_lock:
        latest._latest_refresh_request_reserved = False
        latest._latest_refresh_thread = None
        latest._latest_refresh_stop_event = None
        latest._latest_refresh_accepting = True
    monkeypatch.setattr(emby_latest, "get_manager", lambda: Manager())
    monkeypatch.setattr(operations, "start_latest_refresh_operation", reserve_then_block)

    request = threading.Thread(
        target=lambda: outcome.append(latest.build_latest_refresh_payload(10, 2, False))
    )
    request.start()
    assert entered.wait(1)
    assert latest.shutdown_latest_refresh(0.02) is False
    with pytest.raises(RuntimeError, match="non certamente drenato"):
        latest.start_accepting_latest_refresh()

    release.set()
    request.join(1)
    assert outcome[0][1] == 409
    assert latest.shutdown_latest_refresh(1) is True
    latest.start_accepting_latest_refresh()


def test_latest_operation_start_failure_releases_reservation(monkeypatch):
    import emby_latest
    import emby_latest.api_handlers as latest
    import emby_latest.operations as operations

    class Manager:
        def is_refreshing(self):
            return False

    latest.shutdown_latest_refresh(1)
    latest.start_accepting_latest_refresh()
    monkeypatch.setattr(emby_latest, "get_manager", lambda: Manager())
    monkeypatch.setattr(
        operations,
        "start_latest_refresh_operation",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("tracker failed")),
    )
    with pytest.raises(RuntimeError, match="tracker failed"):
        latest.build_latest_refresh_payload(10, 2, False)
    assert latest._latest_refresh_request_reserved is False
    assert latest.shutdown_latest_refresh(0) is True
    latest.start_accepting_latest_refresh()


def test_scan_cannot_reopen_after_partial_drain():
    from core.tasks import ScanManager

    entered = threading.Event()
    release = threading.Event()
    manager = ScanManager()

    def blocked(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)

    assert manager.start_scan({}, process_requests_func=blocked) is True
    assert entered.wait(1)
    manager.begin_shutdown()
    assert manager.wait(0.02) is False
    with pytest.raises(RuntimeError, match="non certamente drenato"):
        manager.start_accepting()
    release.set()
    assert manager.wait(1) is True
    manager.start_accepting()
    assert manager.start_scan({}, process_requests_func=lambda *_args, **_kwargs: None) is True
    assert manager.wait(1) is True


def test_sessions_timeout_retains_owner_and_fences_late_cache_and_broadcast(monkeypatch):
    from emby_runtime.streams import EmbyStreamsManager
    from realtime import manager

    entered = threading.Event()
    release = threading.Event()
    broadcasts = []
    streams = EmbyStreamsManager()

    monkeypatch.setattr("core.emby_servers._get_emby_server_by_id", lambda _sid: {"id": "green"})

    def fetch(_server):
        entered.set()
        assert release.wait(2)
        return [{"Id": "late"}], None

    monkeypatch.setattr("emby_runtime.api_clients._fetch_emby_active_sessions", fetch)
    monkeypatch.setattr("emby_runtime.streams.get_streams_manager", lambda: streams)
    monkeypatch.setattr(manager, "_broadcast_sse_event", broadcasts.append)
    monkeypatch.setattr(manager, "_sessions_dispatcher", None)
    monkeypatch.setattr(manager, "_sessions_dispatcher_accepting", False)

    manager.initialize_session_refresh_dispatcher()
    assert manager._schedule_sessions_update("green", {}) is True
    assert entered.wait(1)
    assert manager.shutdown_session_refresh_dispatcher(0.02) is False
    with pytest.raises(RuntimeError, match="non certamente drenato"):
        manager.initialize_session_refresh_dispatcher()
    release.set()
    assert manager.shutdown_session_refresh_dispatcher(1) is True
    assert streams.get_streams("green") == []
    assert broadcasts == []
    manager.initialize_session_refresh_dispatcher()
    assert manager.shutdown_session_refresh_dispatcher(1) is True


def test_emby_websocket_close_timeout_retains_retryable_owner():
    from emby_runtime.websocket_manager import EmbyWebSocketConnection, EmbyWebSocketManager

    entered = threading.Event()
    release = threading.Event()

    class BlockingSocket:
        def send(self, _payload):
            return None

        def close(self):
            entered.set()
            assert release.wait(2)

    connection = EmbyWebSocketConnection("green", "http://green", "key", lambda *_: None)
    connection.ws = BlockingSocket()
    manager = EmbyWebSocketManager()
    manager.connections["green"] = connection

    started = time.monotonic()
    assert manager.stop_all(0.02) is False
    assert time.monotonic() - started < 0.2
    assert entered.is_set()
    assert manager.get_connection("green") is connection
    with pytest.raises(RuntimeError, match="non certamente drenati"):
        manager.start_accepting()

    release.set()
    assert manager.stop_all(1) is True
    assert manager.connections == {}
    manager.start_accepting()


def test_emby_websocket_close_failure_retains_owner_until_retry():
    from emby_runtime.websocket_manager import EmbyWebSocketConnection, EmbyWebSocketManager

    class FlakySocket:
        def __init__(self):
            self.close_calls = 0

        def send(self, _payload):
            return None

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("close failed")

    connection = EmbyWebSocketConnection("green", "http://green", "key", lambda *_: None)
    connection.ws = FlakySocket()
    manager = EmbyWebSocketManager()
    manager.connections["green"] = connection

    assert manager.remove_server("green", 1) is False
    assert manager.get_connection("green") is connection
    assert manager.remove_server("green", 1) is True
    assert manager.get_connection("green") is None


@pytest.mark.anyio
async def test_event_bridge_delivery_guard_preserves_commit_delivery_order():
    from emby_runtime.event_bridge_configuration import event_bridge_settings_delivery_guard

    first_pushing = asyncio.Event()
    release_first = asyncio.Event()
    timeline = []

    async def update(name: str, block: bool = False):
        async with event_bridge_settings_delivery_guard(["green"]):
            timeline.append(f"commit-{name}")
            if block:
                first_pushing.set()
                await release_first.wait()
            timeline.append(f"push-{name}")

    first = asyncio.create_task(update("first", True))
    await first_pushing.wait()
    second = asyncio.create_task(update("second"))
    await asyncio.sleep(0)
    assert timeline == ["commit-first"]
    release_first.set()
    await asyncio.gather(first, second)
    assert timeline == ["commit-first", "push-first", "commit-second", "push-second"]


@pytest.mark.anyio
async def test_event_bridge_websocket_pushes_are_serial_per_server():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    payloads = []

    class Socket:
        async def send_json(self, payload):
            payloads.append(payload)
            if len(payloads) == 1:
                first_entered.set()
                await release_first.wait()

        async def close(self, code=1000):
            return None

    manager = EventBridgeConnectionManager()
    await manager.register(Socket(), {"serverId": "green"})
    first = asyncio.create_task(manager.push_configuration("green", {"ENABLED": False}))
    await first_entered.wait()
    second = asyncio.create_task(manager.push_configuration("green", {"ENABLED": True}))
    await asyncio.sleep(0)
    assert len(payloads) == 1
    release_first.set()
    assert await asyncio.gather(first, second) == [1, 1]
    assert [payload["settings"]["enabled"] for payload in payloads] == [False, True]
    first_id, second_id = (payload["id"] for payload in payloads)
    websocket = manager._servers["green"].websocket
    assert manager.record_config_ack(websocket, {"id": first_id, "ok": True}) is None
    assert manager._servers["green"].last_config_ack_status == "pending"
    assert manager.record_config_ack(websocket, {"id": second_id, "ok": True}) is not None
    assert manager._servers["green"].last_config_ack_status == "applied"
    await manager.shutdown()


@pytest.mark.anyio
async def test_event_bridge_delivery_guard_releases_after_failure_and_avoids_multiserver_deadlock():
    from emby_runtime.event_bridge_configuration import event_bridge_settings_delivery_guard

    entered = []

    async def failing_update():
        with pytest.raises(RuntimeError, match="push failed"):
            async with event_bridge_settings_delivery_guard(["blue", "green"]):
                entered.append("failed")
                raise RuntimeError("push failed")

    async def retry_update(server_ids):
        async with event_bridge_settings_delivery_guard(server_ids):
            entered.append("retry")

    await failing_update()
    await asyncio.wait_for(
        asyncio.gather(
            retry_update(["green", "blue"]),
            retry_update(["blue", "green"]),
        ),
        timeout=1,
    )
    assert entered == ["failed", "retry", "retry"]


@pytest.mark.anyio
async def test_disjoint_event_bridge_puts_push_only_their_submitted_server(monkeypatch):
    from emby_runtime import event_bridge_configuration
    from web import event_bridge_api_routes

    config = {
        "EMBY": {
            "SERVERS": [
                {"id": "green", "url": "https://green.example"},
                {"id": "blue", "url": "https://blue.example"},
            ],
        },
        "EVENT_BRIDGE": {"SERVERS": {}},
    }
    http_targets = []
    websocket_targets = []

    class Manager:
        def status(self):
            return {
                "servers": [
                    {"server_id": "green", "connected": True},
                    {"server_id": "blue", "connected": True},
                ],
            }

        def record_plugin_configuration_response(self, _server_id, _response):
            return None

        async def push_configuration(self, server_id, _settings):
            websocket_targets.append(server_id)
            return 1

    def save_settings(submitted):
        return {"SERVERS": dict(submitted)}

    def push_http(_server, server_id, _settings):
        http_targets.append(server_id)
        if server_id == "green":
            return True, "", {"Ok": True}
        return False, "offline", None

    monkeypatch.setattr(event_bridge_api_routes, "_save_event_bridge_settings", save_settings)
    monkeypatch.setattr(event_bridge_configuration, "get_event_bridge_manager", lambda: Manager())
    monkeypatch.setattr(event_bridge_configuration, "push_event_bridge_settings_to_plugin", push_http)
    event_bridge_api_routes.init_event_bridge_api_routes(
        require_auth=lambda _request: {"username": "admin"},
        validate_csrf=lambda _request, token: token == "csrf",
        load_config_func=lambda: (config, True),
    )

    def request_for(server_id):
        async def json_payload():
            return {"servers": {server_id: {"ENABLED": True}}}

        return SimpleNamespace(headers={"X-CSRF-Token": "csrf"}, json=json_payload)

    responses = await asyncio.gather(
        event_bridge_api_routes.update_event_bridge_settings_api_route(request_for("green")),
        event_bridge_api_routes.update_event_bridge_settings_api_route(request_for("blue")),
    )

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(http_targets) == ["blue", "green"]
    assert websocket_targets == ["blue"]


@pytest.mark.anyio
async def test_server_update_reports_stopping_socket_then_reaps_it_on_retry(monkeypatch):
    from fastapi import HTTPException, Request
    from emby_runtime import server_routes, websocket_manager
    from emby_runtime.server_api_models import EmbyServerInput

    released = threading.Event()
    created = []

    class Connection:
        def __init__(self, server_id, server_url, api_key, event_callback):
            self.server_id = server_id
            self.server_url = server_url.rstrip("/")
            self.api_key = api_key
            self.event_callback = event_callback
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def wait_stopped(self, _timeout):
            return released.is_set()

    monkeypatch.setattr(websocket_manager, "EmbyWebSocketConnection", Connection)
    manager = websocket_manager.EmbyWebSocketManager()
    old = Connection("green", "http://old", "old-key", lambda *_args: None)
    old.start()
    manager.connections["green"] = old
    monkeypatch.setattr(server_routes, "get_websocket_manager", lambda: manager)
    monkeypatch.setattr(server_routes, "_require_auth", lambda _request: None)
    monkeypatch.setattr(server_routes, "_validate_json_csrf", lambda _request: None)
    monkeypatch.setattr(server_routes, "_require_valid_configuration", lambda: None)
    existing = {
        "id": "green",
        "name": "Green",
        "original_name": "Green",
        "alias": "Green",
        "url": "http://old",
        "api_key": "old-key",
        "enabled": True,
        "notes": "",
        "icon": "fa-server",
        "icon_color": "#3b82f6",
        "icon_style": "solid",
    }
    monkeypatch.setattr(server_routes, "_load_stored_servers", lambda: [existing])

    def save(_values, _server_id):
        updated = {**existing, "url": "http://new", "api_key": "new-key"}
        server_routes._sync_server_websocket(updated)
        return updated, False

    monkeypatch.setattr(server_routes, "_save_server_values", save)
    request = Request({"type": "http", "method": "PUT", "path": "/", "headers": []})
    payload = EmbyServerInput(url="http://new", api_key="new-key")

    with pytest.raises(HTTPException) as busy:
        await server_routes.update_emby_server_api("green", request, payload)
    assert busy.value.status_code == 409
    assert manager.get_connection("green") is old

    released.set()
    response = await server_routes.update_emby_server_api("green", request, payload)
    assert response.status_code == 200
    replacement = manager.get_connection("green")
    assert replacement is not None and replacement is not old
    assert replacement.server_url == "http://new"
    assert replacement.api_key == "new-key"


def test_websocket_close_callback_does_not_deadlock_manager_fence(monkeypatch):
    from emby_runtime import websocket_manager

    completed = threading.Event()
    delivered = []

    class CallbackOnStop:
        def __init__(self, server_id, server_url, api_key, event_callback):
            self.server_id = server_id
            self.server_url = server_url
            self.api_key = api_key
            self.event_callback = event_callback
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True
            self.event_callback(
                self.server_id,
                {"MessageType": "ConnectionClosed", "Data": {}},
            )

        def wait_stopped(self, _timeout):
            return self.stopped

    monkeypatch.setattr(websocket_manager, "EmbyWebSocketConnection", CallbackOnStop)
    manager = websocket_manager.EmbyWebSocketManager()
    manager.set_global_callback(lambda *_args: delivered.append(True))
    assert manager.upsert_server("green", "http://green", "key") is True

    remover = threading.Thread(
        target=lambda: (manager.remove_server("green", 0.2), completed.set()),
        daemon=True,
    )
    remover.start()
    assert completed.wait(0.5)
    remover.join(0.5)
    assert delivered == []
    assert manager.get_connection("green") is None


@pytest.mark.anyio
async def test_server_quiesce_fails_closed_when_websocket_stop_raises(monkeypatch):
    from fastapi import HTTPException
    from emby_runtime import server_routes

    class Jobs:
        def has_active_jobs(self):
            return False

    class WebSockets:
        def remove_server(self, *_args):
            raise RuntimeError("close failed")

    monkeypatch.setattr("services.background_job_registry.background_job_registry", Jobs())
    monkeypatch.setattr(server_routes, "get_websocket_manager", lambda: WebSockets())

    with pytest.raises(HTTPException) as stopped:
        await server_routes._quiesce_server("green")
    assert stopped.value.status_code == 409


@pytest.mark.anyio
async def test_event_bridge_immediate_ack_observes_published_message_owner():
    from emby_runtime.event_bridge_manager import EventBridgeConnectionManager

    manager = EventBridgeConnectionManager()

    class ImmediateAckSocket:
        async def send_json(self, payload):
            assert manager.record_config_ack(
                self,
                {"id": payload["id"], "ok": True, "applied": True},
            ) is not None

        async def close(self, code=1000):
            return None

    websocket = ImmediateAckSocket()
    await manager.register(websocket, {"serverId": "green"})
    assert await manager.push_configuration("green", {"ENABLED": True}) == 1
    state = manager._servers["green"]
    assert state.last_config_ack_status == "applied"
    assert state.last_config_ack_message_id == state.last_config_message_id
    await manager.shutdown()


def test_runtime_busy_compensation_restores_exact_server_configuration(monkeypatch):
    from emby_runtime import server_routes

    previous = {"id": "green", "url": "http://old", "api_key": "old-key"}
    blue = {"id": "blue", "url": "http://blue", "api_key": "blue-key"}
    state = {
        "SERVERS": [
            {"id": "green", "url": "http://new", "api_key": "new-key"},
            blue,
        ],
    }
    reloads = []

    def mutate(updater):
        state.clear()
        state.update(updater({
            "SERVERS": [
                {"id": "green", "url": "http://new", "api_key": "new-key"},
                blue,
            ],
        }))
        return state

    monkeypatch.setattr(server_routes, "_mutate_emby_settings_in_db", mutate)
    monkeypatch.setattr(server_routes, "_load_config", lambda: (reloads.append(True) or {}, True))
    monkeypatch.setattr(server_routes, "_invalidate_server_status_cache", lambda: None)

    server_routes._restore_server_configuration_after_runtime_busy(
        server_routes._ServerConfigurationRollback(
            server_id="green",
            created=False,
            previous_server=previous,
            previous_index=0,
        ),
    )

    assert state["SERVERS"] == [previous, blue]
    assert reloads == [True]


def test_save_guard_compensates_before_propagating_runtime_busy(monkeypatch):
    from emby_runtime import server_routes

    previous = {"id": "green", "url": "http://old", "api_key": "old-key"}
    updated = {"id": "green", "url": "http://new", "api_key": "new-key"}
    compensated = []
    monkeypatch.setattr(server_routes, "_load_stored_servers", lambda: [previous])
    monkeypatch.setattr(server_routes, "_build_emby_server_from_form", lambda *_args: dict(updated))
    monkeypatch.setattr(server_routes, "_refresh_emby_server_identity", lambda _server: None)
    rollback = server_routes._ServerConfigurationRollback(
        server_id="green",
        created=False,
        previous_server=previous,
        previous_index=0,
    )
    monkeypatch.setattr(server_routes, "_persist_emby_server", lambda *_args: (dict(updated), rollback))
    monkeypatch.setattr(
        server_routes,
        "_refresh_saved_server_runtime",
        lambda _server: (_ for _ in ()).throw(
            server_routes.EmbyServerLifecycleBusyError("busy")
        ),
    )
    monkeypatch.setattr(
        server_routes,
        "_restore_server_configuration_after_runtime_busy",
        compensated.append,
    )

    with pytest.raises(server_routes.EmbyServerLifecycleBusyError, match="busy"):
        server_routes._save_server_values_guarded({}, "green")
    assert compensated == [rollback]


@pytest.mark.parametrize("idempotent_post", [True, False])
def test_post_runtime_busy_uses_exact_persistence_rollback_token(monkeypatch, idempotent_post):
    from emby_runtime import server_routes

    blue = {"id": "blue", "url": "http://blue", "api_key": "blue-key"}
    historical = {
        "id": "historic-green",
        "url": "http://green",
        "api_key": "historic-key",
        "alias": "Historic",
    }
    red = {"id": "red", "url": "http://red", "api_key": "red-key"}
    original = [blue, historical, red] if idempotent_post else [blue, red]
    state = {"SERVERS": [dict(server) for server in original]}
    updated = {
        "id": "generated-green",
        "url": "http://green" if idempotent_post else "http://new-green",
        "api_key": "new-key",
        "alias": "Submitted",
    }

    def mutate(updater):
        result = updater({"SERVERS": [dict(server) for server in state["SERVERS"]]})
        state.clear()
        state.update(result)
        return state

    monkeypatch.setattr(server_routes, "_load_stored_servers", lambda: [dict(server) for server in state["SERVERS"]])
    monkeypatch.setattr(server_routes, "_build_emby_server_from_form", lambda *_args: dict(updated))
    monkeypatch.setattr(server_routes, "_refresh_emby_server_identity", lambda _server: None)
    monkeypatch.setattr(server_routes, "_mutate_emby_settings_in_db", mutate)
    monkeypatch.setattr(
        server_routes,
        "_refresh_saved_server_runtime",
        lambda _server: (_ for _ in ()).throw(
            server_routes.EmbyServerLifecycleBusyError("busy")
        ),
    )
    monkeypatch.setattr(server_routes, "_load_config", lambda: ({}, True))
    monkeypatch.setattr(server_routes, "_invalidate_server_status_cache", lambda: None)

    with pytest.raises(server_routes.EmbyServerLifecycleBusyError, match="busy"):
        server_routes._save_server_values_guarded({}, None)

    assert state["SERVERS"] == original
