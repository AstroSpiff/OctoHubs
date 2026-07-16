"""Operation-center integration for Latest Publications refreshes."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def get_latest_operation_tracker():
    """Return the global operation tracker when it is available."""
    try:
        from app_state import get_operation_tracker

        return get_operation_tracker()
    except Exception as exc:  # pragma: no cover - defensive integration boundary
        print(f"[LATEST] Operation tracker non disponibile: {exc}")
        return None


def start_latest_refresh_operation(
    full_refresh: bool,
    limit: int,
    per_server_limit: int,
) -> Tuple[Any, Optional[str]]:
    tracker = get_latest_operation_tracker()
    if not tracker:
        return None, None

    summary = "Completo" if full_refresh else "Incrementale"
    try:
        operation = tracker.start(
            "latest_refresh",
            "Aggiornamento Pubblicazioni",
            summary=summary,
            details={
                "mode": summary,
                "limit": int(limit),
                "per_server_limit": int(per_server_limit),
                "current_step_label": "Avvio refresh",
            },
        )
        operation_id = operation.get("id") if isinstance(operation, dict) else None
        return tracker, operation_id
    except Exception as exc:  # pragma: no cover - defensive integration boundary
        print(f"[LATEST] Errore creazione operazione Pubblicazioni: {exc}")
        return None, None


def make_latest_operation_progress_tracker(
    base_progress_tracker,
    operation_tracker,
    operation_id: Optional[str],
    full_refresh: bool,
    limit: int,
    per_server_limit: int,
):
    if not operation_tracker or not operation_id:
        return base_progress_tracker
    return LatestOperationProgressBridge(
        base_progress_tracker,
        operation_tracker,
        operation_id,
        full_refresh=full_refresh,
        limit=limit,
        per_server_limit=per_server_limit,
    )


def finish_latest_refresh_operation(
    operation_tracker,
    operation_id: Optional[str],
    payload: Optional[Dict[str, Any]],
    error: Optional[str],
) -> None:
    if not operation_tracker or not operation_id:
        return

    result = _result_from_payload(payload)
    try:
        if error:
            operation_tracker.fail(operation_id, f"Aggiornamento Pubblicazioni fallito: {error}", result=result)
        else:
            operation_tracker.finish(operation_id, "Aggiornamento Pubblicazioni completato", result=result)
    except Exception as exc:  # pragma: no cover - defensive integration boundary
        print(f"[LATEST] Errore chiusura operazione Pubblicazioni: {exc}")


def fail_latest_refresh_operation(operation_tracker, operation_id: Optional[str], error: Any) -> None:
    if not operation_tracker or not operation_id:
        return
    try:
        operation_tracker.fail(operation_id, f"Aggiornamento Pubblicazioni fallito: {error}")
    except Exception as exc:  # pragma: no cover - defensive integration boundary
        print(f"[LATEST] Errore fallimento operazione Pubblicazioni: {exc}")


class LatestOperationProgressBridge:
    """Mirror Latest progress updates into the global operation center."""

    def __init__(
        self,
        base_progress_tracker,
        operation_tracker,
        operation_id: str,
        *,
        full_refresh: bool,
        limit: int,
        per_server_limit: int,
    ):
        self._base = base_progress_tracker
        self._operation_tracker = operation_tracker
        self._operation_id = operation_id
        self._refresh_label = "Completo" if full_refresh else "Incrementale"
        self._limit = int(limit)
        self._per_server_limit = int(per_server_limit)

    def update(
        self,
        state: Optional[str] = None,
        total: Optional[int] = None,
        completed: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        self._base.update(state=state, total=total, completed=completed, message=message)
        self._mirror_progress(self._base.get_snapshot())

    def get_snapshot(self) -> Dict[str, Any]:
        return self._base.get_snapshot()

    def _mirror_progress(self, snapshot: Dict[str, Any]) -> None:
        message = str(snapshot.get("message") or "Aggiornamento Pubblicazioni")
        details = {
            "mode": self._refresh_label,
            "limit": self._limit,
            "per_server_limit": self._per_server_limit,
            "latest_state": snapshot.get("state") or "",
            "current_step_label": _step_label(snapshot.get("state"), message),
        }
        kwargs: Dict[str, Any] = {
            "message": message,
            "details": details,
        }

        total = _positive_int(snapshot.get("total"))
        completed = _non_negative_int(snapshot.get("completed"))
        if total is not None:
            kwargs["total"] = total
        if completed is not None:
            kwargs["current"] = completed

        progress = _progress_from_snapshot(snapshot)
        if progress is not None:
            kwargs["progress"] = progress

        try:
            self._operation_tracker.update(self._operation_id, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive integration boundary
            print(f"[LATEST] Errore aggiornamento operazione Pubblicazioni: {exc}")


def _progress_from_snapshot(snapshot: Dict[str, Any]) -> Optional[int]:
    state = str(snapshot.get("state") or "")
    if state == "done":
        return 100
    if state == "error":
        return None

    total = _positive_int(snapshot.get("total"))
    completed = _non_negative_int(snapshot.get("completed"))
    if total and completed is not None:
        return max(0, min(99, int(round((completed / total) * 100))))

    if state == "collecting":
        return 10
    if state == "enriching":
        return 50
    return None


def _step_label(state: Any, message: str) -> str:
    state_text = str(state or "")
    if state_text == "collecting":
        return "Raccolta da Emby"
    if state_text == "enriching":
        return "Arricchimento dati"
    if state_text == "done":
        return "Completato"
    if state_text == "error":
        return "Errore"
    return message or "Aggiornamento"


def _result_from_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "movies": len(payload.get("movies") or []),
        "series": len(payload.get("series") or []),
        "errors": len(payload.get("errors") or []),
    }


def _positive_int(value: Any) -> Optional[int]:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _non_negative_int(value: Any) -> Optional[int]:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, resolved)
