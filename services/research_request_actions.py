"""Commands for Jellyseerr request rules and refresh operations."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from core import config_manager
from core.log_sanitization import format_exception_for_log
from core.storage import StorageError
from core.utils import json_error
from search.rule_contracts import RequestRulesPayloadInput, normalize_rule_terms


_BACKGROUND_REFRESH_LOCK = threading.Lock()
logger = logging.getLogger(__name__)
REQUEST_REFRESH_FAILURE_MESSAGE = "Aggiornamento richieste non completato. Verifica i log dell'applicazione."


def _research_internal_error(context: str, exc: BaseException):
    logger.error("%s:\n%s", context, format_exception_for_log(exc))
    return json_error(REQUEST_REFRESH_FAILURE_MESSAGE, 500)


def _unknown_request_rule_ids(
    overview: Any,
    rules_payload: list[dict[str, Any]],
) -> list[str]:
    """Return submitted IDs not present in the current Jellyseerr snapshot."""
    rows = overview if isinstance(overview, list) else []
    known_ids = {
        str(request_id)
        for entry in rows
        if isinstance(entry, dict)
        for request_id in (
            entry.get("request_id")
            if entry.get("request_id") is not None
            else entry.get("id"),
        )
        if request_id is not None
    }
    submitted_ids = {str(entry["request_id"]) for entry in rules_payload}
    return sorted(submitted_ids - known_ids)


def _normalize_request_rule(
    entry: dict[str, Any],
    base_search_rules: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a persisted override, or ``None`` when it matches the defaults."""
    from core.config import (
        _coerce_request_bool,
        _coerce_request_int,
        _normalize_alt_language,
    )

    query_terms = normalize_rule_terms(entry.get("query_terms"))
    filter_terms = normalize_rule_terms(entry.get("filter_terms"))
    exclude_terms = normalize_rule_terms(entry.get("exclude_terms"))
    enabled_value = entry.get("enabled")
    enabled = True if enabled_value is None else bool(enabled_value)
    use_original_title = _coerce_request_bool(
        entry.get("use_original_title"),
        base_search_rules.get("use_original_title", True),
    )
    use_alt_titles_original = _coerce_request_bool(
        entry.get("use_alt_titles_original"),
        base_search_rules.get("use_alt_titles_original", True),
    )
    use_alt_titles_language = _coerce_request_bool(
        entry.get("use_alt_titles_language"),
        base_search_rules.get("use_alt_titles_language", False),
    )
    alt_language_default = str(
        base_search_rules.get("alt_titles_language") or "all",
    ).lower()
    alt_titles_language = _normalize_alt_language(
        entry.get("alt_titles_language"),
        alt_language_default,
    )
    if not use_alt_titles_language:
        alt_titles_language = alt_language_default
    year_variance = _coerce_request_int(entry.get("year_variance"), 0, 0, 10)
    has_custom = any((
        query_terms,
        filter_terms,
        exclude_terms,
        not enabled,
        use_original_title != base_search_rules.get("use_original_title", True),
        use_alt_titles_original != base_search_rules.get("use_alt_titles_original", True),
        use_alt_titles_language != base_search_rules.get("use_alt_titles_language", False),
        use_alt_titles_language and alt_titles_language != alt_language_default,
        year_variance > 0,
    ))
    if not has_custom:
        return None
    return {
        "enabled": enabled,
        "query_terms": query_terms,
        "filter_terms": filter_terms,
        "exclude_terms": exclude_terms,
        "use_original_title": use_original_title,
        "use_alt_titles_original": use_alt_titles_original,
        "use_alt_titles_language": use_alt_titles_language,
        "alt_titles_language": alt_titles_language,
        "year_variance": year_variance,
    }


