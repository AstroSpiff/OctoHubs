import io
from urllib import error

import pytest

from scripts.octohubs_api_client import OctoHubsApiClient, OctoHubsApiError


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_client_sends_bearer_token_and_decodes_json(monkeypatch):
    observed = {}

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["auth"] = request.get_header("Authorization")
        observed["accept"] = request.get_header("Accept")
        return _FakeResponse(200, b'{"ok":true}')

    monkeypatch.setattr("scripts.octohubs_api_client.request.urlopen", fake_urlopen)

    response = OctoHubsApiClient("https://octohubs.example.test", "ohs_secret", timeout=4).get_status()

    assert response.status == 200
    assert response.payload == {"ok": True}
    assert observed == {
        "url": "https://octohubs.example.test/api/v1/system/status",
        "timeout": 4,
        "auth": "Bearer ohs_secret",
        "accept": "application/json",
    }


def test_client_reads_the_scope_filtered_external_catalog(monkeypatch):
    observed = {}

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["auth"] = request.get_header("Authorization")
        return _FakeResponse(200, b'{"paths":{"/api/v1/system/status":{}}}')

    monkeypatch.setattr("scripts.octohubs_api_client.request.urlopen", fake_urlopen)

    response = OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").get_catalog()

    assert response.payload == {"paths": {"/api/v1/system/status": {}}}
    assert observed == {
        "url": "https://octohubs.example.test/api/v1/external/openapi.json",
        "auth": "Bearer ohs_secret",
    }


def test_expect_denied_accepts_only_403(monkeypatch):
    def fake_urlopen(_request, timeout):
        raise error.HTTPError(
            "https://octohubs.example.test/api/v1/telegram/action",
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"API token senza permesso richiesto: write:configuration"}'),
        )

    monkeypatch.setattr("scripts.octohubs_api_client.request.urlopen", fake_urlopen)

    response = OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").expect_denied(
        "POST",
        "/api/v1/telegram/action",
        {"action": "bot.save", "data": {}},
    )

    assert response.status == 403
    assert response.payload["detail"].endswith("write:configuration")


def test_expect_denied_fails_when_request_is_allowed(monkeypatch):
    monkeypatch.setattr(
        "scripts.octohubs_api_client.request.urlopen",
        lambda _request, timeout: _FakeResponse(200, b'{"success":true}'),
    )

    with pytest.raises(OctoHubsApiError) as exc:
        OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").expect_denied(
            "POST",
            "/api/v1/telegram/action",
            {"action": "bot.save", "data": {}},
        )

    assert exc.value.status == 200
    assert "Expected HTTP 403" in str(exc.value)


def test_call_documented_checks_the_scope_filtered_catalog_before_calling(monkeypatch):
    observed = []

    def fake_urlopen(request, timeout):
        observed.append((request.full_url, request.get_method(), request.data))
        if request.full_url.endswith("/api/v1/external/openapi.json"):
            return _FakeResponse(
                200,
                b'{"paths":{"/api/v1/research/search-rules":{"put":{}}}}',
            )
        return _FakeResponse(200, b'{"success":true}')

    monkeypatch.setattr("scripts.octohubs_api_client.request.urlopen", fake_urlopen)

    response = OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").call_documented(
        "PUT",
        "/api/v1/research/search-rules",
        {"search_rules": {"min_seeders": 2}},
    )

    assert response.payload == {"success": True}
    assert observed == [
        ("https://octohubs.example.test/api/v1/external/openapi.json", "GET", None),
        (
            "https://octohubs.example.test/api/v1/research/search-rules",
            "PUT",
            b'{"search_rules": {"min_seeders": 2}}',
        ),
    ]


def test_call_documented_refuses_an_operation_not_visible_to_the_token(monkeypatch):
    monkeypatch.setattr(
        "scripts.octohubs_api_client.request.urlopen",
        lambda _request, timeout: _FakeResponse(200, b'{"paths":{"/api/v1/system/status":{"get":{}}}}'),
    )

    with pytest.raises(OctoHubsApiError, match="is not exposed"):
        OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").call_documented(
            "POST",
            "/api/v1/telegram/action",
            {"action": "bot.save", "data": {}},
        )


def test_verify_control_plane_only_calls_safe_reads_and_discovers_operations(monkeypatch):
    observed = []

    def fake_urlopen(request, timeout):
        observed.append((request.full_url, request.get_method()))
        if request.full_url.endswith("/api/v1/external/openapi.json"):
            return _FakeResponse(200, b'''{"paths":{
                "/api/v1/system/status":{"get":{"x-octohubs-operation-kind":"read"}},
                "/api/v1/emby/streams":{"get":{"x-octohubs-operation-kind":"read"}},
                "/api/v1/workflow/start":{"post":{"x-octohubs-operation-kind":"operation","x-octohubs-required-scope":"run:operations"}}
            }}''')
        return _FakeResponse(200, b'{"ok":true}')

    monkeypatch.setattr("scripts.octohubs_api_client.request.urlopen", fake_urlopen)

    result = OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").verify_control_plane()

    assert result.reads == [
        ("/api/v1/system/status", 200),
        ("/api/v1/emby/streams", 200),
    ]
    assert result.operations == [("POST", "/api/v1/workflow/start", "run:operations")]
    assert observed == [
        ("https://octohubs.example.test/api/v1/external/openapi.json", "GET"),
        ("https://octohubs.example.test/api/v1/system/status", "GET"),
        ("https://octohubs.example.test/api/v1/emby/streams", "GET"),
    ]


def test_verify_control_plane_requires_the_status_scope(monkeypatch):
    monkeypatch.setattr(
        "scripts.octohubs_api_client.request.urlopen",
        lambda _request, timeout: _FakeResponse(200, b'{"paths":{"/api/v1/emby/streams":{"get":{}}}}'),
    )

    with pytest.raises(OctoHubsApiError, match="system/status"):
        OctoHubsApiClient("https://octohubs.example.test", "ohs_secret").verify_control_plane()
