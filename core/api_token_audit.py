"""Read-only, safe presentation of API-token audit records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from core import auth


API_TOKEN_AUDIT_ACTIONS = frozenset({
    "api_token_read",
    "api_token_write",
    "api_token_operation",
    "api_token_denied",
})
API_TOKEN_AUDIT_RESULTS = frozenset({"allowed", "denied"})
API_TOKEN_AUDIT_VERSIONS = frozenset({"v1", "legacy"})
MAX_API_TOKEN_AUDIT_EVENTS = 200


def _detail(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        decoded = {}
    return decoded if isinstance(decoded, dict) else {}


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _api_version(path: str) -> str:
    """Classify the public API path recorded by a token audit event."""
    normalized_path = str(path or "")
    if normalized_path.startswith("/api/v1/"):
        return "v1"
    return "legacy" if normalized_path.startswith("/api/") else "unknown"


def _event(log: Any) -> dict[str, Any] | None:
    detail = _detail(getattr(log, "detail", None))
    try:
        token_id = int(detail.get("token_id") or 0)
    except (TypeError, ValueError):
        return None
    if token_id <= 0:
        return None
    action = str(getattr(log, "action", "") or "")
    result = str(detail.get("result") or "").strip().lower()
    if result not in API_TOKEN_AUDIT_RESULTS:
        result = "denied" if action == "api_token_denied" else "allowed"
    path = str(getattr(log, "path", "") or "")
    return {
        "id": int(getattr(log, "id", 0) or 0),
        "at": _timestamp(getattr(log, "created_at", None)),
        "token_id": token_id,
        "token_name": str(detail.get("token_name") or "Token rimosso"),
        "token_prefix": str(detail.get("token_prefix") or ""),
        "action": action,
        "result": result,
        "required_scope": str(detail.get("required_scope") or ""),
        "method": str(getattr(log, "method", "") or "").upper(),
        "path": path,
        "api_version": _api_version(path),
        "ip_address": str(getattr(log, "ip_address", "") or ""),
        "user_agent": str(getattr(log, "user_agent", "") or ""),
    }


def _event_matches(
    event: dict[str, Any],
    *,
    token_id: int | None,
    result: str,
    api_version: str,
) -> bool:
    return not (
        (token_id is not None and event["token_id"] != token_id)
        or (result and event["result"] != result)
        or (api_version and event["api_version"] != api_version)
    )


def list_api_token_audit_events(
    user_id: int,
    *,
    token_id: int | None = None,
    result: str | None = None,
    api_version: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List a user's API-token audit records without returning token secrets."""
    if not auth.db_session:
        return []
    requested_result = str(result or "").strip().lower()
    if requested_result not in API_TOKEN_AUDIT_RESULTS:
        requested_result = ""
    requested_version = str(api_version or "").strip().lower()
    if requested_version not in API_TOKEN_AUDIT_VERSIONS:
        requested_version = ""
    normalized_limit = max(1, min(int(limit or 100), MAX_API_TOKEN_AUDIT_EVENTS))
    normalized_token_id = int(token_id) if token_id is not None else None
    fetch_limit = min(max(normalized_limit * 12, 300), 2400)
    try:
        records = (
            auth.db_session.query(auth.AuditLog)
            .filter(auth.AuditLog.user_id == int(user_id))
            .filter(auth.AuditLog.action.in_(API_TOKEN_AUDIT_ACTIONS))
            .order_by(auth.AuditLog.created_at.desc())
            .limit(fetch_limit)
            .all()
        )
    except (TypeError, ValueError):
        return []
    except SQLAlchemyError as exc:
        raise auth.AuthStorageError("Audit API token non disponibile") from exc

    events: list[dict[str, Any]] = []
    for record in records:
        event = _event(record)
        if event is None:
            continue
        if not _event_matches(
            event,
            token_id=normalized_token_id,
            result=requested_result,
            api_version=requested_version,
        ):
            continue
        events.append(event)
        if len(events) >= normalized_limit:
            break
    return events


def api_token_audit_export(
    user_id: int,
    *,
    token_id: int | None = None,
    result: str | None = None,
    api_version: str | None = None,
) -> dict[str, Any]:
    """Create a bounded, safe JSON export for one account's API token audit."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "token_id": token_id,
            "result": result or None,
            "api_version": api_version or None,
        },
        "events": list_api_token_audit_events(
            user_id,
            token_id=token_id,
            result=result,
            api_version=api_version,
            limit=MAX_API_TOKEN_AUDIT_EVENTS,
        ),
    }
