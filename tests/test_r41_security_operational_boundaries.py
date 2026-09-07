"""Class-level security and resource-lifecycle gates introduced by R41."""

from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _json_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_manage_users_redacts_bootstrap_credentials(monkeypatch, capsys):
    from scripts import manage_users

    def fail_bootstrap():
        raise RuntimeError(
            "postgresql://operator:r41-password-canary@db.example/octohubs"
            "?token=r41-token-canary"
        )

    monkeypatch.setattr(manage_users, "_bootstrap_app", fail_bootstrap)
    assert manage_users.main(["list"]) == 1
    stderr = capsys.readouterr().err
    assert "r41-password-canary" not in stderr
    assert "r41-token-canary" not in stderr
    assert "[REDACTED]" in stderr


def _is_main_guard(node: ast.If) -> bool:
    return (
        isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and any(
            isinstance(comparator, ast.Constant) and comparator.value == "__main__"
            for comparator in node.test.comparators
        )
    )


def _stderr_print(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "print"
        and any(
            keyword.arg == "file"
            and isinstance(keyword.value, ast.Attribute)
            and isinstance(keyword.value.value, ast.Name)
            and keyword.value.value.id == "sys"
            and keyword.value.attr == "stderr"
            for keyword in call.keywords
        )
    )


def _uses_canonical_redaction(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id
        in {"sanitize_diagnostic_text", "format_exception_for_log", "redact_mapping_for_log"}
        for child in ast.walk(node)
    )


def _is_exception_type_name(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__name__"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "type"
    )


def _safe_stderr_argument(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) or _uses_canonical_redaction(node):
        return True
    formatted_values = [
        child for child in ast.walk(node) if isinstance(child, ast.FormattedValue)
    ]
    return bool(formatted_values) and all(
        _uses_canonical_redaction(item.value) or _is_exception_type_name(item.value)
        for item in formatted_values
    )


def test_operator_entrypoint_exception_stderr_uses_canonical_redaction():
    """Class gate: every Python entrypoint redacts dynamic exception stderr."""
    violations: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".git", "node_modules", "tests", "venv"} for part in path.parts):
            continue
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        if not any(isinstance(node, ast.If) and _is_main_guard(node) for node in ast.walk(tree)):
            continue
        for handler in (
            node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
        ):
            for node in handler.body:
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call) or not _stderr_print(call):
                        continue
                    for argument in call.args:
                        if not _safe_stderr_argument(argument):
                            violations.append(f"{relative_path}:{call.lineno}")
    assert violations == []


def test_external_api_client_redacts_exception_and_payload(monkeypatch, capsys):
    from scripts import octohubs_api_client

    monkeypatch.setenv("OCTOHUBS_API_TOKEN", "test-token")
    monkeypatch.setattr(
        octohubs_api_client,
        "run",
        lambda _args: (_ for _ in ()).throw(
            octohubs_api_client.OctoHubsApiError(
                "postgresql://operator:r41-client-password@db.example/octohubs"
                "?token=r41-client-query-token",
                payload={
                    "password": "r41-payload-password",
                    "detail": "https://user:r41-url-password@example.test/path?api_key=r41-api-key",
                },
            )
        ),
    )

    assert octohubs_api_client.main(["status"]) == 1
    stderr = capsys.readouterr().err
    for sentinel in (
        "r41-client-password",
        "r41-client-query-token",
        "r41-payload-password",
        "r41-url-password",
        "r41-api-key",
    ):
        assert sentinel not in stderr
    assert "[REDACTED]" in stderr


def test_saved_password_response_is_never_cacheable():
    from emby_users.routes import api_emby_users_password_get, init_emby_user_routes

    manager = SimpleNamespace(
        password_manager=SimpleNamespace(
            get_password_info=lambda **_kwargs: {
                "ok": True,
                "saved": True,
                "password": "saved-password",
            }
        )
    )
    init_emby_user_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    request = SimpleNamespace(state=SimpleNamespace(auth_method="session"))

    response = asyncio.run(
        api_emby_users_password_get(request, user=SimpleNamespace(role="admin"))
    )

    assert _json_body(response)["password"] == "saved-password"
    assert response.headers["cache-control"] == "no-store"


class _Response:
    status_code = 200
    headers: dict[str, str] = {}
    content = b"Ok."

    def iter_content(self, chunk_size=0):
        del chunk_size
        yield self.content

    def close(self):
        return None


class _TrackedSession:
    def __init__(
        self,
        *,
        failure: BaseException | None = None,
        close_failure: BaseException | None = None,
    ):
        self.closed = False
        self.failure = failure
        self.close_failure = close_failure

    def post(self, *_args, **_kwargs):
        if self.failure is not None:
            raise self.failure
        return _Response()

    def get(self, *_args, **_kwargs):
        return SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "application/json"},
            content=b"[]",
            iter_content=lambda chunk_size=0: iter((b"[]",)),
            close=lambda: None,
        )

    def close(self):
        self.closed = True
        if self.close_failure is not None:
            raise self.close_failure


