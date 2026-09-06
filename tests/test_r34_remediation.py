"""Deterministic regression and invariant canaries for the R34 remediation."""

from __future__ import annotations

from concurrent.futures import Future
import importlib.util
from pathlib import Path
import threading

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_migration(filename: str):
    path = PROJECT_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auth_engine_uses_canonical_postgresql_deadlines(monkeypatch):
    from core import auth
    from core.storage import storage_core

    captured: dict[str, object] = {}
    assert callable(storage_core.upgrade_database)

    class Engine:
        pass

    def create_engine(url, **options):
        captured.update({"url": url, **options})
        return Engine()

    monkeypatch.setenv("OCTOHUBS_DB_CONNECT_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("OCTOHUBS_DB_STATEMENT_TIMEOUT_MS", "41000")
    monkeypatch.setattr("core.database_migrations.upgrade_database", lambda _url: None)
    monkeypatch.setattr(auth, "create_engine", create_engine)
    monkeypatch.setattr(auth, "sessionmaker", lambda **_kwargs: object())
    monkeypatch.setattr(auth, "db_session", None)

    assert auth.init_auth(
        database_url="postgresql+psycopg2://user:password@db/app"
    ) is True
    assert captured["connect_args"] == {
        "connect_timeout": 9,
        "options": "-c statement_timeout=41000",
    }


def test_auth_double_failure_preserves_typed_primary_error(monkeypatch):
    from core import auth

    class BrokenSession:
        invalidated = False

        def query(self, *_args):
            raise SQLAlchemyError("query failure")

        def rollback(self):
            raise SQLAlchemyError("rollback failure")

        def invalidate(self):
            self.invalidated = True

    session = BrokenSession()
    monkeypatch.setattr(auth, "db_session", session)

    with pytest.raises(auth.AuthStorageError, match="Verifica API token"):
        auth.verify_api_token("ohs_test_value")
    assert session.invalidated is True


def test_automatic_search_respects_global_outbound_concurrency(monkeypatch):
    from search import outbound_execution
    from search.stream_limits import MAX_GLOBAL_OUTBOUND_SEARCHES
    from services import requests_processor

    release = threading.Event()
    all_started = threading.Event()
    lock = threading.Lock()
    active = 0
    peak = 0

    def blocker():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == MAX_GLOBAL_OUTBOUND_SEARCHES:
                all_started.set()
        release.wait(2)
        with lock:
            active -= 1
        return []

    outbound_execution.initialize_search_executor()
    blockers = [
        outbound_execution.submit_outbound_search(blocker)
        for _ in range(MAX_GLOBAL_OUTBOUND_SEARCHES)
    ]
    assert all_started.wait(1)
    monkeypatch.setattr(requests_processor, "SEARCH_OUTBOUND_TIMEOUT_SECONDS", 0.02)
    try:
        with pytest.raises(
            requests_processor.ProviderSearchError,
            match="Nessun indexer",
        ):
            requests_processor.search_indexers(
                "query",
                "movie",
                {
                    "PROWLARR_URL": "https://indexer.test",
                    "PROWLARR_API_KEY": "configured",
                },
            )
        assert peak == MAX_GLOBAL_OUTBOUND_SEARCHES
    finally:
        release.set()
        for future in blockers:
            future.result(timeout=1)
        outbound_execution.shutdown_search_executor(timeout_seconds=1)
        outbound_execution.initialize_search_executor()


@pytest.mark.parametrize("invalid", [{"nested": "title"}, ["title"], 42, True])
@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("prowlarr", lambda invalid: [{"title": invalid}]),
        ("jackett", lambda invalid: {"Results": [{"Title": invalid}]}),
    ],
)
def test_indexer_adapters_reject_non_scalar_titles(
    monkeypatch,
    invalid,
    provider,
    payload,
):
    from emby_runtime import api_clients_indexers
    from search.provider_outcomes import ProviderSearchError

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        def raise_for_status(self):
            return None

        def json(self):
            return payload(invalid)

        def close(self):
            return None

    monkeypatch.setattr(api_clients_indexers.requests, "get", lambda *_a, **_kw: Response())
    if provider == "prowlarr":
        def call():
            return api_clients_indexers.search_prowlarr(
                "query",
                "movie",
                {"PROWLARR_URL": "https://indexer.test", "PROWLARR_API_KEY": "key"},
            )
    else:
        def call():
            return api_clients_indexers.search_jackett(
                "query",
                "movie",
                {"JACKETT_URL": "https://indexer.test", "JACKETT_API_KEY": "key"},
            )
    with pytest.raises(ProviderSearchError, match="title|Title"):
        call()


def test_every_search_consumer_rejects_a_malformed_provider_result(monkeypatch):
    from search import manual_search_results
    from search.provider_outcomes import ProviderSearchError
    from services import requests_processor

    malformed = [{"title": {"nested": "value"}}]

    def completed_future(*_args, **_kwargs):
        future: Future[list[dict[str, object]]] = Future()
        future.set_result(malformed)
        return future

    monkeypatch.setattr(manual_search_results, "submit_outbound_search", completed_future)
    warnings: list[str] = []
    rows, completed, _truncated = manual_search_results._collect_provider_results(
        [("provider", object(), "query", "movie", {})],
        warnings,
    )
    assert rows == []
    assert completed == 0
    assert warnings == ["Provider non disponibile"]

    monkeypatch.setattr(requests_processor, "submit_outbound_search", completed_future)
    with pytest.raises(ProviderSearchError, match="Nessun indexer"):
        requests_processor.search_indexers(
            "query",
            "movie",
            {"PROWLARR_URL": "https://indexer.test", "PROWLARR_API_KEY": "key"},
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("magnet", {}),
        ("downloadUrl", []),
        ("indexer", False),
        ("seeders", "12"),
        ("size", float("inf")),
    ],
)
def test_canonical_provider_contract_rejects_every_malformed_field(field, invalid):
    from search.provider_outcomes import ProviderSearchError, validate_provider_results

    row = {"title": "Valid title", "indexer": "provider", field: invalid}
    with pytest.raises(ProviderSearchError, match=field):
        validate_provider_results([row], provider="provider")


