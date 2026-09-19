"""Opaque, expiring references for Prowlarr cached search releases."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


PROWLARR_GRAB_REFERENCE_PREFIX = "ohsgrab_"
PROWLARR_GRAB_TTL_SECONDS = 30 * 60
_PERSISTED_OWNER_ID = 0


class ProwlarrGrabReferenceError(ValueError):
    """Raised when a Prowlarr grab reference is invalid or unauthorized."""


class ProwlarrGrabReferenceCodec:
    """Encrypt cached-release identities and bind them to one account."""

    def __init__(self, secret: str) -> None:
        normalized = str(secret or "").encode("utf-8")
        digest = hashlib.sha256(
            b"octohubs-prowlarr-grab-reference-v1\0" + normalized
        ).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))

    def issue(
        self,
        owner_id: int,
        release: Any,
        *,
        persisted: bool = False,
        expires_at: int | None = None,
    ) -> str:
        normalized_owner = _normalize_owner_id(owner_id, persisted=persisted)
        payload = {
            "v": 1,
            "owner": normalized_owner,
            "kind": "prowlarr_grab",
            "release": _normalized_release(release),
            "persisted": bool(persisted),
            "expires_at": expires_at
            or int(time.time()) + PROWLARR_GRAB_TTL_SECONDS,
            "nonce": secrets.token_hex(8),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        return PROWLARR_GRAB_REFERENCE_PREFIX + self._cipher.encrypt(encoded).decode(
            "ascii"
        )

    def resolve(self, owner_id: int, reference: str) -> dict[str, Any]:
        payload = self._decode(reference)
        normalized_owner = _normalize_owner_id(owner_id)
        if payload.get("persisted") or int(payload.get("owner") or 0) != normalized_owner:
            raise ProwlarrGrabReferenceError("Riferimento Prowlarr non disponibile")
        return _normalized_release(payload.get("release"))

    def reissue(
        self,
        reference: str,
        owner_id: int,
        *,
        persisted: bool,
    ) -> str:
        payload = self._decode(reference)
        target_owner = _PERSISTED_OWNER_ID if persisted else _normalize_owner_id(owner_id)
        source_owner = int(payload.get("owner") or 0)
        source_persisted = bool(payload.get("persisted"))
        if not persisted and not source_persisted and source_owner != target_owner:
            raise ProwlarrGrabReferenceError("Riferimento Prowlarr non disponibile")
        return self.issue(
            target_owner,
            payload.get("release"),
            persisted=persisted,
            expires_at=int(payload["expires_at"]),
        )

    def _decode(self, reference: str) -> dict[str, Any]:
        token = str(reference or "")
        if not token.startswith(PROWLARR_GRAB_REFERENCE_PREFIX):
            raise ProwlarrGrabReferenceError("Riferimento Prowlarr non valido")
        try:
            encoded = self._cipher.decrypt(
                token[len(PROWLARR_GRAB_REFERENCE_PREFIX) :].encode("ascii")
            )
            payload = json.loads(encoded.decode("utf-8"))
        except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ProwlarrGrabReferenceError(
                "Riferimento Prowlarr non valido o scaduto"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "prowlarr_grab"
        ):
            raise ProwlarrGrabReferenceError("Riferimento Prowlarr non disponibile")
        try:
            expires_at = int(payload.get("expires_at") or 0)
        except (TypeError, ValueError) as exc:
            raise ProwlarrGrabReferenceError("Riferimento Prowlarr non valido") from exc
        if expires_at <= int(time.time()):
            raise ProwlarrGrabReferenceError(
                "Riferimento Prowlarr non valido o scaduto"
            )
        return payload


_codec_lock = threading.RLock()
_codec = ProwlarrGrabReferenceCodec(secrets.token_urlsafe(48))


def configure_prowlarr_grab_reference_secret(secret: str) -> None:
    global _codec
    with _codec_lock:
        _codec = ProwlarrGrabReferenceCodec(secret)


def issue_prowlarr_grab_reference(
    owner_id: int,
    release: Any,
    *,
    persisted: bool,
) -> str:
    with _codec_lock:
        return _codec.issue(owner_id, release, persisted=persisted)


def reissue_prowlarr_grab_reference(
    reference: str,
    owner_id: int,
    *,
    persisted: bool,
) -> str:
    with _codec_lock:
        return _codec.reissue(reference, owner_id, persisted=persisted)


def resolve_prowlarr_grab_reference(
    owner_id: int,
    reference: str,
) -> dict[str, Any]:
    with _codec_lock:
        return _codec.resolve(owner_id, reference)


def _normalized_release(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProwlarrGrabReferenceError("Riferimento Prowlarr non valido")
    indexer_id = value.get("indexerId", value.get("indexer_id"))
    guid = value.get("guid")
    if isinstance(indexer_id, bool) or not isinstance(indexer_id, int) or indexer_id <= 0:
        raise ProwlarrGrabReferenceError("Riferimento Prowlarr non valido")
    if not isinstance(guid, str) or not guid.strip() or len(guid) > 4096:
        raise ProwlarrGrabReferenceError("Riferimento Prowlarr non valido")
    return {"indexerId": indexer_id, "guid": guid.strip()}


def _normalize_owner_id(owner_id: int, *, persisted: bool = False) -> int:
    try:
        normalized = int(owner_id)
    except (TypeError, ValueError) as exc:
        raise ProwlarrGrabReferenceError("Identita Prowlarr non valida") from exc
    if persisted and normalized == _PERSISTED_OWNER_ID:
        return normalized
    if normalized <= 0:
        raise ProwlarrGrabReferenceError("Identita Prowlarr non valida")
    return normalized


__all__ = [
    "PROWLARR_GRAB_REFERENCE_PREFIX",
    "ProwlarrGrabReferenceCodec",
    "ProwlarrGrabReferenceError",
    "configure_prowlarr_grab_reference_secret",
    "issue_prowlarr_grab_reference",
    "reissue_prowlarr_grab_reference",
    "resolve_prowlarr_grab_reference",
]
