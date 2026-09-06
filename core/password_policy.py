"""Shared password limits imposed by the bcrypt hashing backend."""

from __future__ import annotations


BCRYPT_MAX_PASSWORD_BYTES = 72
PUBLIC_ADMIN_BOOTSTRAP_PASSWORDS = frozenset(
    {
        "change-this-admin-password",
        "strongpassword",
        "passwordforte",
        "inserisci_password_admin_reale",
    }
)


class PasswordTooLongError(ValueError):
    """Raised when a password cannot be represented safely by bcrypt."""


def bcrypt_password_bytes(password: str) -> bytes:
    """Encode a password and enforce bcrypt's UTF-8 byte limit."""
    if not isinstance(password, str):
        raise TypeError("La password deve essere una stringa.")
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"La password non può superare {BCRYPT_MAX_PASSWORD_BYTES} byte UTF-8."
        )
    return encoded


def password_fits_bcrypt(password: str) -> bool:
    """Return whether a password is within bcrypt's byte limit."""
    try:
        bcrypt_password_bytes(password)
    except (TypeError, PasswordTooLongError):
        return False
    return True


def is_public_admin_bootstrap_password(password: str) -> bool:
    """Reject passwords published as copyable deployment examples."""
    if not isinstance(password, str):
        return False
    return password.strip().casefold() in PUBLIC_ADMIN_BOOTSTRAP_PASSWORDS
