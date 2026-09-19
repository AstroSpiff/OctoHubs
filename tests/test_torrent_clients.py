"""Regression and contract tests for multi-client torrent dispatch."""

from __future__ import annotations

from typing import Any

import pytest

from services.torrent_clients import (
    normalize_submitted_torrent_clients,
    public_torrent_client_profiles,
    select_torrent_client,
    torrent_client_profiles,
)


def _profile(
    client_id: str,
    kind: str,
    *,
    default: bool = False,
    password: str = "secret",
) -> dict[str, Any]:
    return {
        "id": client_id,
        "name": client_id,
        "kind": kind,
        "url": "http://torrent.invalid",
        "username": "user",
        "password": password,
        "enabled": True,
        "is_default": default,
    }


def test_legacy_qbittorrent_settings_project_as_enabled_default_without_leaking_secret():
    config = {
        "QBITTORRENT_URL": "http://qb.invalid",
        "QBITTORRENT_USERNAME": "admin",
        "QBITTORRENT_PASSWORD": "legacy-canary",
    }

    profiles = torrent_client_profiles(config)
    public = public_torrent_client_profiles(config)

    assert profiles[0]["kind"] == "qbittorrent"
    assert profiles[0]["is_default"] is True
    assert public[0]["password_configured"] is True
    assert "legacy-canary" not in repr(public)


def test_submitted_profiles_preserve_omitted_secret_and_assign_one_default():
    current = {
        "TORRENT_CLIENTS": [_profile("home", "transmission", password="saved-canary")]
    }

    normalized = normalize_submitted_torrent_clients(
        [
            {
                "id": "home",
                "name": "Home",
                "kind": "transmission",
                "url": "http://transmission.invalid",
                "username": "operator",
                "enabled": True,
                "is_default": False,
            },
            {
                "id": "deluge",
                "name": "Deluge",
                "kind": "deluge",
                "url": "http://deluge.invalid",
                "password": "new-secret",
                "enabled": True,
                "is_default": False,
            },
        ],
        current,
    )

    assert normalized[0]["password"] == "saved-canary"
    assert [item["is_default"] for item in normalized] == [True, False]


def test_submitted_profiles_reject_multiple_defaults_and_duplicate_names():
    first = _profile("first", "qbittorrent", default=True)
    second = _profile("second", "deluge", default=True)
    with pytest.raises(ValueError, match="solo client torrent predefinito"):
        normalize_submitted_torrent_clients([first, second], {})

    second["is_default"] = False
    second["name"] = first["name"].upper()
    with pytest.raises(ValueError, match="nome univoco"):
        normalize_submitted_torrent_clients([first, second], {})


def test_client_selection_requires_enabled_configured_profile_and_honors_explicit_id():
    config = {
        "TORRENT_CLIENTS": [
            _profile("primary", "qbittorrent", default=True),
            _profile("secondary", "transmission"),
            {**_profile("disabled", "deluge"), "enabled": False},
        ]
    }

    assert select_torrent_client(config)["id"] == "primary"
    assert select_torrent_client(config, "secondary")["id"] == "secondary"
    assert select_torrent_client(config, "disabled") is None
    assert select_torrent_client(config, "missing") is None


class _Response:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.closed = False

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses: list[_Response]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_deluge_uses_web_login_connection_check_and_kind_specific_add(monkeypatch):
    from emby_runtime import api_clients_deluge

    session = _Session(
        [
            _Response({"error": None, "result": True}),
            _Response({"error": None, "result": True}),
            _Response({"error": None, "result": "torrent-hash"}),
        ]
    )
    monkeypatch.setattr(api_clients_deluge.requests, "Session", lambda: session)

    success, message = api_clients_deluge.send_to_deluge(
        "magnet:?xt=urn:btih:abc",
        _profile("deluge", "deluge"),
    )

    assert success is True
    assert message == "Torrent aggiunto a Deluge"
    assert [call["json"]["method"] for call in session.calls] == [
        "auth.login",
        "web.connected",
        "core.add_torrent_magnet",
    ]
    assert session.closed is True