def test_canonical_provider_contract_bounds_rows_and_text():
    from search.provider_outcomes import (
        MAX_INDEXER_FIELD_CHARS,
        MAX_INDEXER_RESULTS,
        validate_provider_results,
    )

    rows = [
        {"title": "x" * 800, "indexer": "p", "guid": "g" * 8_000}
        for _index in range(MAX_INDEXER_RESULTS + 1)
    ]
    validated = validate_provider_results(rows, provider="provider")
    assert len(validated) == MAX_INDEXER_RESULTS
    assert validated.truncated is True
    assert len(validated[0]["title"]) == 500
    assert len(validated[0]["guid"]) == MAX_INDEXER_FIELD_CHARS


def test_latest_projection_migration_fetches_rows_in_bounded_batches():
    migration = _load_migration(
        "20260906_19_remove_legacy_latest_state.py"
    )

    class Result:
        def __init__(self):
            self.remaining = 1_201
            self.requested: list[int] = []

        def mappings(self):
            return self

        def fetchmany(self, size):
            self.requested.append(size)
            count = min(size, self.remaining)
            self.remaining -= count
            return [{"id": index} for index in range(count)]

    class Bind:
        def __init__(self):
            self.result = Result()
            self.options: list[dict[str, object]] = []

        def execute(self, statement):
            self.options.append(dict(statement._execution_options))
            return self.result

    bind = Bind()
    assert len(list(migration._iter_rows(bind, "legacy"))) == 1_201
    assert bind.result.requested == [migration._ROW_BATCH_SIZE] * 4
    assert bind.options == [{"stream_results": True}]


def test_latest_settings_never_reload_or_resave_legacy_payloads(monkeypatch):
    from emby_latest import settings

    stored = {
        "EMBY_LATEST": {
            "STATE": {"server": {"large": "payload"}},
            "CACHE": {"server": {"large": "payload"}},
            "SETTINGS": {},
        }
    }
    saved: dict[str, object] = {}
    monkeypatch.setattr("services.manager._load_app_settings_snapshot", lambda: stored)
    monkeypatch.setattr(
        "services.manager._save_app_settings_snapshot",
        lambda payload: saved.update(payload),
    )

    loaded = settings._load_latest_settings()
    assert "STATE" not in loaded
    assert "CACHE" not in loaded
    settings._save_latest_settings(loaded)
    assert "STATE" not in saved["EMBY_LATEST"]
    assert "CACHE" not in saved["EMBY_LATEST"]


def test_latest_app_settings_cleanup_is_idempotent():
    migration = _load_migration(
        "20260906_20_remove_latest_app_settings_legacy.py"
    )
    original = {
        "OTHER": {"preserved": True},
        "EMBY_LATEST": {"STATE": {"old": 1}, "CACHE": {"old": 2}, "PRESETS": []},
    }
    cleaned, changed = migration._scrub_latest_payload(original)
    assert changed is True
    assert cleaned == {
        "OTHER": {"preserved": True},
        "EMBY_LATEST": {"PRESETS": []},
    }
    repeated, changed_again = migration._scrub_latest_payload(cleaned)
    assert repeated == cleaned
    assert changed_again is False


def test_latest_runtime_cleanup_uses_atomic_section_update(monkeypatch):
    from emby_latest import settings

    class Backend:
        calls = 0
        result: dict[str, object] = {}

        def update_app_settings_section(self, section, updater):
            assert section == "EMBY_LATEST"
            self.calls += 1
            self.result = updater(
                {
                    "STATE": {"obsolete": True},
                    "CACHE": {"obsolete": True},
                    "PRESETS": [{"id": "kept"}],
                }
            )

    backend = Backend()
    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: backend)
    settings._clear_latest_state()
    assert backend.calls == 1
    assert backend.result == {"PRESETS": [{"id": "kept"}]}


def test_tracked_scan_server_identifiers_are_opaque_and_single_line():
    from emby_libraries.scan_api_models import (
        GroupScanLibrary,
        ScanLibraryRequest,
        TrackedScanLibraryRequest,
    )

    for model, payload in (
        (ScanLibraryRequest, {"server_id": "server\nforged", "library_id": "library"}),
        (
            TrackedScanLibraryRequest,
            {"server_id": "server\nforged", "library_ids": ["library"]},
        ),
        (GroupScanLibrary, {"server_id": "server\nforged", "library_id": "library"}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_direct_scan_group_normalizer_rejects_unsafe_server_identifiers():
    from emby_libraries.scan_limits import normalize_group_libraries

    with pytest.raises(ValueError, match="Server o ID"):
        normalize_group_libraries(
            [{"server_id": "server\nforged", "library_id": "library"}]
        )


def test_direct_tracked_scan_boundary_rejects_identifier_before_logging(capsys):
    from emby_libraries.scan_manager import EmbyLibraryScanManager

    manager = object.__new__(EmbyLibraryScanManager)
    with pytest.raises(ValueError, match="server_id non valido"):
        manager._tracked_request_values(
            {
                "server_id": "server\n[FORGED]",
                "library_ids": ["library"],
                "scan_type": "content",
            }
        )
    assert capsys.readouterr().out == ""
