"""Security and resource-bound regressions for streaming searches."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from realtime.routes import init_realtime_routes, websocket_search_endpoint
from search import outbound_execution, websocket as search_websocket
from search.outbound_execution import create_search_semaphore, run_outbound_search
from search.routes import init_search_routes, start_search_stream
from search.state import (
    SearchSessionLimitError,
    SearchSessionRegistry,
    SearchSessionUnavailableError,
    create_search_session,
    search_session_registry,
)
from search.stream_limits import (
    MAX_CONCURRENT_OUTBOUND_SEARCHES,
    MAX_SEARCH_FRAME_BYTES,
    MAX_SEARCH_QUERY_LENGTH,
    MAX_SEARCH_TASKS,
    SearchClientDisconnected,
    SearchWorkloadLimitError,
)
from search.stream_protocol import SearchStreamProtocolError, receive_search_start
from search.streaming import search_streaming_parallel
from web.research_api_models import ManualSearchPayload


class _WebSocket:
    def __init__(self, messages=None, headers=None):
        self.headers = headers or {}
        self._messages = list(messages or [])
        self.accepted = False
        self.closed = False
        self.close_code = None
        self.sent = []
        self.client_state = WebSocketState.CONNECTED

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed = True
        self.close_code = code
        self.client_state = WebSocketState.DISCONNECTED

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        return {"type": "websocket.disconnect", "code": 1000}


class _Request:
    headers = {}


def _start_frame(**overrides):
    payload = {
        "action": "start_search",
        "query_variants": ["Example Film"],
        "search_types": ["movie"],
        "indexers": ["prowlarr"],
        "use_jellyseerr_logic": False,
        "use_custom_rules": False,
        "tmdb_id": "",
        "custom_rules": None,
        "seasons": [],
    }
    payload.update(overrides)
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def test_http_manual_search_uses_the_shared_query_length_limit():
    accepted = ManualSearchPayload(query="q" * MAX_SEARCH_QUERY_LENGTH, indexers=["prowlarr"])
    assert len(accepted.query) == MAX_SEARCH_QUERY_LENGTH

    with pytest.raises(ValidationError):
        ManualSearchPayload(
            query="q" * (MAX_SEARCH_QUERY_LENGTH + 1),
            indexers=["prowlarr"],
        )


def test_manual_search_runner_defensively_skips_oversized_queries(monkeypatch):
    from search import manual_search_results

    calls = []
    monkeypatch.setattr(manual_search_results, "_prowlarr_configured", lambda _config: True)
    monkeypatch.setattr(
        manual_search_results,
        "search_prowlarr",
        lambda *args: calls.append(args) or [],
    )

    results, warnings, debug_queries = manual_search_results.run_manual_searches(
        ["q" * (MAX_SEARCH_QUERY_LENGTH + 1)],
        "movie",
        {"prowlarr"},
        {},
    )

    assert results == []
    assert debug_queries == []
    assert warnings == ["Query ignorata perché troppo lunga"]
    assert calls == []


@pytest.fixture(autouse=True)
def _clear_global_sessions():
    search_session_registry.clear()
    yield
    search_session_registry.clear()


def test_search_session_is_owner_bound_one_shot_and_removed_on_finish():
    registry = SearchSessionRegistry()
    session_id = registry.create(10)

    with pytest.raises(SearchSessionUnavailableError):
        registry.claim(session_id, 11)

    registry.claim(session_id, 10)
    with pytest.raises(SearchSessionUnavailableError):
        registry.claim(session_id, 10)

    registry.finish(session_id, 10)
    assert registry.snapshot() == {}


def test_pending_sessions_expire_and_per_user_quota_is_bounded():
    now = [100.0]
    registry = SearchSessionRegistry(clock=lambda: now[0], pending_ttl=10, max_pending_per_user=2)
    registry.create(10)
    registry.create(10)

    with pytest.raises(SearchSessionLimitError):
        registry.create(10)

    now[0] += 11
    replacement = registry.create(10)
    assert list(registry.snapshot()) == [replacement]


def test_active_searches_have_per_user_and_global_quotas():
    registry = SearchSessionRegistry(max_active_per_user=1, max_active=2)
    first = registry.create(10)
    second = registry.create(10)
    third = registry.create(11)
    fourth = registry.create(12)
    registry.claim(first, 10)

    with pytest.raises(SearchSessionLimitError):
        registry.claim(second, 10)

    registry.claim(third, 11)
    with pytest.raises(SearchSessionLimitError):
        registry.claim(fourth, 12)


@pytest.mark.anyio
async def test_http_session_creation_records_authenticated_owner_and_enforces_quota():
    init_search_routes(
        require_auth=lambda _request: 10,
        ensure_db_backend=lambda: None,
        validate_csrf=lambda _request, _token: True,
    )

    responses = [await start_search_stream(_Request()) for _index in range(3)]
    session_ids = [json.loads(response.body)["session_id"] for response in responses]

    assert set(session_ids) == set(search_session_registry.snapshot())
    assert {session.owner_id for session in search_session_registry.snapshot().values()} == {10}
    with pytest.raises(HTTPException) as exc_info:
        await start_search_stream(_Request())
    assert exc_info.value.status_code == 429


@pytest.mark.anyio
async def test_foreign_user_cannot_claim_search_websocket_session():
    session_id = create_search_session(10)
    init_realtime_routes(lambda _connection: 11)
    websocket = _WebSocket()

    await websocket_search_endpoint(websocket, session_id)

    assert websocket.accepted is False
    assert websocket.close_code == 1008
    assert search_session_registry.snapshot()[session_id].status == "pending"


@pytest.mark.anyio
async def test_invalid_first_frame_consumes_session_and_cleans_up():
    session_id = create_search_session(10)
    init_realtime_routes(lambda _connection: 10)
    websocket = _WebSocket([_start_frame(use_custom_rules="false")])

    await websocket_search_endpoint(websocket, session_id)

    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.sent[-1] == {"type": "error", "message": "Parametri di ricerca non validi"}
    assert search_session_registry.snapshot() == {}

    replay = _WebSocket()
    await websocket_search_endpoint(replay, session_id)
    assert replay.accepted is False
    assert replay.close_code == 1008


@pytest.mark.anyio
async def test_first_frame_has_an_application_size_limit():
    oversized = "x" * (MAX_SEARCH_FRAME_BYTES + 1)
    websocket = _WebSocket([{"type": "websocket.receive", "text": oversized}])

    with pytest.raises(SearchStreamProtocolError, match="troppo grande"):
        await receive_search_start(websocket)


@pytest.mark.anyio
async def test_valid_socket_search_is_parsed_and_session_is_cleaned_up():
    session_id = create_search_session(10)
    init_realtime_routes(lambda _connection: 10)
    websocket = _WebSocket([_start_frame()])
    streaming = AsyncMock(return_value={"total_results": 0})

    with patch("core.config_manager.load_config", return_value=({"configured": True}, True)), patch(
        "search.streaming.search_streaming_parallel",
        streaming,
    ):
        await websocket_search_endpoint(websocket, session_id)

    assert websocket.accepted is True
    assert websocket.close_code == 1000
    assert streaming.await_args.kwargs["query_variants"] == ["Example Film"]
    assert streaming.await_args.kwargs["selected_indexers"] == {"prowlarr"}
    assert search_session_registry.snapshot() == {}


@pytest.mark.anyio
async def test_whole_stream_timeout_returns_error_and_cleans_up(monkeypatch):
    session_id = create_search_session(10)
    init_realtime_routes(lambda _connection: 10)
    websocket = _WebSocket([_start_frame()])

    async def never_finishes(**_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(search_websocket, "SEARCH_STREAM_TIMEOUT_SECONDS", 0.01)
    with patch("core.config_manager.load_config", return_value=({"configured": True}, True)), patch(
        "search.streaming.search_streaming_parallel",
        side_effect=never_finishes,
    ):
        await websocket_search_endpoint(websocket, session_id)

    assert websocket.sent[-1] == {"type": "error", "message": "Tempo massimo della ricerca superato"}
    assert search_session_registry.snapshot() == {}


@pytest.mark.anyio
async def test_generated_search_workload_has_a_hard_task_cap():
    called = False

    def search_provider(_query, _media_type, _config):
        nonlocal called
        called = True
        return []

    websocket = _WebSocket()
    with patch("search.indexers._prowlarr_configured", return_value=True), patch(
        "emby_runtime.api_clients.search_prowlarr",
        side_effect=search_provider,
    ):
        with pytest.raises(SearchWorkloadLimitError, match=str(MAX_SEARCH_TASKS)):
            await search_streaming_parallel(
                query_variants=[f"query-{index}" for index in range(MAX_SEARCH_TASKS + 1)],
                search_types=["movie"],
                selected_indexers={"prowlarr"},
                config={},
                websocket=websocket,
                session_id="bounded-session",
                owner_id=41,
            )

    assert called is False


@pytest.mark.anyio
async def test_outbound_search_concurrency_is_bounded_per_stream():
    semaphore = create_search_semaphore()
    lock = threading.Lock()
    active = 0
    peak = 0

    def search_provider(_query, _media_type, _config):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return []

    await asyncio.gather(
        *[
            run_outbound_search(semaphore, search_provider, f"query-{index}", "movie", {})
            for index in range(MAX_CONCURRENT_OUTBOUND_SEARCHES * 3)
        ]
    )

    assert peak <= MAX_CONCURRENT_OUTBOUND_SEARCHES


@pytest.mark.anyio
async def test_each_outbound_search_has_a_timeout(monkeypatch):
    monkeypatch.setattr(outbound_execution, "SEARCH_OUTBOUND_TIMEOUT_SECONDS", 0.01)

    def slow_provider(_query, _media_type, _config):
        time.sleep(0.05)
        return []

    with pytest.raises(TimeoutError):
        await run_outbound_search(
            create_search_semaphore(),
            slow_provider,
            "query",
            "movie",
            {},
        )


@pytest.mark.anyio
async def test_disconnected_client_cancels_search_before_outbound_calls():
    calls = []

    def search_provider(query, _media_type, _config):
        calls.append(query)
        return []

    class _DisconnectedWebSocket(_WebSocket):
        async def send_json(self, _payload):
            raise RuntimeError("socket closed")

    with patch("search.indexers._prowlarr_configured", return_value=True), patch(
        "emby_runtime.api_clients.search_prowlarr",
        side_effect=search_provider,
    ):
        with pytest.raises(SearchClientDisconnected):
            await search_streaming_parallel(
                query_variants=[f"query-{index}" for index in range(10)],
                search_types=["movie"],
                selected_indexers={"prowlarr"},
                config={},
                websocket=_DisconnectedWebSocket(),
                session_id="disconnected-session",
                owner_id=41,
            )

    assert calls == []
