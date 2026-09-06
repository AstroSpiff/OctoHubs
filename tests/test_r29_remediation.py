from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from core.log_sanitization import sanitize_diagnostic_text
from core.pagination import PaginationGuard, PaginationLimitError
from emby_collections.sources_trakt import _fetch_trakt_list_items
from emby_users.settings_apply import SettingsApplyMixin


class _SettingsPersistenceHarness(SettingsApplyMixin):
    storage = object()

    def _build_library_group_index(self):
        return [], {}, {}, {}

    def _normalize_settings_payload(self, settings, **_kwargs):
        return {**settings, "libraries": settings.get("libraries") or {"items": [], "groups": {}}}

    def _apply_settings_to_user(self, *_args, **_kwargs):
        return True, True, True

    def settings_user_key(self, server_id, user_id):
        return f"{server_id}:{user_id}"

    def _save_settings_entry(self, *_args):
        raise RuntimeError("database unavailable secret=CANARY")


def test_diagnostic_text_is_redacted_single_line_and_bounded():
    canary = "safe\n[FORGED] token=super-secret\x00" + "x" * 400

    sanitized = sanitize_diagnostic_text(canary, max_length=80)

    assert "\n" not in sanitized
    assert "\x00" not in sanitized
    assert "super-secret" not in sanitized
    assert len(sanitized) <= 80


@pytest.mark.parametrize(
    ("function_name", "payload"),
    [
        ("search_prowlarr", [{"title": "safe\n[FORGED] auth ok", "guid": "opaque\nGUID"}]),
        ("search_jackett", {"Results": [{"Title": "safe\n[FORGED] auth ok", "Guid": "opaque\nGUID"}]}),
    ],
)
def test_indexer_diagnostics_cannot_forge_log_lines(function_name, payload, capsys):
    from emby_runtime import api_clients_indexers

    class _Response:
        status_code = 200
        text = "ok"
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    config = {
        "PROWLARR_URL": "https://prowlarr.example",
        "PROWLARR_API_KEY": "secret",
        "JACKETT_URL": "https://jackett.example",
        "JACKETT_API_KEY": "secret",
    }
    with patch("emby_runtime.api_clients_indexers.requests.get", return_value=_Response()):
        getattr(api_clients_indexers, function_name)("query", "movie", config)

    output = capsys.readouterr().out
    assert "\n[FORGED]" not in output
    assert "opaque\nGUID" not in output


def test_settings_remote_success_and_local_failure_returns_partial_result():
    result = _SettingsPersistenceHarness()._update_user_settings_guarded(
        "server-a", "user-a", {"config": {"RememberAudioSelections": True}}
    )

    assert result["ok"] is False
    assert result["status"] == "partial"
    assert result["applied"] == 1
    assert result["reconciliation_required"] is True


def test_pagination_guard_rejects_a_repeated_nonempty_page():
    guard = PaginationGuard(max_pages=10, max_items=100)
    guard.observe([{"id": 1}])

    with pytest.raises(PaginationLimitError, match="pagina ripetuta"):
        guard.observe([{"id": 1}])


def test_trakt_list_stops_on_provider_repeating_the_same_full_page():
    class _Client:
        def __init__(self):
            self.calls = 0

        def _request(self, *_args, **_kwargs):
            self.calls += 1
            return [{"movie": {"ids": {"tmdb": index}}} for index in range(1, 101)]

    client = _Client()
    with patch("emby_collections.sources_trakt._ensure_trakt_manager", return_value=client):
        with pytest.raises(PaginationLimitError, match="pagina ripetuta"):
            _fetch_trakt_list_items("popular")

    assert client.calls == 2


def test_dead_pytrakt_runtime_and_dependency_are_removed():
    root = pathlib.Path(__file__).resolve().parents[1]

    assert not (root / "core" / "trakt_manager.py").exists()
    assert "pytrakt" not in (root / "requirements.in").read_text(encoding="utf-8").lower()
    assert "pytrakt" not in (root / "requirements.txt").read_text(encoding="utf-8").lower()