def _build_request_rule_patch(
    rules_payload: list[dict[str, Any]],
    base_search_rules: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Split submitted rules into upserts and removals."""
    updates: dict[str, dict[str, Any]] = {}
    deletions: set[str] = set()
    for entry in rules_payload:
        if not isinstance(entry, dict) or entry.get("request_id") is None:
            continue
        key = str(entry["request_id"])
        normalized_rule = _normalize_request_rule(entry, base_search_rules)
        if normalized_rule is None:
            updates.pop(key, None)
            deletions.add(key)
            continue
        deletions.discard(key)
        updates[key] = normalized_rule
    return updates, deletions


@config_manager.serialized_config_update
def update_request_rules(payload: dict[str, Any] | None):
    """Persist per-request research overrides without exposing config internals."""
    from core import config_manager
    from core.config import _default_search_rules
    from core.config_manager import _ensure_db_backend, load_config
    from services.app_settings import _refresh_request_overview_rules

    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    source = RequestRulesPayloadInput.model_validate(
        payload if isinstance(payload, dict) else {},
    ).model_dump(exclude_none=True)
    rules_payload = source.get("rules")
    if not isinstance(rules_payload, list):
        return json_error("Formato non valido")

    try:
        backend = _ensure_db_backend()
        overview, _updated_at = backend.load_request_overview()
    except StorageError as exc:
        return _research_internal_error("Validazione regole richieste non riuscita", exc)
    unknown_request_ids = _unknown_request_rule_ids(overview, rules_payload)
    if unknown_request_ids:
        return json_error(
            "Una o più richieste non sono presenti nella cache Jellyseerr aggiornata",
            422,
        )

    base_search_rules = config.get("SEARCH_RULES") or _default_search_rules()
    request_rule_updates, request_rule_deletions = _build_request_rule_patch(
        rules_payload,
        base_search_rules,
    )

    try:
        request_rules = backend.patch_request_rules(
            request_rule_updates,
            request_rule_deletions,
        )
    except StorageError as exc:
        return _research_internal_error("Salvataggio regole richieste non riuscito", exc)
    config_manager.publish_active_config_updates({"REQUEST_RULES": request_rules})
    _refresh_request_overview_rules(config)
    return {"success": True, "message": "Regole per le richieste aggiornate"}, 200


def refresh_requests(
    *,
    reserved: bool = False,
    operation_tracker: Any = None,
    operation_id: str | None = None,
):
    """Read Jellyseerr, persist the normalized cache, and update operation state."""
    from app_state import _JELLYSEERR_REFRESH_STATE
    from core.config_manager import _ensure_db_backend, load_config
    from emby_runtime.api_clients import get_jellyseerr_requests
    from services.request_refresh_snapshot import save_request_refresh_dataset

    state = _JELLYSEERR_REFRESH_STATE
    if state.get("running") and not reserved:
        return {"success": True, "message": "Aggiornamento richieste gia in corso."}, 200
    if not reserved:
        state.update({
            "running": True,
            "last_error": None,
            "last_warning": None,
            "last_warning_at": None,
        })
    try:
        config, is_valid = load_config()
        if not is_valid:
            state.update({"running": False, "last_status": "error", "last_error": "Config non valida"})
            return json_error("Config non valida")
        if operation_tracker and operation_id:
            operation_tracker.update(
                operation_id,
                message="Lettura richieste da Jellyseerr",
                progress=15,
                details={"current_step_label": "Lettura Jellyseerr"},
            )
        requests_data, ok = get_jellyseerr_requests(config, silent=True, return_status=True)
        if not ok:
            warning = "Jellyseerr non risponde: refresh richieste saltato."
            now = datetime.now(timezone.utc).isoformat()
            state.update({
                "running": False,
                "last_status": "skipped",
                "last_warning": warning,
                "last_warning_at": now,
                "completed_at": now,
            })
            return {"success": False, "message": warning}, 200
        if operation_tracker and operation_id:
            operation_tracker.update(
                operation_id,
                message="Analisi richieste e disponibilita",
                progress=45,
                details={"current_step_label": "Analisi richieste"},
            )
        try:
            if operation_tracker and operation_id:
                operation_tracker.update(
                    operation_id,
                    message="Salvataggio cache richieste",
                    progress=75,
                    details={"current_step_label": "Salvataggio cache"},
                )
            backend = _ensure_db_backend()
            overview = save_request_refresh_dataset(
                config,
                requests_data,
                backend=backend,
            )
        except Exception as exc:
            logger.error("Salvataggio cache richieste non riuscito:\n%s", format_exception_for_log(exc))
            state.update({
                "running": False,
                "last_status": "error",
                "last_error": REQUEST_REFRESH_FAILURE_MESSAGE,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return json_error(REQUEST_REFRESH_FAILURE_MESSAGE, 500)
        tv_count = sum(
            1 for request in overview
            if str(request.get("media_type") or "").lower() == "tv"
        )
        counts = {"total": len(overview), "tv": tv_count, "movies": len(overview) - tv_count}
        if operation_tracker and operation_id:
            operation_tracker.update(
                operation_id,
                message=f"Richieste elaborate: {counts['total']}",
                progress=95,
                details={"current_step_label": "Completamento", **counts},
            )
        state.update({
            "running": False,
            "last_status": "success",
            "counts": counts,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": True, "message": "Lista aggiornata da Jellyseerr.", "counts": counts}, 200
    except Exception as exc:
        logger.error("Aggiornamento richieste non riuscito:\n%s", format_exception_for_log(exc))
        state.update({
            "running": False,
            "last_status": "error",
            "last_error": REQUEST_REFRESH_FAILURE_MESSAGE,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return json_error(REQUEST_REFRESH_FAILURE_MESSAGE, 500)


def _start_background_refresh_locked():
    """Start one tracked request-refresh operation and return its operation id."""
    from app_state import _JELLYSEERR_REFRESH_STATE, get_operation_tracker
    from services.background_job_registry import background_job_registry

    state = _JELLYSEERR_REFRESH_STATE
    tracker = get_operation_tracker()
    operation: dict[str, Any] = {}

    def create_operation() -> dict[str, Any]:
        created = tracker.start(
            "requests_refresh",
            "Aggiornamento Richieste Jellyseerr",
            summary="Ricerca",
            details={"current_step_label": "Avvio refresh"},
        )
        operation.update(created)
        operation_id = str(created.get("id") or "")
        if not operation_id:
            raise RuntimeError("Impossibile creare l'operazione di refresh")
        state.update({
            "running": True,
            "operation_id": operation_id,
            "last_status": "running",
            "last_error": None,
            "last_warning": None,
            "last_warning_at": None,
        })
        return operation

    def run(stop_event) -> None:
        operation_id = str(operation.get("id") or "")
        if stop_event.is_set():
            tracker.fail(operation_id, "Operazione interrotta durante lo shutdown")
            state["running"] = False
            state.pop("operation_id", None)
            return
        try:
            data, status_code = refresh_requests(
                reserved=True,
                operation_tracker=tracker,
                operation_id=operation_id,
            )
            if stop_event.is_set():
                tracker.fail(operation_id, "Operazione interrotta durante lo shutdown", result=data)
                return
            message = str((data or {}).get("message") or "Aggiornamento richieste completato")
            if status_code >= 400:
                tracker.fail(operation_id, message, result=data)
            elif data.get("success") is False:
                tracker.skip(operation_id, message, result=data)
            else:
                tracker.finish(operation_id, message, result=data)
        finally:
            state["running"] = False
            state.pop("operation_id", None)

    try:
        registered, started = background_job_registry.start(
            "requests:jellyseerr-refresh",
            create_operation,
            run,
        )
    except Exception:
        operation_id = str(operation.get("id") or "")
        if operation_id:
            tracker.fail(operation_id, "Avvio refresh non riuscito")
        state["running"] = False
        state.pop("operation_id", None)
        raise
    operation_id = str(registered.get("id") or "")
    return {
        "success": True,
        "background": True,
        "operation_id": operation_id,
        "message": (
            "Aggiornamento richieste avviato in Operazioni."
            if started
            else "Aggiornamento richieste gia in corso."
        ),
    }, 202 if started else 200


def start_background_refresh():
    with _BACKGROUND_REFRESH_LOCK:
        return _start_background_refresh_locked()


def get_request_refresh_status() -> dict[str, Any]:
    """Return refresh state without triggering another Jellyseerr request."""
    from app_state import _JELLYSEERR_REFRESH_STATE, get_jellyseerr_refresh_state

    return {
        **get_jellyseerr_refresh_state(),
        "counts": _JELLYSEERR_REFRESH_STATE.get("counts"),
    }


__all__ = [
    "get_request_refresh_status",
    "refresh_requests",
    "start_background_refresh",
    "update_request_rules",
]
