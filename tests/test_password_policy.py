"""Shared bcrypt password byte-limit coverage."""

import argparse

import pytest

from core.password_policy import PasswordTooLongError, bcrypt_password_bytes


@pytest.mark.parametrize(
    ("password", "expected_bytes"),
    (
        ("è" * 35 + "a", 71),
        ("è" * 36, 72),
    ),
)
def test_bcrypt_password_policy_accepts_up_to_72_utf8_bytes(password, expected_bytes):
    assert len(bcrypt_password_bytes(password)) == expected_bytes


def test_bcrypt_password_policy_rejects_73_utf8_bytes():
    with pytest.raises(PasswordTooLongError, match="72 byte UTF-8"):
        bcrypt_password_bytes("è" * 36 + "a")


def test_user_creation_and_password_update_fail_cleanly_over_limit(tmp_path):
    from core import auth

    auth.init_auth(
        create_default_admin=False,
        database_url=f"sqlite:///{tmp_path / 'auth.db'}",
        allow_sqlite_for_tests=True,
    )
    user = auth.create_user("existing", "existing-password")
    assert user is not None

    assert auth.create_user("over-limit", "è" * 36 + "a") is None
    assert auth.update_user_password(user, "è" * 36 + "a") is False
    assert auth.get_user_by_username("over-limit") is None
    assert auth.get_user_by_username("existing").check_password("existing-password") is True


def test_cli_password_arguments_use_the_shared_byte_limit():
    from scripts.manage_users import _password_argument

    assert _password_argument("è" * 36) == "è" * 36
    with pytest.raises(argparse.ArgumentTypeError, match="72 byte UTF-8"):
        _password_argument("è" * 36 + "a")
