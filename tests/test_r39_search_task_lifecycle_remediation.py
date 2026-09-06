"""Deterministic lifecycle canaries for the R39 search task remediation."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _SearchWebSocket:
    headers: dict[str, str] = {}
    scope: dict[str, str] = {}

    def __init__(self) -> None:
        self.accepted = False
        self.closed: list[int] = []
        self.messages: list[object] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: object) -> None:
        self.messages.append(payload)

    async def close(self, *, code: int = 1000) -> None:
        self.closed.append(code)


def _search_payload() -> SimpleNamespace:
    return SimpleNamespace(
        query_variants=["example"],
        search_types=["movie"],
        indexers=["prowlarr"],
        use_jellyseerr_logic=False,
        use_custom_rules=False,
        tmdb_id=None,
        custom_rules=None,
        seasons=[],
    )


def _live_search_children(session_id: str) -> list[asyncio.Task[Any]]:
    prefix = f"search:{session_id}:"
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith(prefix) and not task.done()
    ]


def _prepare_search_handler(monkeypatch, *, finished: list[tuple[str, int]]) -> None:
    from core import config_manager
    from search import websocket as search_websocket

    async def receive(_websocket):
        return _search_payload()

    monkeypatch.setattr(search_websocket, "claim_search_session", lambda *_args: None)
    monkeypatch.setattr(
        search_websocket,
        "finish_search_session",
        lambda session_id, owner_id: finished.append((session_id, owner_id)),
    )
    monkeypatch.setattr(search_websocket, "receive_search_start", receive)
    monkeypatch.setattr(config_manager, "load_config", lambda: ({"configured": True}, True))


@pytest.mark.anyio
async def test_task_drain_survives_repeated_parent_cancellation() -> None:
    from core.async_lifecycle import cancel_and_drain_tasks

    child_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    children: list[asyncio.Task[None]] = []

    async def child() -> None:
        child_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await release_cleanup.wait()
            raise

    async def owner() -> None:
        owned = asyncio.create_task(child())
        children.append(owned)
        try:
            await asyncio.Event().wait()
        finally:
            await cancel_and_drain_tasks(owned)

    owner_task = asyncio.create_task(owner())
    await asyncio.wait_for(child_started.wait(), 0.5)

    owner_task.cancel()
    await asyncio.wait_for(cleanup_started.wait(), 0.5)
    owner_task.cancel()
    await asyncio.sleep(0)
    assert not owner_task.done()

    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(owner_task, 0.5)

    assert children and all(task.done() for task in children)


@pytest.mark.anyio
async def test_search_handler_cancellation_drains_work_and_authorization_tasks(monkeypatch) -> None:
    from search import streaming, websocket as search_websocket

    session_id = "cancel-parent"
    finished: list[tuple[str, int]] = []
    search_started = asyncio.Event()
    search_cancelled = asyncio.Event()
    authorization_entered = asyncio.Event()
    authorization_cancelled = asyncio.Event()
    _prepare_search_handler(monkeypatch, finished=finished)
    monkeypatch.setattr(search_websocket, "SEARCH_AUTHORIZATION_RECHECK_SECONDS", 0)

    async def search(**_kwargs):
        search_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            search_cancelled.set()

    authorization_calls = 0

    async def authorize(_websocket):
        nonlocal authorization_calls
        authorization_calls += 1
        if authorization_calls == 1:
            return 42
        authorization_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            authorization_cancelled.set()

    monkeypatch.setattr(streaming, "search_streaming_parallel", search)
    handler = asyncio.create_task(
        search_websocket.handle_search_websocket(_SearchWebSocket(), session_id, authorize)
    )
    await asyncio.wait_for(search_started.wait(), 0.5)
    await asyncio.wait_for(authorization_entered.wait(), 0.5)
    assert len(_live_search_children(session_id)) == 2

    handler.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handler

    assert search_cancelled.is_set()
    assert authorization_cancelled.is_set()
    assert _live_search_children(session_id) == []
    assert finished == [(session_id, 42)]


@pytest.mark.anyio
async def test_search_handler_repeated_cancellation_finishes_claim_after_child_cleanup(
    monkeypatch,
) -> None:
    from search import streaming, websocket as search_websocket

    session_id = "cancel-parent-twice"
    claims: list[tuple[str, int]] = []
    finished: list[tuple[str, int]] = []
    search_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    websocket = _SearchWebSocket()
    _prepare_search_handler(monkeypatch, finished=finished)
    monkeypatch.setattr(
        search_websocket,
        "claim_search_session",
        lambda claimed_session_id, owner_id: claims.append((claimed_session_id, owner_id)),
    )

    async def search(**_kwargs):
        search_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await release_cleanup.wait()
            raise

    async def authorize(_websocket):
        return 42

    monkeypatch.setattr(streaming, "search_streaming_parallel", search)
    handler = asyncio.create_task(
        search_websocket.handle_search_websocket(websocket, session_id, authorize)
    )
    await asyncio.wait_for(search_started.wait(), 0.5)

    handler.cancel()
    await asyncio.wait_for(cleanup_started.wait(), 0.5)
    handler.cancel()
    await asyncio.sleep(0)
    assert not handler.done()

    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(handler, 0.5)

    assert _live_search_children(session_id) == []
    assert claims == [(session_id, 42)]
    assert finished == [(session_id, 42)]
    assert websocket.closed == [1000]


@pytest.mark.anyio
async def test_streaming_fanout_repeated_cancellation_drains_child_cleanup(monkeypatch) -> None:
    from starlette.websockets import WebSocketState

    from search import outbound_execution
    from search.streaming import search_streaming_parallel

    child_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    children: list[asyncio.Task[Any]] = []

    class WebSocket:
        client_state = WebSocketState.CONNECTED

        async def send_json(self, _message):
            return None

    async def run_outbound_search(*_args, **_kwargs):
        current = asyncio.current_task()
        assert current is not None
        children.append(current)
        child_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await release_cleanup.wait()
            raise

    monkeypatch.setattr("search.indexers._prowlarr_configured", lambda _config: True)
    monkeypatch.setattr(
        "emby_runtime.api_clients.search_prowlarr",
        lambda *_args: [],
    )
    monkeypatch.setattr(outbound_execution, "run_outbound_search", run_outbound_search)

    stream = asyncio.create_task(
        search_streaming_parallel(
            ["query"],
            ["movie"],
            {"prowlarr"},
            {"PROWLARR_URL": "https://indexer", "PROWLARR_API_KEY": "key"},
            WebSocket(),
            "stream-cancel-twice",
            42,
        )
    )
    await asyncio.wait_for(child_started.wait(), 0.5)

    stream.cancel()
    await asyncio.wait_for(cleanup_started.wait(), 0.5)
    stream.cancel()
    await asyncio.sleep(0)
    assert not stream.done()

    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stream, 0.5)

    assert children and all(child.done() for child in children)


@pytest.mark.anyio
async def test_search_authorization_error_drains_blocked_search(monkeypatch) -> None:
    from search import streaming, websocket as search_websocket

    session_id = "auth-error"
    finished: list[tuple[str, int]] = []
    search_cancelled = asyncio.Event()
    _prepare_search_handler(monkeypatch, finished=finished)
    monkeypatch.setattr(search_websocket, "SEARCH_AUTHORIZATION_RECHECK_SECONDS", 0)

    async def search(**_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            search_cancelled.set()

    calls = 0

    async def authorize(_websocket):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 42
        raise RuntimeError("revalidation failed")

    monkeypatch.setattr(streaming, "search_streaming_parallel", search)
    await asyncio.wait_for(
        search_websocket.handle_search_websocket(_SearchWebSocket(), session_id, authorize),
        0.5,
    )

    assert search_cancelled.is_set()
    assert _live_search_children(session_id) == []
    assert finished == [(session_id, 42)]


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["complete", "timeout", "disconnect"])
async def test_search_terminal_paths_leave_no_child_tasks(monkeypatch, outcome: str) -> None:
    from search import streaming, websocket as search_websocket
    from search.stream_limits import SearchClientDisconnected

    session_id = f"terminal-{outcome}"
    finished: list[tuple[str, int]] = []
    _prepare_search_handler(monkeypatch, finished=finished)

    async def search(**_kwargs):
        if outcome == "timeout":
            await asyncio.Event().wait()
        if outcome == "disconnect":
            raise SearchClientDisconnected
        return {"status": "complete"}

    async def authorize(_websocket):
        return 42

    monkeypatch.setattr(streaming, "search_streaming_parallel", search)
    if outcome == "timeout":
        monkeypatch.setattr(search_websocket, "SEARCH_STREAM_TIMEOUT_SECONDS", 0.01)

    await asyncio.wait_for(
        search_websocket.handle_search_websocket(_SearchWebSocket(), session_id, authorize),
        0.5,
    )

    assert _live_search_children(session_id) == []
    assert finished == [(session_id, 42)]


def _created_task_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return None
    target = node.targets[0]
    value = node.value
    call = value.elt if isinstance(value, ast.ListComp) else value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr != "create_task" or not isinstance(target, ast.Name):
        return None
    return target.id


def _created_task_names(function: ast.AsyncFunctionDef) -> set[str]:
    return {
        task_name
        for node in ast.walk(function)
        if (task_name := _created_task_name(node)) is not None
    }


def _cleanup_nodes(function: ast.AsyncFunctionDef):
    for try_node in ast.walk(function):
        if isinstance(try_node, ast.Try):
            for root in (*try_node.handlers, *try_node.finalbody):
                yield from ast.walk(root)


def _drained_task_names(function: ast.AsyncFunctionDef) -> set[str]:
    drained: set[str] = set()
    for node in _cleanup_nodes(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "cancel_and_drain_tasks":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Name):
                drained.add(argument.id)
            elif isinstance(argument, ast.Starred) and isinstance(argument.value, ast.Name):
                drained.add(argument.value.id)
    return drained


def _request_task_ownership_violations(tree: ast.AST) -> list[str]:
    violations: list[str] = []
    functions = (
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
    )
    for function in functions:
        argument_names = {argument.arg for argument in function.args.args}
        if argument_names.isdisjoint({"request", "websocket"}):
            continue
        created = _created_task_names(function)
        drained = _drained_task_names(function)
        violations.extend(
            f"{function.name}:{missing}" for missing in sorted(created - drained)
        )
    return violations


def test_request_and_websocket_created_tasks_have_a_canonical_drain_gate() -> None:
    violations: list[str] = []
    ignored = {"tests", "venv", ".venv", "node_modules"}
    for path in PROJECT_ROOT.rglob("*.py"):
        relative = path.relative_to(PROJECT_ROOT)
        if any(part in ignored for part in relative.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        violations.extend(
            f"{relative}:{violation}"
            for violation in _request_task_ownership_violations(tree)
        )
    assert violations == []


def test_request_task_drain_gate_detects_an_unowned_child() -> None:
    tree = ast.parse(
        "import asyncio\n"
        "async def handler(websocket):\n"
        "    child = asyncio.create_task(websocket.receive())\n"
        "    await child\n"
    )
    assert _request_task_ownership_violations(tree) == ["handler:child"]

    normal_path_only = ast.parse(
        "import asyncio\n"
        "async def handler(request):\n"
        "    child = asyncio.create_task(request.receive())\n"
        "    await cancel_and_drain_tasks(child)\n"
    )
    assert _request_task_ownership_violations(normal_path_only) == ["handler:child"]
