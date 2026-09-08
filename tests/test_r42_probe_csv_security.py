"""R42 regressors for safe Probe CSV headers and response-owned cleanup."""

from __future__ import annotations

import ast
import asyncio
import io
from pathlib import Path
import threading

from fastapi import HTTPException
import h11
import pytest

from web.download_headers import attachment_content_disposition
from web.owned_streaming_response import IdempotentCleanup, OwnedStreamingResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASGI_SCOPE = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.4"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/api/emby/probe/export-csv",
    "raw_path": b"/api/emby/probe/export-csv",
    "query_string": b"",
    "headers": [],
    "client": ("127.0.0.1", 12345),
    "server": ("127.0.0.1", 5050),
}


class TrackingSpool(io.StringIO):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        super().close()


class ProbeRequest:
    def __init__(self, scope: object = "libraries") -> None:
        self.query_params = {"server_id": "green", "scope": scope}


def _available_slots(semaphore: threading.BoundedSemaphore) -> int:
    acquired = 0
    while semaphore.acquire(blocking=False):
        acquired += 1
    for _ in range(acquired):
        semaphore.release()
    return acquired


async def _receive() -> dict[str, object]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _probe_response(monkeypatch, *, scope: str = "libraries"):
    from emby_probe import routes

    semaphore = threading.BoundedSemaphore(value=2)
    spool = TrackingSpool("Tipo,Server\r\nIncompleto,green\r\n")
    monkeypatch.setattr(routes, "_PROBE_CSV_EXPORT_SLOTS", semaphore)
    monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 1)
    monkeypatch.setattr(routes, "load_config", lambda: ({"EMBY": {"SERVERS": []}}, True))
    monkeypatch.setattr(
        routes,
        "build_probe_csv_export",
        lambda *_args: (spool, None, 200),
    )
    response = await routes.probe_export_csv(ProbeRequest(scope))
    assert isinstance(response, OwnedStreamingResponse)
    assert _available_slots(semaphore) == 1
    return response, spool, semaphore


@pytest.mark.parametrize(
    "scope",
    [
        "",
        "libraries\r\nX-R42-Injected: yes",
        "recent\x00",
        "libraries\x7f",
        "libràries",
        'libraries"',
        "../libraries",
        "..\\recent",
    ],
)
def test_probe_csv_rejects_every_non_enum_scope_before_acquiring_resources(monkeypatch, scope):
    from emby_probe import routes

    semaphore = threading.BoundedSemaphore(value=2)
    monkeypatch.setattr(routes, "_PROBE_CSV_EXPORT_SLOTS", semaphore)
    monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 1)
    monkeypatch.setattr(routes, "load_config", lambda: pytest.fail("invalid scope reached config loading"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.probe_export_csv(ProbeRequest(scope)))

    assert error.value.status_code == 422
    assert _available_slots(semaphore) == 2


def test_probe_csv_openapi_declares_the_same_scope_enum_enforced_at_runtime():
    from emby_probe import routes
    from emby_probe.api_models import PROBE_SCOPE_VALUES

    route = next(
        route
        for route in routes.router.routes
        if getattr(route, "path", "") == "/api/emby/probe/export-csv"
    )
    parameters = route.openapi_extra["parameters"]
    scope_parameter = next(parameter for parameter in parameters if parameter["name"] == "scope")

    assert scope_parameter["schema"]["enum"] == list(PROBE_SCOPE_VALUES)


@pytest.mark.parametrize(
    ("filename", "forbidden"),
    [
        ("report\r\nX-R42-Injected: yes.csv", "\r"),
        ("report\r\nX-R42-Injected: yes.csv", "\n"),
        ("report\x00.csv", "\x00"),
        ("report\x7f.csv", "\x7f"),
        ('report\"quoted.csv', '\"quoted'),
        ("../../private/report.csv", "private"),
        ("..\\private\\report.csv", "private"),
        ("rèport-€.csv", "€"),
    ],
)
def test_attachment_header_is_ascii_protocol_safe_and_path_free(filename, forbidden):
    value = attachment_content_disposition(filename, fallback="report.csv")

    assert value.isascii()
    assert all(ord(character) >= 32 and ord(character) != 127 for character in value)
    assert forbidden not in value
    assert "/" not in value and "\\" not in value
    connection = h11.Connection(h11.SERVER)
    assert connection.send(h11.Response(status_code=200, headers=[("Content-Disposition", value)]))


def test_attachment_header_keeps_an_untrusted_unicode_fallback_ascii_safe():
    value = attachment_content_disposition("", fallback='€\r\n"fallback')

    assert value.isascii()
    assert all(ord(character) >= 32 and ord(character) != 127 for character in value)
    assert "€" not in value and "\r" not in value and "\n" not in value
    connection = h11.Connection(h11.SERVER)
    assert connection.send(h11.Response(status_code=200, headers=[("Content-Disposition", value)]))


@pytest.mark.parametrize("failure_point", ["response-start", "response-body"])
def test_probe_csv_releases_spool_and_slot_when_transport_fails(monkeypatch, failure_point):
    async def exercise():
        response, spool, semaphore = await _probe_response(monkeypatch)

        async def send(message):
            if message["type"] == "http.response.start" and failure_point == "response-start":
                raise RuntimeError("transport rejected response start")
            if message["type"] == "http.response.body" and failure_point == "response-body":
                raise RuntimeError("transport rejected response body")

        with pytest.raises(RuntimeError, match="transport rejected"):
            await response(ASGI_SCOPE, _receive, send)
        assert spool.closed and spool.close_count == 1
        assert _available_slots(semaphore) == 2

    asyncio.run(exercise())


def test_two_response_start_failures_do_not_make_the_third_export_return_429(monkeypatch):
    from emby_probe import routes

    async def exercise():
        semaphore = threading.BoundedSemaphore(value=2)
        spools = []
        monkeypatch.setattr(routes, "_PROBE_CSV_EXPORT_SLOTS", semaphore)
        monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 1)
        monkeypatch.setattr(routes, "load_config", lambda: ({"EMBY": {"SERVERS": []}}, True))

        def build_export(*_args):
            spool = TrackingSpool("Tipo,Server\r\nIncompleto,green\r\n")
            spools.append(spool)
            return spool, None, 200

        monkeypatch.setattr(routes, "build_probe_csv_export", build_export)

        async def reject_start(message):
            if message["type"] == "http.response.start":
                raise RuntimeError("transport rejected response start")

        for _ in range(2):
            response = await routes.probe_export_csv(ProbeRequest())
            assert isinstance(response, OwnedStreamingResponse)
            with pytest.raises(RuntimeError, match="transport rejected response start"):
                await response(ASGI_SCOPE, _receive, reject_start)

        messages = []

        async def send(message):
            messages.append(message)

        third_response = await routes.probe_export_csv(ProbeRequest())
        assert isinstance(third_response, OwnedStreamingResponse)
        await third_response(ASGI_SCOPE, _receive, send)

        assert all(spool.closed and spool.close_count == 1 for spool in spools)
        assert len(spools) == 3
        assert _available_slots(semaphore) == 2
        assert any(message["type"] == "http.response.start" for message in messages)
        assert b"Incompleto,green" in b"".join(
            message.get("body", b"") for message in messages
        )

    asyncio.run(exercise())


