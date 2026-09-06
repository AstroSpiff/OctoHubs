"""Regression and class-level canaries for the R35 remediation."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import threading

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from core.http_response_limits import UpstreamResponseError, read_bounded_json_response
from core.storage import (
    DatabaseStorage,
    EmbyProbeBlacklist,
    EmbyProbeHistory,
    EmbyProbeQueue,
    StorageError,
)
from core.storage.storage_app_settings import _merge_snapshot_changes
from core.storage.storage_manual_search import StorageManualSearchMixin
from emby_probe.manager import EmbyProbeManager
from emby_runtime import event_bridge_provisioning
from web.research_api_models import ResearchOverviewResponse


@pytest.mark.parametrize(
    ("latest", "original", "submitted"),
    [
        ({}, {"TRAKT": {"ACCESS_TOKEN": "old"}}, {"TRAKT": {"ACCESS_TOKEN": "new"}}),
        (
            {"TRAKT": {}},
            {"TRAKT": {"ACCESS_TOKEN": "old"}},
            {"TRAKT": {"ACCESS_TOKEN": "new"}},
        ),
    ],
)
def test_app_settings_edit_conflicts_with_concurrent_delete(latest, original, submitted):
    with pytest.raises(StorageError, match="Conflitto"):
        _merge_snapshot_changes(latest, original, submitted)


def test_event_bridge_provisioning_is_single_flight_per_server(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    generated: list[str] = []
    persisted: list[str] = []

    def generate() -> str:
        credential = f"credential-{len(generated) + 1}"
        generated.append(credential)
        return credential

    def push(_server, server_id, _settings, *, webhook_secret):
        entered.set()
        assert release.wait(2)
        return True, "", {
            "ServerId": server_id,
            "Settings": {
                "perServerCredentialSupported": True,
                "credentialConfigured": True,
            },
        }

    monkeypatch.setattr(event_bridge_provisioning, "generate_event_bridge_credential", generate)
    monkeypatch.setattr(event_bridge_provisioning, "push_event_bridge_settings_to_plugin", push)
    monkeypatch.setattr(
        event_bridge_provisioning,
        "begin_event_bridge_credential_rotation_if_server_exists",
        lambda _server_id, _credential: True,
    )
    monkeypatch.setattr(
        event_bridge_provisioning,
        "promote_event_bridge_credential_if_pending",
        lambda _server_id, credential: persisted.append(credential) is None,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(
            event_bridge_provisioning.provision_event_bridge_credential,
            {},
            "green",
            {},
        )
        assert entered.wait(2)
        follower = event_bridge_provisioning.provision_event_bridge_credential({}, "green", {})
        assert follower.ok is False
        assert "già in corso" in follower.error
        release.set()
        assert owner.result(timeout=2).ok is True

    assert generated == ["credential-1"]
    assert persisted == ["credential-1"]


class _BrokenSession:
    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def delete(self):
        raise SQLAlchemyError("primary database failure")

    def rollback(self):
        raise SQLAlchemyError("rollback failure")

    def invalidate(self):
        raise SQLAlchemyError("invalidate failure")

    def close(self):
        raise SQLAlchemyError("close failure")

    def remove(self):
        raise SQLAlchemyError("remove failure")


class _ManualSearchBackend(StorageManualSearchMixin):
    def _get_session(self):
        return _BrokenSession()


def test_storage_cleanup_never_masks_the_primary_typed_error_after_all_cleanup_fails():
    with pytest.raises(StorageError, match="Errore eliminazione ricerca manuale") as caught:
        _ManualSearchBackend().delete_manual_search(1)
    assert "primary database failure" in str(caught.value)
    assert "rollback failure" not in str(caught.value)


def test_probe_retry_keeps_diagnostics_when_concrete_claim_is_busy(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'probe-claimed.db'}"
    engine = create_engine(database_url, future=True)
    for model in (EmbyProbeQueue, EmbyProbeBlacklist, EmbyProbeHistory):
        model.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = storage._get_session()
    session.add(
        EmbyProbeQueue(
            server_id="green",
            item_id="movie-1",
            scope="libraries",
            media_source_id="source-a",
            name="Movie",
            media_type="Movie",
            claim_token="active",
            claimed_at=datetime.now(timezone.utc),
        )
    )
    session.add(
        EmbyProbeBlacklist(
            server_id="green",
            item_id="movie-1",
            scope="libraries",
            media_source_id="source-a",
            item_name="Movie",
            retry_count=3,
        )
    )
    session.add(
        EmbyProbeHistory(
            server_id="green",
            item_id="movie-1",
            scope="libraries",
            media_source_id="source-a",
            name="Movie",
            status="error",
        )
    )
    session.commit()
    session.close()

    item = {
        "server_id": "green",
        "item_id": "movie-1",
        "scope": "libraries",
        "media_source_id": "source-a",
        "name": "Movie",
        "media_type": "Movie",
    }
    with pytest.raises(StorageError, match="Nessuna sorgente"):
        storage.retry_probe_items(
            [item],
            server_id="green",
            item_id="movie-1",
            media_source_id="source-a",
            scope="libraries",
        )

    session = storage._get_session()
    try:
        assert session.query(EmbyProbeQueue).count() == 1
        assert session.query(EmbyProbeBlacklist).count() == 1
        assert session.query(EmbyProbeHistory).count() == 1
        assert session.query(EmbyProbeQueue).one().claim_token == "active"
    finally:
        session.close()
        engine.dispose()


def test_probe_retry_redacts_database_exception_from_public_message(monkeypatch, caplog):
    secret = "postgresql://octohubs:CANARY_R35_PASSWORD@db/octohubs"

    class BrokenDatabase:
        def retry_probe_items(self, *_args, **_kwargs):
            raise RuntimeError(secret)

    calls = 0

    def call_emby(_server, _path, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return True, {
                "Items": [
                    {
                        "Type": "Movie",
                        "Name": "Movie",
                        "ParentId": "library-a",
                        "MediaSources": [{"Id": "source-a", "MediaStreams": []}],
                    }
                ]
            }
        return True, [{"Type": "CollectionFolder", "Id": "library-a", "Name": "Movies"}]

    monkeypatch.setattr("emby_probe.manager._call_emby_api", call_emby)
    manager = EmbyProbeManager()
    manager._db_getter = lambda: BrokenDatabase()
    ok, message = manager.retry_item({}, "green", "movie-1", "source-a")

    assert ok is False
    assert message == "Retry Probe non riuscito per un errore database"
    assert secret not in message
    assert "CANARY_R35_PASSWORD" not in caplog.text


class _StreamingRaw:
    def stream(self, _chunk_size, decode_content=True):
        assert decode_content is True
        yield b"{" + b"x" * 40
        yield b"x" * 40 + b"}"


class _TrackedResponse(requests.Response):
    closed = False

    def close(self):
        self.closed = True
        super().close()


def test_bounded_json_rejects_chunked_body_without_content_length():
    response = _TrackedResponse()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response.raw = _StreamingRaw()  # type: ignore[assignment]
    with pytest.raises(UpstreamResponseError, match="troppo grande"):
        read_bounded_json_response(response, max_bytes=64)
    assert response.closed is True


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"Content-Type": "application/json", "Content-Length": "65"}, "troppo grande"),
        ({"Content-Type": "text/html"}, "non JSON"),
    ],
)
def test_bounded_json_rejects_declared_size_and_content_type(headers, message):
    response = _TrackedResponse()
    response.status_code = 200
    response.headers.update(headers)
    response.raw = _StreamingRaw()  # type: ignore[assignment]
    with pytest.raises(UpstreamResponseError, match=message):
        read_bounded_json_response(response, max_bytes=64)
    assert response.closed is True


class _JsonOnlyResponse:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


def test_bounded_json_rejects_oversized_string_field():
    response = _JsonOnlyResponse({"value": "x" * (1024 * 1024 + 1)})
    with pytest.raises(UpstreamResponseError, match="Campo JSON upstream troppo grande"):
        read_bounded_json_response(response)
    assert response.closed is True


def test_bounded_json_rejects_excessive_depth():
    payload: dict[str, object] = {}
    current = payload
    for _index in range(66):
        child: dict[str, object] = {}
        current["child"] = child
        current = child

    response = _JsonOnlyResponse(payload)
    with pytest.raises(UpstreamResponseError, match="Risposta JSON upstream troppo profonda"):
        read_bounded_json_response(response)
    assert response.closed is True


def test_research_overview_has_a_structured_scan_summary_contract():
    schema = ResearchOverviewResponse.model_json_schema()
    results_schema = schema["$defs"]["ResearchResults"]
    item_ref = results_schema["properties"]["items"]["items"]["$ref"]
    assert item_ref.endswith("/ResearchScanSummaryItem")


def _application_python_files(root: Path):
    for path in root.rglob("*.py"):
        if not any(part in {"venv", ".git", "node_modules", "tests"} for part in path.parts):
            yield path


def _request_session_names(tree: ast.AST) -> set[str]:
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "requests"
        and node.value.func.attr == "Session"
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _receiver_name(node: ast.Attribute) -> str:
    return node.value.id if isinstance(node.value, ast.Name) else ""


def _is_response_name(name: str) -> bool:
    return name in {"response", "r"} or name.endswith("resp")


def _has_literal_stream_true(node: ast.Call) -> bool:
    values = [keyword.value for keyword in node.keywords if keyword.arg == "stream"]
    return bool(values and isinstance(values[0], ast.Constant) and values[0].value is True)


def _direct_response_reads(root: Path) -> list[str]:
    findings: list[str] = []
    allowed = root / "core/http_response_limits.py"
    for path in _application_python_files(root):
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"text", "content"}:
                if _is_response_name(_receiver_name(node)):
                    findings.append(f"{path.relative_to(root)}:{node.lineno}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "json" and _is_response_name(_receiver_name(node.func)):
                    findings.append(f"{path.relative_to(root)}:{node.lineno}")
    return findings


def _unbounded_request_calls(root: Path) -> list[str]:
    findings: list[str] = []
    verbs = {"get", "post", "put", "patch", "delete", "request"}
    for path in _application_python_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        sessions = _request_session_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            direct = isinstance(receiver, ast.Name) and receiver.id == "requests"
            session = isinstance(receiver, ast.Name) and receiver.id in sessions
            if (direct or session) and node.func.attr in verbs and not _has_literal_stream_true(node):
                findings.append(f"{path.relative_to(root)}:{node.lineno}")
    return findings


def _direct_storage_cleanup(root: Path) -> list[str]:
    findings: list[str] = []
    for path in (root / "core/storage").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if _receiver_name(node.func) == "session" and node.func.attr in {"rollback", "close"}:
                findings.append(f"{path.relative_to(root)}:{node.lineno}")
    return findings


def test_repository_has_no_direct_response_materialization():
    root = Path(__file__).resolve().parents[1]
    assert _direct_response_reads(root) == []


def test_repository_external_requests_are_streamed():
    root = Path(__file__).resolve().parents[1]
    assert _unbounded_request_calls(root) == []


def test_repository_storage_uses_safe_session_cleanup():
    root = Path(__file__).resolve().parents[1]
    assert _direct_storage_cleanup(root) == []
