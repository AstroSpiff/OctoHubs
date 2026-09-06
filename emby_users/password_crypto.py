"""Versioned encryption and rotation for persisted Emby passwords."""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken

from core.secret_strength import MIN_SECRET_BYTES, is_strong_secret


PASSWORD_SECRET_ENV = "PASSWORD_SECRET"
PASSWORD_SECRET_PREVIOUS_ENV = "PASSWORD_SECRET_PREVIOUS"
PASSWORD_SECRET_ROTATION_ENV_FILE = "PASSWORD_SECRET_ROTATION_ENV_FILE"
PASSWORD_SECRET_ROTATION_MARKER_ENV = "PASSWORD_SECRET_ROTATION_MARKER"
MIN_PASSWORD_SECRET_LENGTH = MIN_SECRET_BYTES
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
        or not is_strong_secret(normalized)
    )


def _cipher_key(secret: str) -> _CipherKey:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return _CipherKey(
        key_id=hashlib.sha256(digest).hexdigest()[:16],
        cipher=Fernet(base64.urlsafe_b64encode(digest)),
    )


class PasswordCipher:
    """Encrypt versioned tokens and decrypt the current or explicit rotation key."""

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
    """Validate and re-encrypt every previous-key password atomically."""
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

    # The storage boundary performs one commit for the complete set. A failed
    # rotation must stop startup rather than leave a mixture of old/new keys.
    try:
        storage.replace_group_password_ciphertexts(pending)
    except Exception as exc:
        raise PasswordCiphertextError(
            "Rotazione password Emby annullata senza modifiche; verifica il database "
            "e riprova mantenendo PASSWORD_SECRET_PREVIOUS configurata"
        ) from exc
    return len(pending)


def finalize_password_secret_rotation(
    environment: Mapping[str, str] = os.environ,
) -> bool:
    """Commit the persisted Docker key only after DB ciphertext rotation succeeds."""
    marker_value = str(environment.get(PASSWORD_SECRET_ROTATION_MARKER_ENV) or "").strip()
    env_file_value = str(environment.get(PASSWORD_SECRET_ROTATION_ENV_FILE) or "").strip()
    if not marker_value or not env_file_value:
        return False

    marker_path = os.path.abspath(marker_value)
    env_path = os.path.abspath(env_file_value)
    if not os.path.isfile(marker_path):
        return False

    current_secret = str(environment.get(PASSWORD_SECRET_ENV) or "").strip()
    if is_insecure_password_secret(current_secret):
        raise PasswordSecretError("Impossibile completare la rotazione senza PASSWORD_SECRET valida")
    expected_id = open(marker_path, encoding="utf-8").read().strip()
    actual_id = hashlib.sha256(current_secret.encode("utf-8")).hexdigest()
    if not expected_id or expected_id != actual_id:
        raise PasswordSecretError("Il marker di rotazione PASSWORD_SECRET non corrisponde alla chiave corrente")

    try:
        with open(env_path, encoding="utf-8") as handle:
            retained_lines = [
                line
                for line in handle.readlines()
                if not line.startswith("PASSWORD_SECRET=")
                and not line.startswith("PASSWORD_SECRET_PREVIOUS=")
            ]
    except FileNotFoundError:
        retained_lines = []

    directory = os.path.dirname(env_path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary_path = ""
    try:
        descriptor, temporary_path = tempfile.mkstemp(prefix=".octohubs-env-", dir=directory)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.writelines(retained_lines)
            if retained_lines and not retained_lines[-1].endswith("\n"):
                handle.write("\n")
            handle.write(
                "# Chiave dedicata per le password Emby cifrate. "
                "Non modificare senza rotazione.\n"
            )
            handle.write(f"PASSWORD_SECRET={current_secret}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, env_path)
        os.unlink(marker_path)
    except OSError as exc:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise PasswordSecretError(
            "Impossibile rendere persistente il completamento della rotazione PASSWORD_SECRET"
        ) from exc
    return True
