"""Opaque, subject-bound references for credential-bearing search downloads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from core.configuration_redaction import connection_url_has_credentials


REFERENCE_PREFIX = "ohsdl_"
SOURCE_ID_PREFIX = "ohsid_"
REFERENCE_TTL_SECONDS = 30 * 60
_PERSISTED_OWNER_ID = 0
_DOWNLOAD_FIELDS = frozenset(
    {
        "downloadurl",
        "guid",
        "link",
        "magnet",
        "magneturi",
        "magneturl",
        "torrent",
    }
)
_INFO_FIELDS = frozenset({"infourl", "web"})
class DownloadReferenceError(ValueError):
    """Raised when an opaque download reference is invalid or unauthorized."""


class DownloadReferenceCodec:
    """Encrypt provider URLs while binding short-lived copies to one account."""

    def __init__(self, secret: str) -> None:
        normalized = str(secret or "").encode("utf-8")
        digest = hashlib.sha256(b"octohubs-download-reference-v1\0" + normalized).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))
        self._source_id_key = hashlib.sha256(
            b"octohubs-download-source-id-v1\0" + normalized
        ).digest()

    def issue(
        self,
        owner_id: int,
        value: str,
        kind: str,
        *,
        persisted: bool = False,
    ) -> str:
        normalized_owner = _normalize_owner_id(owner_id, persisted=persisted)
        normalized_value = _download_value(value)
        normalized_kind = _download_kind(normalized_value, expected=kind)
        payload = {
            "v": 1,
            "owner": normalized_owner,
            "kind": normalized_kind,
            "value": normalized_value,
            "persisted": bool(persisted),
            "nonce": secrets.token_hex(8),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return REFERENCE_PREFIX + self._cipher.encrypt(encoded).decode("ascii")

    def resolve(
        self,
        owner_id: int,
        reference: str,
        *,
        expected_kind: str | None = None,
    ) -> str:
        payload = self._decode(reference, enforce_ttl=True)
        normalized_owner = _normalize_owner_id(owner_id)
        if payload.get("persisted") or int(payload.get("owner") or 0) != normalized_owner:
            raise DownloadReferenceError("Riferimento download non disponibile")
        value = _download_value(payload.get("value"))
        _download_kind(value, expected=expected_kind or str(payload.get("kind") or ""))
        return value

    def reissue(self, reference: str, owner_id: int, *, persisted: bool) -> str:
        kind, value = self.reference_value(
            reference,
            owner_id,
            persisted=persisted,
        )
        target_owner = _PERSISTED_OWNER_ID if persisted else _normalize_owner_id(owner_id)
        return self.issue(target_owner, value, kind, persisted=persisted)

    def reference_value(
        self,
        reference: str,
        owner_id: int,
        *,
        persisted: bool,
    ) -> tuple[str, str]:
        payload = self._decode(reference, enforce_ttl=False)
        target_owner = _PERSISTED_OWNER_ID if persisted else _normalize_owner_id(owner_id)
        source_owner = int(payload.get("owner") or 0)
        source_persisted = bool(payload.get("persisted"))
        if not persisted and not source_persisted and source_owner != target_owner:
            raise DownloadReferenceError("Riferimento download non disponibile")
        value = _download_value(payload.get("value"))
        kind = _download_kind(value, expected=str(payload.get("kind") or ""))
        return kind, value

    def source_id(
        self,
        owner_id: int,
        values: dict[str, str],
        *,
        persisted: bool,
    ) -> str:
        target_owner = _PERSISTED_OWNER_ID if persisted else _normalize_owner_id(owner_id)
        normalized_values = [
            (kind, _download_value(value))
            for kind, value in sorted(values.items())
        ]
        payload = json.dumps(
            {"owner": target_owner, "sources": normalized_values},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hmac.new(self._source_id_key, payload, hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(digest[:18]).decode("ascii").rstrip("=")
        return SOURCE_ID_PREFIX + token

    def _decode(self, reference: str, *, enforce_ttl: bool) -> dict[str, Any]:
        token = str(reference or "")
        if not token.startswith(REFERENCE_PREFIX):
            raise DownloadReferenceError("Riferimento download non valido")
        try:
            encoded = self._cipher.decrypt(
                token[len(REFERENCE_PREFIX) :].encode("ascii"),
                ttl=REFERENCE_TTL_SECONDS if enforce_ttl else None,
            )
            payload = json.loads(encoded.decode("utf-8"))
        except (InvalidToken, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DownloadReferenceError("Riferimento download non valido o scaduto") from exc
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise DownloadReferenceError("Riferimento download non valido")
        return payload


_codec_lock = threading.RLock()
_codec = DownloadReferenceCodec(secrets.token_urlsafe(48))


def configure_download_reference_secret(secret: str) -> None:
    """Use the application session secret so all workers share the same codec."""
    global _codec
    with _codec_lock:
        _codec = DownloadReferenceCodec(secret)


def resolve_download_reference(
    owner_id: int,
    reference: str,
    *,
    expected_kind: str | None = None,
) -> str:
    with _codec_lock:
        return _codec.resolve(owner_id, reference, expected_kind=expected_kind)


def protect_download_references(
    value: Any,
    owner_id: int = _PERSISTED_OWNER_ID,
    *,
    persisted: bool = False,
) -> Any:
    """Return a detached payload with raw provider downloads replaced by opaque refs."""
    normalized_owner = _normalize_owner_id(owner_id, persisted=persisted)
    return _protect_value(deepcopy(value), normalized_owner, persisted=persisted)


def _protect_value(value: Any, owner_id: int, *, persisted: bool) -> Any:
    if isinstance(value, list):
        return [_protect_value(item, owner_id, persisted=persisted) for item in value]
    if not isinstance(value, dict):
        return value

    protected = {
        key: _protect_value(item, owner_id, persisted=persisted)
        for key, item in value.items()
    }
    raw_by_kind, existing_by_kind = _extract_download_values(protected)
    source_values = _resolve_source_values(
        raw_by_kind,
        existing_by_kind,
        owner_id,
        persisted=persisted,
    )
    _add_source_id(protected, source_values, owner_id, persisted=persisted)
    _add_download_references(
        protected,
        raw_by_kind,
        existing_by_kind,
        owner_id,
        persisted=persisted,
    )
    return protected


def _resolve_source_values(
    raw_by_kind: dict[str, str],
    existing_by_kind: dict[str, str],
    owner_id: int,
    *,
    persisted: bool,
) -> dict[str, str]:
    source_values = dict(raw_by_kind)

    for kind, reference in existing_by_kind.items():
        try:
            with _codec_lock:
                resolved_kind, value = _codec.reference_value(
                    reference,
                    owner_id,
                    persisted=persisted,
                )
            source_values[resolved_kind or kind] = value
        except DownloadReferenceError:
            continue
    return source_values


def _add_source_id(
    protected: dict[Any, Any],
    source_values: dict[str, str],
    owner_id: int,
    *,
    persisted: bool,
) -> None:
    if not source_values:
        return
    with _codec_lock:
        protected["source_id"] = _codec.source_id(
            owner_id,
            source_values,
            persisted=persisted,
        )


def _add_download_references(
    protected: dict[Any, Any],
    raw_by_kind: dict[str, str],
    existing_by_kind: dict[str, str],
    owner_id: int,
    *,
    persisted: bool,
) -> None:
    for kind in ("magnet", "torrent"):
        reference = _issue_or_reissue_reference(
            kind,
            raw_by_kind.get(kind),
            existing_by_kind.get(kind),
            owner_id,
            persisted=persisted,
        )
        if reference:
            protected[f"{kind}_ref"] = reference
            protected[f"has_{kind}"] = True


def _issue_or_reissue_reference(
    kind: str,
    raw_value: str | None,
    existing_reference: str | None,
    owner_id: int,
    *,
    persisted: bool,
) -> str | None:
    try:
        with _codec_lock:
            if existing_reference:
                return _codec.reissue(
                    existing_reference,
                    owner_id,
                    persisted=persisted,
                )
            if raw_value:
                return _codec.issue(
                    _PERSISTED_OWNER_ID if persisted else owner_id,
                    raw_value,
                    kind,
                    persisted=persisted,
                )
    except DownloadReferenceError:
        return None
    return None


def _extract_download_values(protected: dict[Any, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Remove raw download fields and return one candidate per supported kind."""
    raw_by_kind: dict[str, str] = {}
    existing_by_kind: dict[str, str] = {}
    for key, item in list(protected.items()):
        normalized_key = str(key).replace("_", "").lower()
        if normalized_key == "sourceid":
            protected.pop(key, None)
            continue
        if normalized_key in {"magnetref", "torrentref"} and isinstance(item, str):
            kind = "magnet" if normalized_key == "magnetref" else "torrent"
            existing_by_kind.setdefault(kind, item)
            protected.pop(key, None)
            continue
        if normalized_key in _DOWNLOAD_FIELDS:
            # Download-shaped fields are sensitive by contract. Remove them
            # before validation so malformed/provider-specific values cannot
            # fall through into public responses or persisted history.
            protected.pop(key, None)
            if not isinstance(item, str):
                continue
            try:
                kind = _download_kind(item)
            except DownloadReferenceError:
                continue
            raw_by_kind.setdefault(kind, item)
            continue
        if normalized_key in _INFO_FIELDS:
            if not isinstance(item, str) or not _safe_info_url(item):
                protected.pop(key, None)
    return raw_by_kind, existing_by_kind


