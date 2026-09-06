"""Deterministic canaries for the R33 remediation invariants."""

from __future__ import annotations

import threading
import time

import pytest
import requests
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketState


@pytest.mark.anyio
async def test_real_lifespan_resolves_storage_before_poller_and_admission(monkeypatch):
    from runtime import app_setup

    calls = []
    storage = object()
    monkeypatch.setattr("search.outbound_execution.initialize_search_executor", lambda: calls.append("search"))
    monkeypatch.setattr(app_setup, "init_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(app_setup, "load_config", lambda: (calls.append("config") or ({}, True)))
    monkeypatch.setattr(app_setup, "_ensure_db_backend", lambda: calls.append("storage") or storage)
    monkeypatch.setattr(app_setup, "init_auth", lambda **_kwargs: calls.append("auth"))

    async def register(received):
        assert received is storage
        calls.append("poller")

    def initialize(**kwargs):
        assert kwargs["db_storage"] is storage
        calls.append("admission")

    async def shutdown():
        calls.append("shutdown")
        return True

    monkeypatch.setattr(app_setup, "register_runtime_event_loop", register)
    monkeypatch.setattr(app_setup, "initialize_runtime_services", initialize)
    monkeypatch.setattr(app_setup, "shutdown_runtime_services", shutdown)
    monkeypatch.setattr(app_setup, "mark_runtime_starting", lambda: None)
    monkeypatch.setattr(app_setup, "mark_runtime_started", lambda: calls.append("ready"))

    async with app_setup._application_lifespan(object()):
        assert calls.index("config") < calls.index("poller") < calls.index("admission")
        assert calls[-1] == "ready"
    assert calls[-1] == "shutdown"


def test_postgresql_engines_receive_local_connection_and_statement_deadlines(monkeypatch):
    from core.database_timeouts import postgres_engine_options

    monkeypatch.setenv("OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("OCTOHUBS_DB_STATEMENT_TIMEOUT_MS", "42000")

    options = postgres_engine_options("postgresql+psycopg2://user:secret@db/app")

    assert options == {
        "connect_args": {
            "connect_timeout": 7,
            "options": "-c statement_timeout=42000",
        }
    }
    assert postgres_engine_options("sqlite://") == {}


def test_readiness_follower_has_a_local_deadline(monkeypatch):
    from core import config_manager
    from runtime import health

    entered = threading.Event()
    release = threading.Event()

    class Backend:
        def test_connection(self):
            entered.set()
            release.wait(1)
            return True, None

        def validate_migrations(self):
            return {"ok": True}

    monkeypatch.setattr(config_manager, "_ensure_db_backend", lambda: Backend())
    monkeypatch.setattr(health, "_READINESS_WAITER_SECONDS", 0.02)
    health.mark_runtime_starting()
    owner = threading.Thread(target=health.database_ready)
    owner.start()
    assert entered.wait(1)
    started = time.monotonic()
    try:
        assert health.database_ready() is False
        assert time.monotonic() - started < 0.2
    finally:
        release.set()
        owner.join(1)
        health.mark_runtime_starting()


def test_indexer_response_is_rejected_before_unbounded_json_decode(monkeypatch):
    from emby_runtime.api_clients_indexers import search_prowlarr
    from search import provider_outcomes
    from search.provider_outcomes import ProviderSearchError

    class Response:
        status_code = 200
        headers = {}
        closed = False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            del chunk_size
            yield b"["
            yield b"x" * 32

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(provider_outcomes, "MAX_INDEXER_RESPONSE_BYTES", 16)
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response)

    with pytest.raises(ProviderSearchError, match="limite"):
        search_prowlarr(
            "query",
            "movie",
            {"PROWLARR_URL": "https://indexer.test", "PROWLARR_API_KEY": "key"},
        )
    assert response.closed is True


def test_manual_and_automatic_searches_share_the_global_result_budget(monkeypatch):
    from search import manual_search_results
    from search.provider_outcomes import (
        MAX_AGGREGATED_SEARCH_RESULTS,
        AggregatedSearchResults,
    )
    from services import requests_processor

    oversized = [{"title": f"item-{index}"} for index in range(600)]
    monkeypatch.setattr(
        manual_search_results,
        "_manual_provider_tasks",
        lambda *_args: [("provider", object(), "query", "movie", {})],
    )
    monkeypatch.setattr(
        manual_search_results,
        "_collect_provider_results",
        lambda *_args: (oversized, 1, False),
    )
    manual, _warnings, _queries = manual_search_results.run_manual_searches(
        ["query"], "movie", {"provider"}, {}
    )
    assert len(manual) == MAX_AGGREGATED_SEARCH_RESULTS
    assert manual.truncated is True

    monkeypatch.setattr(
        requests_processor,
        "search_indexers",
        lambda *_args: AggregatedSearchResults(oversized),
    )
    monkeypatch.setattr(requests_processor, "filter_results", lambda rows, *_args, **_kwargs: rows)
    automatic, attempts = requests_processor.execute_search_with_variants(
        ["one", "two"], "movie", {}
    )
    assert len(automatic) == MAX_AGGREGATED_SEARCH_RESULTS
    assert automatic.truncated is True
    assert attempts[0]["truncated"] is True


def test_library_membership_failure_is_not_reported_as_absent(monkeypatch):
    from search.library_index import (
        LibraryIndexUnavailableError,
        _load_emby_library_title_index,
    )

    class Backend:
        def get_probe_matching_titles(self, _titles):
            raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: Backend())
    with pytest.raises(LibraryIndexUnavailableError):
        _load_emby_library_title_index({"known title"})


