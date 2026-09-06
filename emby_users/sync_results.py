"""Canonical validation for multi-server user synchronization results."""

from __future__ import annotations

from typing import Any, Iterable


class SyncStepError(RuntimeError):
    """A sync domain could not prove that all requested work succeeded."""


def require_complete_snapshots(states: Iterable[dict[str, Any]], expected: int) -> list[dict[str, Any]]:
    snapshots = list(states)
    failures = [state for state in snapshots if state.get("error")]
    if len(snapshots) != expected or failures:
        labels = [
            f"{state.get('server_id')}/{state.get('user_id')}: {state.get('error')}"
            for state in failures
        ]
        raise SyncStepError(f"Snapshot incompleto: {'; '.join(labels) or 'snapshot mancanti'}")
    return snapshots


def validate_sync_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise SyncStepError("Risultato sync non valido")
    if result.get("error"):
        raise SyncStepError(str(result["error"]))
    if result.get("ok") is False:
        raise SyncStepError(str(result.get("message") or "Sincronizzazione non riuscita"))
    if str(result.get("status") or "").lower() in {"error", "failed", "partial"}:
        raise SyncStepError(str(result.get("message") or result.get("status")))
    failed = result.get("failed")
    if isinstance(failed, (list, tuple, set, dict)) and failed:
        raise SyncStepError(f"Scritture non riuscite: {failed}")
    if result.get("skipped"):
        raise SyncStepError(str(result.get("reason") or "Sincronizzazione saltata"))
    return result
