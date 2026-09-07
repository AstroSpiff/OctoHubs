"""Versioned encryption envelopes for secrets stored in AppSettings JSON."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import parse_qsl

from core.configuration_redaction import connection_url_has_credentials


_ENVELOPE_KEY = "__octohubs_secret_envelope__"
_ENVELOPE_VERSION = 1
_EMPTY_SECRET_VALUES = (None, "", [], {})
_EXCLUDED_DERIVED_SECRET_KEYS = frozenset({"EVENT_BRIDGE_CREDENTIALS"})
_SENSITIVE_NAMES = frozenset(
    {
        "api_key",
        "api_keys",
        "credential",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)
_SENSITIVE_SUFFIXES = tuple(f"_{name}" for name in _SENSITIVE_NAMES)


class AppSettingsCryptoError(RuntimeError):
    """Raised when persisted application settings cannot be decrypted safely."""


class SettingsCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, token: str) -> tuple[str | None, bool]: ...


def _normalized_key(value: Any) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _is_sensitive_key(key: Any) -> bool:
    raw = str(key or "")
    if raw.upper() in _EXCLUDED_DERIVED_SECRET_KEYS:
        # Event Bridge persists high-entropy credential digests, never plaintext.
        return False
    normalized = _normalized_key(raw)
    compact = normalized.replace("_", "")
    if normalized.endswith("_configured"):
        return False
    return (
        normalized in _SENSITIVE_NAMES
        or normalized.endswith(_SENSITIVE_SUFFIXES)
        or compact
        in {
            "accesstoken",
            "apikey",
            "clientsecret",
            "privatekey",
            "refreshtoken",
            "sslpassword",
        }
    )


def _parameter_string_has_secret(value: str) -> bool:
    try:
        pairs = parse_qsl(value.lstrip("?"), keep_blank_values=True)
    except ValueError:
        return False
    return any(_is_sensitive_key(key) and item != "" for key, item in pairs)


def _value_contains_embedded_secret(key: Any, value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    normalized = _normalized_key(key)
    if normalized.endswith("url"):
        return connection_url_has_credentials(value)
    if normalized.endswith("params"):
        return _parameter_string_has_secret(value)
    return False


def _is_envelope(value: Any) -> bool:
    return isinstance(value, Mapping) and _ENVELOPE_KEY in value


def _nonempty_secret(value: Any) -> bool:
    return value not in _EMPTY_SECRET_VALUES


def _decrypt_envelope(
    value: Mapping[str, Any],
    cipher_factory: Callable[[], SettingsCipher],
) -> tuple[Any, bool]:
    envelope = value.get(_ENVELOPE_KEY)
    if not isinstance(envelope, Mapping):
        raise AppSettingsCryptoError("Envelope segreto app_settings non valido")
    if envelope.get("version") != _ENVELOPE_VERSION:
        raise AppSettingsCryptoError("Versione envelope app_settings non supportata")
    ciphertext = envelope.get("ciphertext")
    if not isinstance(ciphertext, str) or not ciphertext:
        raise AppSettingsCryptoError("Ciphertext app_settings non valido")
    plaintext, needs_rotation = cipher_factory().decrypt(ciphertext)
    if plaintext is None:
        raise AppSettingsCryptoError(
            "Segreti app_settings non decifrabili: ripristina PASSWORD_SECRET oppure "
            "configura PASSWORD_SECRET_PREVIOUS prima del riavvio"
        )
    try:
        return json.loads(plaintext), needs_rotation
    except (json.JSONDecodeError, RecursionError) as exc:
        raise AppSettingsCryptoError("Payload segreto app_settings non valido") from exc


def decode_app_settings_document(
    document: Mapping[str, Any],
    cipher_factory: Callable[[], SettingsCipher],
) -> tuple[dict[str, Any], bool]:
    """Return plaintext settings and whether a transactional rewrite is required."""

    def decode(value: Any, *, key: Any = None) -> tuple[Any, bool]:
        if _is_envelope(value):
            return _decrypt_envelope(value, cipher_factory)
        requires_encryption = (
            _nonempty_secret(value)
            and (_is_sensitive_key(key) or _value_contains_embedded_secret(key, value))
        )
        if requires_encryption:
            return copy.deepcopy(value), True
        if isinstance(value, Mapping):
            decoded: dict[str, Any] = {}
            rewrite = False
            for child_key, child_value in value.items():
                item, item_rewrite = decode(child_value, key=child_key)
                decoded[str(child_key)] = item
                rewrite = rewrite or item_rewrite
            return decoded, rewrite
        if isinstance(value, list):
            decoded_items: list[Any] = []
            rewrite = False
            for child_value in value:
                item, item_rewrite = decode(child_value)
                decoded_items.append(item)
                rewrite = rewrite or item_rewrite
            return decoded_items, rewrite
        return copy.deepcopy(value), False

    decoded, rewrite_required = decode(document)
    if not isinstance(decoded, dict):  # pragma: no cover - guarded by the public type
        raise AppSettingsCryptoError("Documento app_settings non valido")
    return decoded, rewrite_required


def encode_app_settings_document(
    document: Mapping[str, Any],
    cipher_factory: Callable[[], SettingsCipher],
) -> dict[str, Any]:
    """Encrypt every reusable credential while preserving the surrounding JSON."""

    def encode(value: Any, *, key: Any = None) -> Any:
        if _is_envelope(value):
            # Validate caller-supplied envelopes instead of double-encrypting them.
            _decrypt_envelope(value, cipher_factory)
            return copy.deepcopy(value)
        if (
            _nonempty_secret(value)
            and (_is_sensitive_key(key) or _value_contains_embedded_secret(key, value))
        ):
            try:
                plaintext = json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            except (TypeError, ValueError, RecursionError) as exc:
                raise AppSettingsCryptoError("Valore segreto app_settings non serializzabile") from exc
            return {
                _ENVELOPE_KEY: {
                    "version": _ENVELOPE_VERSION,
                    "ciphertext": cipher_factory().encrypt(plaintext),
                }
            }
        if isinstance(value, Mapping):
            return {
                str(child_key): encode(child_value, key=child_key)
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [encode(child_value) for child_value in value]
        return copy.deepcopy(value)

    encoded = encode(document)
    if not isinstance(encoded, dict):  # pragma: no cover - guarded by the public type
        raise AppSettingsCryptoError("Documento app_settings non valido")
    return encoded


__all__ = [
    "AppSettingsCryptoError",
    "SettingsCipher",
    "decode_app_settings_document",
    "encode_app_settings_document",
]