def test_probe_csv_export_stops_at_a_hard_page_budget(monkeypatch):
    from emby_probe import csv_export

    monkeypatch.setattr(csv_export, "MAX_PROBE_CSV_EXPORT_PAGES", 1)

    def fetch_page(_server_id, _error, _item, _scope, _limit, offset):
        next_offset = int(offset) + 500
        return {"blacklist": [], "next_offset": next_offset}, 200

    spool, payload, status = csv_export.build_probe_csv_export(
        fetch_page,
        None,
        "libraries",
        {},
    )
    assert spool is None
    assert status == 413
    assert "pagine" in payload["error"]


def test_probe_csv_concurrency_gate_is_bounded():
    from emby_probe.routes import _PROBE_CSV_EXPORT_SLOTS

    assert _PROBE_CSV_EXPORT_SLOTS.acquire(blocking=False)
    assert _PROBE_CSV_EXPORT_SLOTS.acquire(blocking=False)
    try:
        assert not _PROBE_CSV_EXPORT_SLOTS.acquire(blocking=False)
    finally:
        _PROBE_CSV_EXPORT_SLOTS.release()
        _PROBE_CSV_EXPORT_SLOTS.release()


def test_auth_storage_errors_remain_distinct_from_not_found(monkeypatch):
    from core import auth

    class FailingSession:
        def query(self, *_args):
            raise SQLAlchemyError("database unavailable")

        def get(self, *_args):
            raise SQLAlchemyError("database unavailable")

    previous = auth.db_session
    monkeypatch.setattr(auth, "db_session", FailingSession())
    try:
        with pytest.raises(auth.AuthStorageError):
            auth.get_user_by_username("known")
        with pytest.raises(auth.AuthStorageError):
            auth.get_user_by_id(1)
        with pytest.raises(auth.AuthStorageError):
            auth.get_all_users()
        with pytest.raises(auth.AuthStorageError):
            auth.list_api_tokens(1)
    finally:
        auth.db_session = previous


def test_latest_console_diagnostics_are_single_line(capsys):
    from emby_latest.builders import _build_emby_latest_item

    _build_emby_latest_item(
        {
            "Id": "1",
            "Name": "Legit\n[FORGED] authorization=passed",
            "ProviderIds": {"Imdb": "tt1"},
        },
        None,
    )

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert "[FORGED]" in lines[0]


