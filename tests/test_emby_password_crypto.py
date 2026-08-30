"""Password encryption secret, versioning, and rotation regressions."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from emby_users.password_crypto import (
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

    def save_group_password(self, group_id, password_enc):
        self.saved.append((group_id, password_enc))
        self.entries[group_id] = {"group_id": group_id, "password_enc": password_enc}


def _legacy_token(secret: str, plaintext: str) -> str:
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


def test_previous_secret_rotates_legacy_ciphertexts_to_the_current_key():
    previous_secret = "previous-password-secret-that-is-long-enough"
    storage = _PasswordStorage(
        [
            {
                "group_id": "group-1",
                "password_enc": _legacy_token(previous_secret, "legacy-password"),
            }
        ]
    )
    cipher = password_cipher_from_environment(
        {
            "PASSWORD_SECRET": "current-password-secret-that-is-long-enough",
            "PASSWORD_SECRET_PREVIOUS": previous_secret,
        }
    )

    assert rotate_stored_password_ciphertexts(storage, cipher) == 1
    assert storage.saved[0][0] == "group-1"
    assert storage.saved[0][1].startswith("v1:")
    plaintext, needs_rotation = cipher.decrypt(storage.saved[0][1])
    assert plaintext == "legacy-password"
    assert needs_rotation is False


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


def test_application_factory_fails_before_bootstrap_without_password_secret(monkeypatch):
    import runtime.app_setup as app_setup

    monkeypatch.delenv("PASSWORD_SECRET", raising=False)
    monkeypatch.delenv("PASSWORD_SECRET_PREVIOUS", raising=False)
    monkeypatch.setattr(app_setup, "load_config_env_file", lambda: None)

    with pytest.raises(PasswordSecretError, match="PASSWORD_SECRET"):
        app_setup.create_app()