@pytest.mark.parametrize(
    "operation,args",
    [
        (
            "single",
            (
                "magnet:?xt=urn:btih:example",
                {
                    "QBITTORRENT_URL": "https://qb.example",
                    "QBITTORRENT_USERNAME": "user",
                    "QBITTORRENT_PASSWORD": "password",
                },
            ),
        ),
        (
            "batch",
            (
                ["magnet:?xt=urn:btih:example"],
                {
                    "QBITTORRENT_URL": "https://qb.example",
                    "QBITTORRENT_USERNAME": "user",
                    "QBITTORRENT_PASSWORD": "password",
                },
            ),
        ),
    ],
)
def test_qbittorrent_send_sessions_close_on_success(monkeypatch, operation, args):
    from emby_runtime import api_clients_qbittorrent

    session = _TrackedSession()
    monkeypatch.setattr(api_clients_qbittorrent.requests, "Session", lambda: session)
    monkeypatch.setattr(api_clients_qbittorrent.time, "sleep", lambda *_args: None)

    if operation == "single":
        api_clients_qbittorrent.send_to_qbittorrent(*args, max_retries=0)
    else:
        api_clients_qbittorrent.send_to_qbittorrent_batch(*args, max_retries=0)
    assert session.closed is True


def test_qbittorrent_send_session_closes_on_base_exception(monkeypatch):
    from emby_runtime import api_clients_qbittorrent

    primary = KeyboardInterrupt("cancelled")
    session = _TrackedSession(failure=primary)
    monkeypatch.setattr(api_clients_qbittorrent.requests, "Session", lambda: session)

    with pytest.raises(KeyboardInterrupt) as caught:
        api_clients_qbittorrent.send_to_qbittorrent(
            "magnet:?xt=urn:btih:example",
            {
                "QBITTORRENT_URL": "https://qb.example",
                "QBITTORRENT_USERNAME": "user",
                "QBITTORRENT_PASSWORD": "password",
            },
            max_retries=0,
        )

    assert caught.value is primary
    assert session.closed is True


@pytest.mark.parametrize(
    "failure",
    [None, requests.ConnectionError("offline"), KeyboardInterrupt("cancelled")],
)
def test_qbittorrent_ping_session_always_closes(monkeypatch, failure):
    from emby_runtime import api_clients_ping

    session = _TrackedSession(failure=failure)
    monkeypatch.setattr(api_clients_ping.requests, "Session", lambda: session)
    config = {
        "QBITTORRENT_URL": "https://qb.example",
        "QBITTORRENT_USERNAME": "user",
        "QBITTORRENT_PASSWORD": "password",
    }
    if isinstance(failure, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            api_clients_ping._ping_qbittorrent(config)
    else:
        api_clients_ping._ping_qbittorrent(config)
    assert session.closed is True


@pytest.mark.parametrize("operation", ["single", "batch", "ping"])
@pytest.mark.parametrize("primary_kind", ["ordinary", "base"])
@pytest.mark.parametrize("cleanup_kind", ["ordinary", "base"])
def test_owned_session_cleanup_never_masks_primary(
    monkeypatch,
    operation,
    primary_kind,
    cleanup_kind,
):
    from emby_runtime import api_clients_ping, api_clients_qbittorrent

    primary = (
        requests.ConnectionError("primary ordinary")
        if primary_kind == "ordinary"
        else KeyboardInterrupt("primary base")
    )
    cleanup = (
        RuntimeError("cleanup ordinary")
        if cleanup_kind == "ordinary"
        else KeyboardInterrupt("cleanup base")
    )
    session = _TrackedSession(failure=primary, close_failure=cleanup)
    config = {
        "QBITTORRENT_URL": "https://qb.example",
        "QBITTORRENT_USERNAME": "user",
        "QBITTORRENT_PASSWORD": "password",
    }
    monkeypatch.setattr(api_clients_ping.requests, "Session", lambda: session)
    monkeypatch.setattr(api_clients_qbittorrent.requests, "Session", lambda: session)
    monkeypatch.setattr(api_clients_qbittorrent.time, "sleep", lambda *_args: None)

    def invoke():
        if operation == "single":
            return api_clients_qbittorrent.send_to_qbittorrent(
                "magnet:?xt=urn:btih:example", config, max_retries=0
            )
        if operation == "batch":
            return api_clients_qbittorrent.send_to_qbittorrent_batch(
                ["magnet:?xt=urn:btih:example"], config, max_retries=0
            )
        return api_clients_ping._ping_qbittorrent(config)

    if primary_kind == "base":
        with pytest.raises(KeyboardInterrupt) as caught:
            invoke()
        assert caught.value is primary
    else:
        result = invoke()
        assert result[0] is False
    assert session.closed is True


def test_release_gate_audits_runtime_and_development_dependencies():
    workflow = (PROJECT_ROOT / ".github/workflows/release-gate.yml").read_text()
    checklist_en = (PROJECT_ROOT / "docs/RELEASE_CHECKLIST.md").read_text()
    checklist_it = (PROJECT_ROOT / "docs/RELEASE_CHECKLIST_ita.md").read_text()

    for document in (workflow, checklist_en, checklist_it):
        assert "npm audit --omit=dev --audit-level=high" in document
        assert "npm audit --audit-level=high" in document
        assert "pip_audit -r requirements.txt" in document
        assert "pip_audit -r requirements-dev.txt" in document