@pytest.mark.anyio
async def test_streaming_search_uses_one_library_lookup_and_marks_truncation(monkeypatch):
    from core.config import DEFAULT_CONFIG
    from search import provider_outcomes
    from search.streaming import search_streaming_parallel

    calls = 0

    def load_index(titles):
        nonlocal calls
        calls += 1
        return set(titles)

    def search(query, _media_type, _config):
        return [
            {"title": f"{query} result {index}", "normalized_title": f"{query} result {index}"}
            for index in range(5)
        ]

    class Backend:
        def save_manual_search(self, _payload):
            return None

    class WebSocket:
        client_state = WebSocketState.CONNECTED

        def __init__(self):
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    websocket = WebSocket()
    config = {**DEFAULT_CONFIG, "PROWLARR_URL": "https://indexer", "PROWLARR_API_KEY": "key"}
    monkeypatch.setattr(provider_outcomes, "MAX_AGGREGATED_SEARCH_RESULTS", 3)
    monkeypatch.setattr("search.indexers._prowlarr_configured", lambda _config: True)
    monkeypatch.setattr("emby_runtime.api_clients.search_prowlarr", search)
    monkeypatch.setattr("core.scanner.filter_results", lambda results, *_args, **_kwargs: results)
    monkeypatch.setattr("search.library_index._load_emby_library_title_index", load_index)
    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: Backend())

    await search_streaming_parallel(
        ["one", "two"],
        ["movie"],
        {"prowlarr"},
        config,
        websocket,
        "session",
        1,
    )

    terminal = [message for message in websocket.messages if message.get("type") == "all_completed"][-1]
    assert calls == 1
    assert terminal["status"] == "partial"
    assert terminal["truncated"] is True
    assert len(terminal["filtered_results"]) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("failure_kind", ["provider", "persistence"])
async def test_streaming_terminal_distinguishes_failure_outcomes(monkeypatch, failure_kind):
    from core.config import DEFAULT_CONFIG
    from search.streaming import search_streaming_parallel

    def search(_query, _media_type, _config):
        if failure_kind == "provider":
            raise RuntimeError("indexer offline")
        return [{"title": "Result", "normalized_title": "result"}]

    class Backend:
        def save_manual_search(self, _payload):
            if failure_kind == "persistence":
                raise SQLAlchemyError("database offline")

    class WebSocket:
        client_state = WebSocketState.CONNECTED

        def __init__(self):
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    websocket = WebSocket()
    config = {**DEFAULT_CONFIG, "PROWLARR_URL": "https://indexer", "PROWLARR_API_KEY": "key"}
    monkeypatch.setattr("search.indexers._prowlarr_configured", lambda _config: True)
    monkeypatch.setattr("emby_runtime.api_clients.search_prowlarr", search)
    monkeypatch.setattr("core.scanner.filter_results", lambda results, *_args, **_kwargs: results)
    monkeypatch.setattr(
        "search.library_index._load_emby_library_title_index",
        lambda _titles: set(),
    )
    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: Backend())

    await search_streaming_parallel(
        ["query"], ["movie"], {"prowlarr"}, config, websocket, "session", 1
    )

    terminal = [message for message in websocket.messages if message.get("type") == "all_completed"][-1]
    if failure_kind == "provider":
        assert terminal["status"] == "error"
        assert terminal["failed_queries"] == 1
    else:
        assert terminal["status"] == "partial"
        assert terminal["history_saved"] is False


def test_latest_runtime_models_expose_only_the_canonical_state_document():
    from core.storage import storage_models

    assert hasattr(storage_models, "EmbyLatestStateDocument")
    for name in (
        "EmbyLatestStateMovie",
        "EmbyLatestStateSeries",
        "EmbyLatestStateEpisode",
        "EmbyLatestStateSeriesGroup",
        "EmbyLatestStateSeriesChange",
    ):
        assert not hasattr(storage_models, name)


def test_every_latest_module_with_console_output_uses_the_safe_boundary():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "emby_latest"
    offenders = []
    for source_path in root.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if "print(" in source and "from core.safe_output import safe_print as print" not in source:
            offenders.append(source_path.name)
    assert offenders == []
