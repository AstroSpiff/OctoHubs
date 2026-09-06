"""Regression canaries for the R28 security/runtime remediations."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
from typing import Any, cast

import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_scan_websocket_manager_imports_in_a_fresh_interpreter() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import emby_runtime.scan_websocket_manager"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


class _HangingWebSocket:
    headers: dict[str, str] = {}
    scope: dict[str, str] = {}

    def __init__(self) -> None:
        self.accepted = False
        self.send_cancelled = False
        self.close_cancelled = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, _payload: object) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.send_cancelled = True

    async def close(self, *, code: int = 1000) -> None:
        del code
        try:
            await asyncio.Event().wait()
        finally:
            self.close_cancelled = True


class _HangingAcceptWebSocket(_HangingWebSocket):
    async def accept(self) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.accepted = True


@pytest.mark.anyio
async def test_websocket_io_deadlines_cancel_stalled_send_and_close() -> None:
    from core.websocket_io import accept_bounded, close_bounded, send_json_bounded

    accepting = _HangingAcceptWebSocket()
    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(
            accept_bounded(accepting, timeout=0.01),
            timeout=0.2,
        )
    assert accepting.accepted is True

    websocket = _HangingWebSocket()

    with pytest.raises(WebSocketDisconnect):
        await asyncio.wait_for(
            send_json_bounded(websocket, {"type": "canary"}, timeout=0.01),
            timeout=0.2,
        )
    assert websocket.send_cancelled is True

    assert await asyncio.wait_for(
        close_bounded(websocket, code=1011, timeout=0.01),
        timeout=0.2,
    ) is False
    assert websocket.close_cancelled is True


@pytest.mark.anyio
async def test_events_socket_releases_subscription_and_lease_after_stalled_write(monkeypatch) -> None:
    from realtime import routes
    from core.websocket_io import send_json_bounded

    websocket = _HangingWebSocket()
    released: list[bool] = []
    unsubscribed: list[object] = []
    subscriber = object()

    class _Lease:
        def release(self) -> None:
            released.append(True)

    async def _fast_send(target, payload) -> None:
        await send_json_bounded(target, payload, timeout=0.01)

    routes.init_realtime_routes(lambda _connection: 7)
    monkeypatch.setattr(routes, "acquire_connection", lambda *_args: _Lease())
    monkeypatch.setattr(routes, "send_json_bounded", _fast_send)
    monkeypatch.setattr(routes.websocket_subscribers, "subscribe", lambda **_kwargs: subscriber)
    monkeypatch.setattr(routes.websocket_subscribers, "unsubscribe", unsubscribed.append)

    await asyncio.wait_for(routes.ws_events(cast(Any, websocket)), timeout=0.2)

    assert websocket.accepted is True
    assert websocket.send_cancelled is True
    assert unsubscribed == [subscriber]
    assert released == [True]


@pytest.mark.anyio
async def test_events_socket_releases_lease_when_accept_stalls(monkeypatch) -> None:
    from realtime import routes
    from core.websocket_io import accept_bounded

    websocket = _HangingAcceptWebSocket()
    released: list[bool] = []

    class _Lease:
        def release(self) -> None:
            released.append(True)

    async def _fast_accept(target) -> None:
        await accept_bounded(target, timeout=0.01)

    routes.init_realtime_routes(lambda _connection: 7)
    monkeypatch.setattr(routes, "acquire_connection", lambda *_args: _Lease())
    monkeypatch.setattr(routes, "accept_bounded", _fast_accept)

    await asyncio.wait_for(routes.ws_events(cast(Any, websocket)), timeout=0.2)

    assert websocket.accepted is True
    assert released == [True]


@pytest.mark.anyio
async def test_scan_manager_removes_registration_when_accept_is_cancelled() -> None:
    from emby_runtime.scan_websocket_manager import ScanConnectionManager

    manager = ScanConnectionManager()
    websocket = _HangingAcceptWebSocket()
    task = asyncio.create_task(manager.connect("client-a", cast(Any, websocket)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "client-a" not in manager.active_connections
    assert "client-a" not in manager._outbound_queues


@pytest.mark.anyio
async def test_scan_socket_releases_lease_when_connect_accept_fails(monkeypatch) -> None:
    from realtime import routes

    websocket = _HangingWebSocket()
    released: list[bool] = []

    class _Lease:
        def release(self) -> None:
            released.append(True)

    class _Manager:
        @staticmethod
        async def connect(_client_id, _websocket) -> bool:
            raise WebSocketDisconnect(code=1011)

    routes.init_realtime_routes(lambda _connection: 7)
    monkeypatch.setattr(routes, "acquire_connection", lambda *_args: _Lease())
    monkeypatch.setattr(routes, "get_scan_connection_manager", lambda: _Manager())

    with pytest.raises(WebSocketDisconnect):
        await routes.websocket_scan_endpoint(cast(Any, websocket), "client-a")

    assert released == [True]


@pytest.mark.anyio
async def test_search_socket_finishes_session_after_stalled_write(monkeypatch) -> None:
    from core.websocket_io import close_bounded, send_json_bounded
    from search import websocket as search_websocket

    websocket = _HangingWebSocket()
    finished: list[tuple[str, int]] = []

    async def _authorize(_websocket) -> int:
        return 42

    async def _fast_send(target, payload) -> None:
        await send_json_bounded(target, payload, timeout=0.01)

    async def _fast_close(target, *, code=1000) -> bool:
        return await close_bounded(target, code=code, timeout=0.01)

    monkeypatch.setattr(search_websocket, "claim_search_session", lambda *_args: None)
    monkeypatch.setattr(
        search_websocket,
        "finish_search_session",
        lambda session_id, owner_id: finished.append((session_id, owner_id)),
    )
    monkeypatch.setattr(search_websocket, "send_json_bounded", _fast_send)
    monkeypatch.setattr(search_websocket, "close_bounded", _fast_close)

    await asyncio.wait_for(
        search_websocket.handle_search_websocket(websocket, "session-canary", _authorize),
        timeout=0.2,
    )

    assert websocket.accepted is True
    assert websocket.send_cancelled is True
    assert websocket.close_cancelled is True
    assert finished == [("session-canary", 42)]


def test_all_browser_and_event_bridge_route_writes_use_the_bounded_io_boundary() -> None:
    for relative_path in (
        "realtime/routes.py",
        "search/websocket.py",
        "search/streaming.py",
        "emby_runtime/scan_websocket_manager.py",
        "emby_runtime/event_bridge_routes.py",
    ):
        source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "await websocket.send_json(" not in source
        assert "await websocket.close(code=" not in source
        assert "await websocket.accept()" not in source


@pytest.mark.parametrize(
    "data",
    [
        {"alias": "a" * 201},
        {"alias": "valid\nforged"},
        {"token": "t" * 513},
        {"group_ids": [f"group-{index}" for index in range(101)]},
        {"channel_ids": ["channel-1", "channel-1"]},
    ],
)
def test_telegram_action_contract_rejects_unbounded_or_ambiguous_values(data) -> None:
    from telegram.api_models import TelegramActionRequest

    with pytest.raises(ValidationError):
        TelegramActionRequest.model_validate({"action": "bot.save", "data": data})


def test_telegram_persistence_rejects_oversized_aggregate_before_storage(monkeypatch) -> None:
    from services import manager as services_manager
    from telegram import manager
    from telegram.limits import TelegramSettingsLimitError

    writes: list[dict[str, object]] = []
    monkeypatch.setattr(services_manager, "_load_app_settings_snapshot", lambda: {})
    monkeypatch.setattr(services_manager, "_save_app_settings_snapshot", writes.append)

    with pytest.raises(TelegramSettingsLimitError, match="256 KiB"):
        manager._save_telegram_settings(
            {
                "BOTS": [
                    {
                        "id": "bot-1",
                        "token": "123:token",
                        "alias": "a" * (300 * 1024),
                    }
                ]
            }
        )

    assert writes == []


def test_telegram_resource_cap_rejects_before_outbound_verification(monkeypatch) -> None:
    from telegram import actions
    from telegram.limits import MAX_TELEGRAM_RESOURCES_PER_KIND, TelegramSettingsLimitError

    settings = {
        "BOTS": [
            {"id": f"bot-{index}", "token": f"{index}:token"}
            for index in range(MAX_TELEGRAM_RESOURCES_PER_KIND)
        ],
        "GROUPS": [],
        "CHANNELS": [],
        "PRESETS": [],
    }
    checked: list[object] = []
    monkeypatch.setattr(actions, "_load_telegram_settings", lambda: settings)
    monkeypatch.setattr(actions, "_telegram_check_bot_identity", checked.append)

    with pytest.raises(TelegramSettingsLimitError, match="100 bot"):
        actions.save_bot({"alias": "new", "token": "new:token"})

    assert checked == []


def test_supported_uvicorn_commands_disable_native_proxy_header_rewriting() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    development = (PROJECT_ROOT / "start_dev.sh").read_text(encoding="utf-8")

    assert '"--no-proxy-headers"' in dockerfile
    assert "--no-proxy-headers" in development
    assert "--no-proxy-headers" in (PROJECT_ROOT / "cli.py").read_text(encoding="utf-8")
    assert "--no-proxy-headers" in (PROJECT_ROOT / "asgi.py").read_text(encoding="utf-8")
    for relative_path in ("docs/DOCKER_DEPLOY.md", "docs/DOCKER_DEPLOY_ita.md"):
        documentation = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "--no-proxy-headers" in documentation