def _download_kind(value: str, *, expected: str = "") -> str:
    normalized = str(value or "").strip()
    if normalized.lower().startswith("magnet:?"):
        kind = "magnet"
    else:
        try:
            parsed = urlsplit(normalized)
        except ValueError as exc:
            raise DownloadReferenceError("Riferimento download non valido") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise DownloadReferenceError("Riferimento download non valido")
        kind = "torrent"
    normalized_expected = str(expected or "").strip().lower()
    if normalized_expected and normalized_expected != kind:
        raise DownloadReferenceError("Tipo riferimento download non valido")
    return kind


def _download_value(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 4096:
        raise DownloadReferenceError("Riferimento download non valido")
    _download_kind(normalized)
    return normalized


def _normalize_owner_id(owner_id: int, *, persisted: bool = False) -> int:
    try:
        normalized = int(owner_id)
    except (TypeError, ValueError) as exc:
        raise DownloadReferenceError("Identita download non valida") from exc
    if persisted and normalized == _PERSISTED_OWNER_ID:
        return normalized
    if normalized <= 0:
        raise DownloadReferenceError("Identita download non valida")
    return normalized


def _sensitive_url(value: str) -> bool:
    return connection_url_has_credentials(value)


def _safe_info_url(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 4096 or _sensitive_url(normalized):
        return False
    try:
        parsed = urlsplit(normalized)
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


__all__ = [
    "DownloadReferenceCodec",
    "DownloadReferenceError",
    "REFERENCE_PREFIX",
    "configure_download_reference_secret",
    "protect_download_references",
    "resolve_download_reference",
]