def test_deluge_fails_closed_when_web_ui_is_not_connected(monkeypatch):
    from emby_runtime import api_clients_deluge

    session = _Session(
        [
            _Response({"error": None, "result": True}),
            _Response({"error": None, "result": False}),
        ]
    )
    monkeypatch.setattr(api_clients_deluge.requests, "Session", lambda: session)

    success, message = api_clients_deluge.send_to_deluge(
        "https://indexer.invalid/file.torrent",
        _profile("deluge", "deluge"),
    )

    assert success is False
    assert message == "Deluge Web non è collegato al daemon"
    assert len(session.calls) == 2


def test_transmission_retries_once_with_csrf_session_and_keeps_basic_auth(monkeypatch):
    from emby_runtime import api_clients_transmission

    session = _Session(
        [
            _Response({}, 409, {"X-Transmission-Session-Id": "csrf-token"}),
            _Response(
                {
                    "result": "success",
                    "arguments": {"torrent-added": {"name": "Example"}},
                }
            ),
        ]
    )
    monkeypatch.setattr(api_clients_transmission.requests, "Session", lambda: session)

    success, message = api_clients_transmission.send_to_transmission(
        "https://indexer.invalid/file.torrent",
        _profile("transmission", "transmission"),
    )

    assert success is True
    assert message == "Torrent aggiunto a Transmission: Example"
    assert session.calls[0]["url"].endswith("/transmission/rpc")
    assert session.calls[0]["auth"] == ("user", "secret")
    assert session.calls[1]["headers"] == {"X-Transmission-Session-Id": "csrf-token"}
    assert session.closed is True


def test_dispatch_uses_default_or_explicit_profile_without_cross_sending(monkeypatch):
    from services import torrent_dispatch

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        torrent_dispatch,
        "send_to_qbittorrent",
        lambda link, _config: calls.append(("qbittorrent", link)) or (True, "qb"),
    )
    monkeypatch.setattr(
        torrent_dispatch,
        "send_to_deluge",
        lambda link, _profile: calls.append(("deluge", link)) or (True, "deluge"),
    )
    config = {
        "TORRENT_CLIENTS": [
            _profile("qb", "qbittorrent", default=True),
            _profile("de", "deluge"),
        ]
    }

    assert torrent_dispatch.send_to_torrent_client("magnet:?xt=one", config) == (
        True,
        "qb",
    )
    assert torrent_dispatch.send_to_torrent_client("magnet:?xt=two", config, "de") == (
        True,
        "deluge",
    )
    assert calls == [("qbittorrent", "magnet:?xt=one"), ("deluge", "magnet:?xt=two")]


def test_search_send_delegates_cached_release_to_prowlarr(monkeypatch):
    from search import manager

    config = {"PROWLARR_URL": "https://prowlarr.invalid", "PROWLARR_API_KEY": "key"}
    observed = {}
    monkeypatch.setattr(manager, "load_config", lambda: (config, True))
    monkeypatch.setattr(
        manager,
        "grab_prowlarr_release",
        lambda release, received_config: observed.update(
            {"release": release, "config": received_config}
        )
        or (True, "Inviato"),
    )

    payload, status = manager._build_send_torrent_snapshot(
        {"prowlarr_release": {"indexerId": 7, "guid": "opaque-guid"}}
    )

    assert status == 200
    assert payload == {"success": True, "message": "Inviato"}
    assert observed == {
        "release": {"indexerId": 7, "guid": "opaque-guid"},
        "config": config,
    }


def test_search_send_rejects_missing_prowlarr_reference_before_network(monkeypatch):
    from search import manager

    config = {"PROWLARR_URL": "https://prowlarr.invalid", "PROWLARR_API_KEY": "key"}

    def send(*_args, **_kwargs):
        pytest.fail("network dispatch must not run")

    monkeypatch.setattr(manager, "load_config", lambda: (config, True))
    monkeypatch.setattr(manager, "grab_prowlarr_release", send)

    payload, status = manager._build_send_torrent_snapshot({})

    assert status == 400
    assert payload["success"] is False
    assert payload["message"] == "Risultato Prowlarr mancante o scaduto"
