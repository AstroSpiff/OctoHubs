"""Regression coverage for the backend findings fixed after review R14."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from emby_runtime.transcode_guard_api_models import TranscodeGuardSettingsRequest
from emby_runtime.transcode_guard_validation import (
    MAX_TRANSCODE_GUARD_PERSISTED_BYTES,
    MAX_TRANSCODE_GUARD_RULE_DEPTH,
    MAX_TRANSCODE_GUARD_RULES,
    validate_transcode_guard_persisted_size,
)


CANARY = "r14-sensitive-log-canary"
SECRET_ERROR = RuntimeError(
    f"postgresql://user:{CANARY}@db.local/octohubs?token={CANARY}"
)


def _rule_tree(depth: int) -> dict:
    node = {"type": "rule", "enabled": False}
    for _index in range(depth - 1):
        node = {"type": "group", "children": [node]}
    return node


def test_transcode_guard_request_model_is_strict_and_bounded():
    accepted = TranscodeGuardSettingsRequest.model_validate(
        {
            "enabled": True,
            "poll_interval_seconds": 5,
            "rules": [
                {
                    "id": "rule-1",
                    "name": "Regola",
                    "type": "rule",
                    "enabled": False,
                    "server_ids": ["server-1"],
                    "children": [],
                }
            ],
        },
        strict=True,
    )

    assert accepted.rules is not None
    assert accepted.rules[0].server_ids == ["server-1"]
    at_limit = TranscodeGuardSettingsRequest.model_validate(
        {"rules": [{"enabled": False} for _index in range(MAX_TRANSCODE_GUARD_RULES)]},
        strict=True,
    )
    assert at_limit.rules is not None
    assert len(at_limit.rules) == MAX_TRANSCODE_GUARD_RULES

    with pytest.raises(ValidationError):
        TranscodeGuardSettingsRequest.model_validate({"enabled": "false"}, strict=True)
    with pytest.raises(ValidationError):
        TranscodeGuardSettingsRequest.model_validate({"unexpected": True}, strict=True)
    with pytest.raises(ValidationError, match="troppe regole"):
        TranscodeGuardSettingsRequest.model_validate(
            {"rules": [{} for _index in range(MAX_TRANSCODE_GUARD_RULES + 1)]},
            strict=True,
        )


def test_transcode_guard_preflight_rejects_count_and_depth_before_expansion():
    from emby_runtime import transcode_guard_rules

    with patch.object(transcode_guard_rules, "normalize_transcode_guard_rule") as normalize_rule:
        with pytest.raises(ValueError, match="troppe regole"):
            transcode_guard_rules.normalize_transcode_guard_settings(
                {"rules": [{} for _index in range(MAX_TRANSCODE_GUARD_RULES + 1)]}
            )
    normalize_rule.assert_not_called()

    accepted = transcode_guard_rules.normalize_transcode_guard_settings(
        {"rules": [_rule_tree(MAX_TRANSCODE_GUARD_RULE_DEPTH)]}
    )
    assert len(accepted["rules"]) == 1

    with pytest.raises(ValueError, match="troppo profondi"):
        transcode_guard_rules.normalize_transcode_guard_settings(
            {"rules": [_rule_tree(MAX_TRANSCODE_GUARD_RULE_DEPTH + 1)]}
        )


def test_transcode_guard_persisted_size_is_rejected_without_truncation():
    oversized = {"message_text": "x" * MAX_TRANSCODE_GUARD_PERSISTED_BYTES}

    with pytest.raises(ValueError, match="dimensione consentita"):
        validate_transcode_guard_persisted_size(oversized)

    assert len(oversized["message_text"]) == MAX_TRANSCODE_GUARD_PERSISTED_BYTES


def test_transcode_guard_service_checks_size_before_storage_write(monkeypatch):
    from emby_runtime import transcode_guard_validation
    from emby_runtime.transcode_guard import TranscodeGuardService

    class Storage:
        def __init__(self):
            self.values = {}

        def get_key_value(self, key):
            return self.values.get(key)

        def set_key_value(self, key, value):
            self.values[key] = value

    storage = Storage()
    service = TranscodeGuardService(storage_provider=lambda: storage)
    monkeypatch.setattr(transcode_guard_validation, "MAX_TRANSCODE_GUARD_PERSISTED_BYTES", 1)

    with pytest.raises(ValueError, match="dimensione consentita"):
        service.save_settings({"enabled": False, "rules": [{"enabled": False}]})

    assert storage.values == {}


def test_requests_summary_logs_sanitized_traceback(monkeypatch, caplog, capsys):
    from services import requests_summary

    def fail_requests(*_args, **_kwargs):
        raise SECRET_ERROR

    monkeypatch.setattr(requests_summary, "get_jellyseerr_requests", fail_requests)
    capsys.readouterr()
    with caplog.at_level(logging.ERROR, logger=requests_summary.__name__), pytest.raises(RuntimeError):
        requests_summary._summarize_requests_for_dashboard(
            {"JELLYSEERR_URL": "https://jellyseerr.invalid"}
        )

    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    assert CANARY not in caplog.text
    assert caplog.text == ""


def test_justwatch_initialization_logs_sanitized_traceback(monkeypatch, caplog, capsys):
    from core import integrations

    def fail_manager(_settings):
        raise SECRET_ERROR

    monkeypatch.setattr(integrations, "_active_justwatch_settings", lambda: {"LOCALE": "it_IT"})
    monkeypatch.setattr(integrations, "_justwatch_enabled", lambda _settings: True)
    monkeypatch.setattr(integrations, "_get_justwatch_manager", fail_manager)
    capsys.readouterr()
    with caplog.at_level(logging.ERROR, logger=integrations.__name__):
        integrations._log_justwatch_status()

    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    assert CANARY not in caplog.text
    assert "Traceback" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "[REDACTED]" in caplog.text


@pytest.mark.anyio
async def test_streaming_generation_logs_sanitized_traceback(monkeypatch, caplog, capsys):
    from search import streaming

    class ExplodingTmdbId:
        def __int__(self):
            raise SECRET_ERROR

    class WebSocket:
        client_state = WebSocketState.CONNECTED

        async def send_json(self, _payload):
            return None

    backend = SimpleNamespace(save_manual_search=lambda _payload: None)
    monkeypatch.setattr("core.config_manager._ensure_db_backend", lambda: backend)
    capsys.readouterr()
    with caplog.at_level(logging.ERROR, logger=streaming.__name__):
        await streaming.search_streaming_parallel(
            query_variants=["Titolo"],
            search_types=["movie"],
            selected_indexers=set(),
            config={"SEARCH_RULES": {}},
            websocket=WebSocket(),
            session_id="r14-log-test",
            owner_id=41,
            use_jellyseerr_logic=True,
            tmdb_id=ExplodingTmdbId(),
        )

    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert CANARY not in captured.err
    assert CANARY not in caplog.text
    assert "Traceback" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "[REDACTED]" in caplog.text
