"""Password encryption secret, versioning, and rotation regressions."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from emby_users.password_crypto import (
    PasswordCipher,
    PasswordCiphertextError,
    PasswordSecretError,
    is_insecure_password_secret,
    password_cipher_from_environment,
    rotate_stored_password_ciphertexts,
)


class _PasswordStorage:
    def __init__(self, entries=None):
        self.entries = {entry["group_id"]: dict(entry) for entry in entries or []}
        self.saved = []

    def get_group_passwords(self):
        return list(self.entries.values())

    def replace_group_password_ciphertexts(self, updates):
        self.saved.extend(updates)
        for group_id, password_enc in updates:
            self.entries[group_id] = {"group_id": group_id, "password_enc": password_enc}


def _unversioned_token(secret: str, plaintext: str) -> str:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    cipher = Fernet(base64.urlsafe_b64encode(digest))
    return cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")


@pytest.mark.parametrize(
    "secret",
    ["", "change-this-secret-key", "change-this-password-secret", "too-short"],
)
def test_password_secret_rejects_missing_placeholders_and_short_values(secret):
    assert is_insecure_password_secret(secret)
    with pytest.raises(PasswordSecretError):
        password_cipher_from_environment({"PASSWORD_SECRET": secret})


@pytest.mark.parametrize("secret", ["a" * 32, "abc" * 20])
def test_password_secret_rejects_long_but_trivial_values(secret):
    assert is_insecure_password_secret(secret)
    with pytest.raises(PasswordSecretError):
        password_cipher_from_environment({"PASSWORD_SECRET": secret})


def test_weak_previous_secret_remains_available_only_for_explicit_rotation():
    previous_secret = "a" * 32
    previous_cipher = PasswordCipher(previous_secret)
    storage = _PasswordStorage(
        [{"group_id": "group-1", "password_enc": previous_cipher.encrypt("secret")}]
    )
    current_cipher = password_cipher_from_environment(
        {
            "PASSWORD_SECRET": "current-password-secret-that-is-long-enough",
            "PASSWORD_SECRET_PREVIOUS": previous_secret,
        }
    )

    assert rotate_stored_password_ciphertexts(storage, current_cipher) == 1
    assert current_cipher.decrypt(storage.saved[0][1]) == ("secret", False)


def test_password_cipher_uses_versioned_ciphertexts():
    cipher = password_cipher_from_environment(
        {"PASSWORD_SECRET": "current-password-secret-that-is-long-enough"}
    )

    token = cipher.encrypt("not-logged-password")
    plaintext, needs_rotation = cipher.decrypt(token)

    assert token.startswith("v1:")
    assert "not-logged-password" not in token
    assert plaintext == "not-logged-password"
    assert needs_rotation is False


def test_unversioned_ciphertexts_are_rejected_even_with_a_previous_key():
    previous_secret = "previous-password-secret-that-is-long-enough"
    storage = _PasswordStorage(
        [
            {
                "group_id": "group-1",
                "password_enc": _unversioned_token(previous_secret, "unversioned-password"),
            }
        ]
    )
    cipher = password_cipher_from_environment(
        {
            "PASSWORD_SECRET": "current-password-secret-that-is-long-enough",
            "PASSWORD_SECRET_PREVIOUS": previous_secret,
        }
    )

    with pytest.raises(PasswordCiphertextError):
        rotate_stored_password_ciphertexts(storage, cipher)
    assert storage.saved == []


def test_previous_secret_rotates_versioned_ciphertexts_to_the_current_key():
    previous_secret = "previous-password-secret-that-is-long-enough"
    previous_cipher = password_cipher_from_environment(
        {"PASSWORD_SECRET": previous_secret}
    )
    storage = _PasswordStorage(
        [
            {
                "group_id": "group-1",
                "password_enc": previous_cipher.encrypt("previous-version-password"),
            }
        ]
    )
    current_cipher = password_cipher_from_environment(
        {
            "PASSWORD_SECRET": "current-password-secret-that-is-long-enough",
            "PASSWORD_SECRET_PREVIOUS": previous_secret,
        }
    )

    assert rotate_stored_password_ciphertexts(storage, current_cipher) == 1
    plaintext, needs_rotation = current_cipher.decrypt(storage.saved[0][1])
    assert plaintext == "previous-version-password"
    assert needs_rotation is False


def test_rotation_validates_every_ciphertext_before_writing():
    storage = _PasswordStorage(
        [
            {"group_id": "group-1", "password_enc": "not-a-fernet-token"},
            {"group_id": "group-2", "password_enc": "also-invalid"},
        ]
    )
    cipher = password_cipher_from_environment(
        {"PASSWORD_SECRET": "current-password-secret-that-is-long-enough"}
    )

    with pytest.raises(PasswordCiphertextError, match="PASSWORD_SECRET_PREVIOUS"):
        rotate_stored_password_ciphertexts(storage, cipher)

    assert storage.saved == []


def test_rotation_storage_failure_is_fatal_and_does_not_fall_back_to_row_writes():
    previous_secret = "previous-password-secret-that-is-long-enough"
    previous_cipher = password_cipher_from_environment({"PASSWORD_SECRET": previous_secret})
    original = previous_cipher.encrypt("previous-password")

    class _FailingAtomicStorage(_PasswordStorage):
        def replace_group_password_ciphertexts(self, updates):
            self.saved.append(("attempted-batch", len(updates)))
            raise RuntimeError("database commit failed")

        def save_group_password(self, _group_id, _password_enc):
            raise AssertionError("row-by-row fallback must never run")

    storage = _FailingAtomicStorage(
        [{"group_id": "group-1", "password_enc": original}]
    )
    cipher = password_cipher_from_environment(
        {
            "PASSWORD_SECRET": "current-password-secret-that-is-long-enough",
            "PASSWORD_SECRET_PREVIOUS": previous_secret,
        }
    )

    with pytest.raises(PasswordCiphertextError, match="annullata senza modifiche"):
        rotate_stored_password_ciphertexts(storage, cipher)

    assert storage.entries["group-1"]["password_enc"] == original


def test_application_factory_fails_before_bootstrap_without_password_secret(monkeypatch):
    import runtime.app_setup as app_setup

    monkeypatch.delenv("PASSWORD_SECRET", raising=False)
    monkeypatch.delenv("PASSWORD_SECRET_PREVIOUS", raising=False)
    monkeypatch.setattr(app_setup, "load_config_env_file", lambda: None)

    with pytest.raises(PasswordSecretError, match="PASSWORD_SECRET"):
        app_setup.create_app()
