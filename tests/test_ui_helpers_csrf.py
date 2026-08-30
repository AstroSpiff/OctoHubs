from types import SimpleNamespace

from web.ui_helpers import get_csrf_token, validate_csrf


def _request(session: dict | None = None, headers: dict | None = None):
    return SimpleNamespace(session=session or {}, headers=headers or {}, state=SimpleNamespace())


def test_csrf_token_rotates_after_its_configured_lifetime(monkeypatch):
    values = iter(["first-token", "second-token"])
    monkeypatch.setattr("web.ui_helpers.generate_csrf_token", lambda: next(values))
    monkeypatch.setattr("web.ui_helpers.time.time", lambda: 100.0)
    monkeypatch.setenv("CSRF_TIME_LIMIT_SECONDS", "60")
    request = _request()

    first_token = get_csrf_token(request)
    assert validate_csrf(request, first_token) is True

    monkeypatch.setattr("web.ui_helpers.time.time", lambda: 161.0)
    second_token = get_csrf_token(request)

    assert second_token == "second-token"
    assert validate_csrf(request, first_token) is False
    assert validate_csrf(request, second_token) is True


def test_csrf_token_from_a_previous_session_format_is_rejected(monkeypatch):
    monkeypatch.setattr("web.ui_helpers.time.time", lambda: 100.0)
    request = _request({"_csrf_token": "old-token"})

    assert validate_csrf(request, "old-token") is False


def test_api_token_auth_bypasses_browser_csrf_after_authentication():
    request = _request()
    request.state.auth_method = "api_token"

    assert validate_csrf(request, None) is True
