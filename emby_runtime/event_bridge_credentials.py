"""Hashed per-server credentials for the Emby Event Bridge."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from typing import Any

from core import config_manager as _config_manager


EVENT_BRIDGE_CREDENTIALS_SECTION = "EVENT_BRIDGE_CREDENTIALS"
_DIGEST_VERSION = "v1"
_DUMMY_DIGEST = "0" * 64


def generate_event_bridge_credential() -> str:
    """Return a high-entropy credential suitable for one Emby server."""
    return secrets.token_urlsafe(32)


def event_bridge_credential_server_ids() -> set[str]:
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    if not isinstance(entries, dict):
        return set()
    return {
        str(server_id).strip()
        for server_id, record in entries.items()
        if str(server_id or "").strip() and _record_digest(record)
    }


def event_bridge_credential_configured(server_id: str) -> bool:
    return bool(_stored_digest(server_id))


def verify_event_bridge_credential(server_id: str, credential: str) -> bool:
    """Compare a presented credential without ever persisting its plaintext."""
    normalized_server_id = _normalized_server_id(server_id)
    stored = _stored_digest(normalized_server_id) or _DUMMY_DIGEST
    presented = _credential_digest(normalized_server_id, credential)
    matches = hmac.compare_digest(stored, presented)
    return bool(
        normalized_server_id
        and credential
        and stored != _DUMMY_DIGEST
        and matches
    )


def save_event_bridge_credential(server_id: str, credential: str) -> None:
    """Atomically replace the hash associated with one server."""
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id or not str(credential or ""):
        raise ValueError("Credenziale Event Bridge non valida")
    record = {
        "version": _DIGEST_VERSION,
        "digest": _credential_digest(normalized_server_id, credential),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    def update(current: Any) -> dict[str, Any]:
        entries = dict(current) if isinstance(current, dict) else {}
        entries[normalized_server_id] = record
        return entries

    backend = _config_manager._ensure_db_backend()
    backend.update_app_settings_section(EVENT_BRIDGE_CREDENTIALS_SECTION, update)


def _stored_digest(server_id: str) -> str:
    normalized_server_id = _normalized_server_id(server_id)
    if not normalized_server_id:
        return ""
    backend = _config_manager._ensure_db_backend()
    settings = backend.load_app_settings() or {}
    entries = settings.get(EVENT_BRIDGE_CREDENTIALS_SECTION)
    if not isinstance(entries, dict):
        return ""
    return _record_digest(entries.get(normalized_server_id))


def _record_digest(record: Any) -> str:
    if not isinstance(record, dict) or record.get("version") != _DIGEST_VERSION:
        return ""
    digest = str(record.get("digest") or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        return ""
    return digest


def _credential_digest(server_id: str, credential: str) -> str:
    value = f"octohubs:event-bridge:{_DIGEST_VERSION}:{server_id}\0{credential}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_server_id(server_id: str) -> str:
    return str(server_id or "").strip()