def test_owned_stream_releases_once_when_cancelled_before_first_body():
    async def exercise():
        body_started = asyncio.Event()
        never = asyncio.Event()
        cleanup_calls = []
        owner = IdempotentCleanup(
            lambda: cleanup_calls.append("released"),
            context="R42 cancellation canary",
        )

        async def body():
            body_started.set()
            await never.wait()
            yield b"unreachable"

        async def send(_message):
            return None

        response = OwnedStreamingResponse(body(), owner=owner)
        task = asyncio.create_task(response(ASGI_SCOPE, _receive, send))
        await asyncio.wait_for(body_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup_calls == ["released"]

    asyncio.run(exercise())


def test_probe_csv_normal_completion_closes_spool_and_releases_slot_once(monkeypatch):
    async def exercise():
        response, spool, semaphore = await _probe_response(monkeypatch, scope="recent")
        messages = []

        async def send(message):
            messages.append(message)

        await response(ASGI_SCOPE, _receive, send)

        assert spool.closed and spool.close_count == 1
        assert _available_slots(semaphore) == 2
        assert b"Incompleto,green" in b"".join(
            message.get("body", b"") for message in messages
        )
        disposition = dict(response.raw_headers)[b"content-disposition"]
        assert b"strm_probe_report_recent_" in disposition
        assert b"\r" not in disposition and b"\n" not in disposition

    asyncio.run(exercise())


def _is_content_disposition_key(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lower() == "content-disposition"
    )


def _is_safe_content_disposition_value(value: ast.AST) -> bool:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value.isascii() and all(
            ord(character) >= 32 and ord(character) != 127
            for character in value.value
        )
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "attachment_content_disposition"
    )


def _content_disposition_candidates(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Dict):
        return [
            value
            for key, value in zip(node.keys, node.values)
            if _is_content_disposition_key(key)
        ]
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return []
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if any(
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and "header" in target.value.id.lower()
        and _is_content_disposition_key(target.slice)
        for target in targets
    ):
        return [node.value]
    return []


def test_all_application_content_disposition_values_are_static_or_canonical():
    violations = []
    ignored_parts = {".git", ".venv", "node_modules", "tests", "venv"}

    for path in PROJECT_ROOT.rglob("*.py"):
        if ignored_parts.intersection(path.relative_to(PROJECT_ROOT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for value in _content_disposition_candidates(node):
                if not _is_safe_content_disposition_value(value):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")

    assert violations == []
