"""Versioned encryption and rotation for persisted Emby passwords."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken


PASSWORD_SECRET_ENV = "PASSWORD_SECRET"
PASSWORD_SECRET_PREVIOUS_ENV = "PASSWORD_SECRET_PREVIOUS"
MIN_PASSWORD_SECRET_LENGTH = 32
_TOKEN_VERSION = "v1"
_INSECURE_PASSWORD_SECRETS = frozenset(
    {
        "",
        "change-this-secret-key",
        "change-this-password-secret",
        "your-secret-key-here",
        "your-password-secret-here",
        "cambia_questo",
    }
)


class PasswordSecretError(RuntimeError):
    """Raised when password encryption is not configured securely."""


class PasswordCiphertextError(RuntimeError):
    """Raised when a persisted password cannot be safely rotated."""


@dataclass(frozen=True)
class _CipherKey:
    key_id: str
    cipher: Fernet


def is_insecure_password_secret(value: object) -> bool:
    """Recognize missing, weak, and documented placeholder encryption secrets."""
    normalized = str(value or "").strip()
    return (
        normalized.lower() in _INSECURE_PASSWORD_SECRETS
        or len(normalized) < MIN_PASSWORD_SECRET_LENGTH
    )


def _cipher_key(secret: str) -> _CipherKey:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return _CipherKey(
        key_id=hashlib.sha256(digest).hexdigest()[:16],
        cipher=Fernet(base64.urlsafe_b64encode(digest)),
    )


class PasswordCipher:
    """Encrypt with the current key and decrypt current or previous versions."""

    def __init__(self, current_secret: str, previous_secret: Optional[str] = None):
        self._current = _cipher_key(current_secret)
        keys = [self._current]
        if previous_secret and previous_secret != current_secret:
            keys.append(_cipher_key(previous_secret))
        self._keys = tuple(keys)
        self._keys_by_id = {key.key_id: key for key in self._keys}

    def encrypt(self, plaintext: str) -> str:
        token = self._current.cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_TOKEN_VERSION}:{self._current.key_id}:{token}"

    def decrypt(self, token: str) -> tuple[Optional[str], bool]:
        """Return plaintext and whether the ciphertext needs current-key rotation."""
        token_value = str(token or "")
        if token_value.startswith(f"{_TOKEN_VERSION}:"):
            parts = token_value.split(":", 2)
            if len(parts) != 3:
                return None, False
            key = self._keys_by_id.get(parts[1])
            if key is None:
                return None, False
            plaintext = self._decrypt_with_key(key, parts[2])
            return plaintext, plaintext is not None and key.key_id != self._current.key_id

        # Legacy ciphertexts had no version/key identifier. Try the current key
        # first, then the explicitly configured previous key used during rotation.
        for key in self._keys:
            plaintext = self._decrypt_with_key(key, token_value)
            if plaintext is not None:
                return plaintext, True
        return None, False

    @staticmethod
    def _decrypt_with_key(key: _CipherKey, token: str) -> Optional[str]:
        try:
            return key.cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError):
            return None


def password_cipher_from_environment(
    environment: Mapping[str, str] = os.environ,
) -> PasswordCipher:
    """Build the password cipher or fail closed when its secret is unsafe."""
    current_secret = str(environment.get(PASSWORD_SECRET_ENV) or "").strip()
    if is_insecure_password_secret(current_secret):
        raise PasswordSecretError(
            f"{PASSWORD_SECRET_ENV} deve essere configurata con almeno "
            f"{MIN_PASSWORD_SECRET_LENGTH} caratteri non prevedibili"
        )

    previous_secret = str(environment.get(PASSWORD_SECRET_PREVIOUS_ENV) or "").strip()
    if previous_secret and previous_secret.lower() in _INSECURE_PASSWORD_SECRETS:
        raise PasswordSecretError(
            f"{PASSWORD_SECRET_PREVIOUS_ENV} contiene un placeholder non sicuro"
        )
    return PasswordCipher(current_secret, previous_secret or None)


def rotate_stored_password_ciphertexts(
    storage: Any,
    cipher: Optional[PasswordCipher] = None,
) -> int:
    """Validate and re-encrypt every legacy/previous-key password atomically in intent."""
    resolved_cipher = cipher or password_cipher_from_environment()
    pending: list[tuple[str, str]] = []

    for entry in storage.get_group_passwords():
        group_id = str(entry.get("group_id") or "")
        plaintext, needs_rotation = resolved_cipher.decrypt(entry.get("password_enc") or "")
        if plaintext is None:
            raise PasswordCiphertextError(
                "Password Emby salvate non decifrabili: ripristina PASSWORD_SECRET "
                "oppure configura PASSWORD_SECRET_PREVIOUS prima del riavvio"
            )
        if needs_rotation:
            pending.append((group_id, resolved_cipher.encrypt(plaintext)))

    # Do not modify any row until every ciphertext has been validated.
    for group_id, ciphertext in pending:
        storage.save_group_password(group_id, ciphertext)
    return len(pending)
