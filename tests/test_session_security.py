from web.session_security import (
    environment_flag,
    is_insecure_session_secret,
    resolved_session_secret,
    session_timeout_seconds,
)


def test_placeholder_session_secrets_are_never_accepted():
    assert is_insecure_session_secret("") is True
    assert is_insecure_session_secret("change-this-secret-key") is True
    assert is_insecure_session_secret("your-secret-key-here") is True
    assert is_insecure_session_secret("secure-session-key") is False


def test_missing_session_secret_gets_a_safe_ephemeral_value():
    secret, generated = resolved_session_secret({}, token_factory=lambda _size: "generated")

    assert secret == "generated"
    assert generated is True


def test_configured_session_secret_is_preserved():
    secret, generated = resolved_session_secret({"SECRET_KEY": "kept-secret"})

    assert secret == "kept-secret"
    assert generated is False


def test_environment_flags_only_accept_explicit_truthy_values():
    assert environment_flag({}, "SESSION_COOKIE_SECURE", default=True) is True
    assert environment_flag({"SESSION_COOKIE_SECURE": "false"}, "SESSION_COOKIE_SECURE", default=True) is False
    assert environment_flag({"SESSION_COOKIE_SECURE": "yes"}, "SESSION_COOKIE_SECURE") is True


def test_session_timeout_uses_minutes_and_allows_a_browser_session():
    assert session_timeout_seconds({}) == 3600
    assert session_timeout_seconds({"SESSION_TIMEOUT_MINUTES": "15"}) == 900
    assert session_timeout_seconds({"SESSION_TIMEOUT_MINUTES": "0"}) is None
    assert session_timeout_seconds({"SESSION_TIMEOUT_MINUTES": "invalid"}) == 3600
