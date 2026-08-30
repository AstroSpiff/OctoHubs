from types import SimpleNamespace


def test_missing_and_inactive_users_still_perform_one_bcrypt_check(monkeypatch):
    from web import login_security

    checked_hashes = []

    def _checkpw(_candidate, password_hash):
        checked_hashes.append(password_hash)
        return False

    monkeypatch.setattr(login_security.bcrypt, "checkpw", _checkpw)

    assert login_security.login_password_matches(None, "password") is False
    assert login_security.login_password_matches(
        SimpleNamespace(is_active=False, password_hash="$2b$12$unused"),
        "password",
    ) is False

    assert checked_hashes == [
        login_security._DUMMY_PASSWORD_HASH,
        login_security._DUMMY_PASSWORD_HASH,
    ]


def test_active_user_password_check_uses_the_stored_hash(monkeypatch):
    from web import login_security

    stored_hash = "$2b$12$oyRhoXUPOLd3r40DAx0Tg.qTxruvtdsIv17rrsU/Ourr0MnoWBPX2"
    checked_hashes = []

    def _checkpw(_candidate, password_hash):
        checked_hashes.append(password_hash)
        return True

    monkeypatch.setattr(login_security.bcrypt, "checkpw", _checkpw)
    user = SimpleNamespace(is_active=True, password_hash=stored_hash)

    assert login_security.login_password_matches(user, "password") is True
    assert checked_hashes == [stored_hash.encode("utf-8")]


def test_overlong_password_still_pays_bcrypt_cost_and_fails(monkeypatch):
    from web import login_security

    checked_candidates = []

    def _checkpw(candidate, _password_hash):
        checked_candidates.append(candidate)
        return True

    monkeypatch.setattr(login_security.bcrypt, "checkpw", _checkpw)
    user = SimpleNamespace(is_active=True, password_hash=login_security._DUMMY_PASSWORD_HASH.decode())

    assert login_security.login_password_matches(user, "è" * 37) is False
    assert checked_candidates == [login_security._DUMMY_PASSWORD]


def test_login_limiter_applies_identity_and_ip_windows():
    from web.login_security import LoginAttemptLimiter

    now = [100.0]
    limiter = LoginAttemptLimiter(
        window_seconds=60,
        per_ip_attempts=3,
        per_identity_attempts=2,
        clock=lambda: now[0],
    )

    assert limiter.consume("192.0.2.1", "alice").allowed is True
    assert limiter.consume("192.0.2.1", "alice").allowed is True
    identity_block = limiter.consume("192.0.2.1", "alice")
    assert identity_block.allowed is False
    assert identity_block.retry_after_seconds == 60

    assert limiter.consume("192.0.2.1", "bob").allowed is True
    assert limiter.consume("192.0.2.1", "carol").allowed is False

    now[0] += 61
    assert limiter.consume("192.0.2.1", "alice").allowed is True


def test_login_client_address_only_trusts_proxy_header_when_enabled(monkeypatch):
    from web.login_security import login_client_address

    request = SimpleNamespace(
        headers={"X-Real-IP": "198.51.100.9"},
        client=SimpleNamespace(host="172.18.0.2"),
    )
    monkeypatch.delenv("LOGIN_TRUST_PROXY_HEADERS", raising=False)
    assert login_client_address(request) == "172.18.0.2"

    monkeypatch.setenv("LOGIN_TRUST_PROXY_HEADERS", "true")
    assert login_client_address(request) == "198.51.100.9"
