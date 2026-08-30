"""Commands for Jellyseerr request rules and refresh operations."""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any

from core.storage import StorageError
from core.utils import json_error


def update_request_rules(payload: dict[str, Any] | None):
    """Persist per-request research overrides without exposing config internals."""
    from core import config_manager
    from core.config import (
        DEFAULT_CONFIG,
        _coerce_request_bool,
        _coerce_request_int,
        _default_search_rules,
        _normalize_alt_language,
    )
    from core.config_manager import _ensure_db_backend, load_config
    from core.utils import _sanitize_terms_list
    from services.app_settings import _refresh_request_overview_rules

    config, is_valid = load_config()
    if not is_valid or not config:
        return json_error("Config non valida")
    source = payload if isinstance(payload, dict) else {}
    rules_payload = source.get("rules")
    if not isinstance(rules_payload, list):
        return json_error("Formato non valido")

    request_rules = dict(config.get("REQUEST_RULES") or {})
    base_search_rules = config.get("SEARCH_RULES") or _default_search_rules()
    for entry in rules_payload:
        if not isinstance(entry, dict) or entry.get("request_id") is None:
            continue
        key = str(entry["request_id"])
        query_terms = _sanitize_terms_list(entry.get("query_terms"))
        filter_terms = _sanitize_terms_list(entry.get("filter_terms"))
        exclude_terms = _sanitize_terms_list(entry.get("exclude_terms"))
        enabled_value = entry.get("enabled")
        enabled = (
            enabled_value.lower() not in {"false", "0", "no"}
            if isinstance(enabled_value, str)
            else bool(enabled_value) if enabled_value is not None else True
        )
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
            use_alt_titles_original
            != base_search_rules.get("use_alt_titles_original", True),
            use_alt_titles_language
            != base_search_rules.get("use_alt_titles_language", False),
            use_alt_titles_language and alt_titles_language != alt_language_default,
            year_variance > 0,
        ))
        if not has_custom:
            request_rules.pop(key, None)
            continue
        request_rules[key] = {
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

    try:
        _ensure_db_backend().save_request_rules(request_rules)
    except StorageError as exc:
        return json_error(f"Errore DB: {exc}", 500)
    if config_manager._ACTIVE_CONFIG is None:
        config_manager._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    config_manager._ACTIVE_CONFIG["REQUEST_RULES"] = request_rules
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
    from services.requests_cache import _save_cached_requests_overview
    from services.requests_summary import _summarize_requests_for_dashboard

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
        overview = _summarize_requests_for_dashboard(config, requests_data=requests_data)
        try:
            if operation_tracker and operation_id:
                operation_tracker.update(
                    operation_id,
                    message="Salvataggio cache richieste",
                    progress=75,
                    details={"current_step_label": "Salvataggio cache"},
                )
            _save_cached_requests_overview(overview)
        except Exception as exc:
            state.update({
                "running": False,
                "last_status": "error",
                "last_error": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return json_error(f"Errore salvataggio cache: {exc}", 500)
        try:
            from services.latest_jellyseerr import save_latest_jellyseerr_requests

            save_latest_jellyseerr_requests(requests_data, backend=_ensure_db_backend())
        except Exception:
            pass

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
        state.update({
            "running": False,
            "last_status": "error",
            "last_error": str(exc),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return json_error(f"Errore aggiornamento richieste: {exc}", 500)


def start_background_refresh():
    """Start one tracked request-refresh operation and return its operation id."""
    from app_state import _JELLYSEERR_REFRESH_STATE, get_operation_tracker

    state = _JELLYSEERR_REFRESH_STATE
    if state.get("running"):
        return {
            "success": True,
            "background": True,
            "operation_id": state.get("operation_id"),
            "message": "Aggiornamento richieste gia in corso.",
        }, 200
    tracker = get_operation_tracker()
    operation = tracker.start(
        "requests_refresh",
        "Aggiornamento Richieste Jellyseerr",
        summary="Ricerca",
        details={"current_step_label": "Avvio refresh"},
    )
    operation_id = operation.get("id")
    state.update({
        "running": True,
        "operation_id": operation_id,
        "last_status": "running",
        "last_error": None,
        "last_warning": None,
        "last_warning_at": None,
    })

    def run() -> None:
        data, status_code = refresh_requests(
            reserved=True,
            operation_tracker=tracker,
            operation_id=operation_id,
        )
        message = str((data or {}).get("message") or "Aggiornamento richieste completato")
        try:
            if status_code >= 400:
                tracker.fail(operation_id, message, result=data)
            elif data.get("success") is False:
                tracker.skip(operation_id, message, result=data)
            else:
                tracker.finish(operation_id, message, result=data)
        finally:
            state.pop("operation_id", None)

    threading.Thread(target=run, daemon=True).start()
    return {
        "success": True,
        "background": True,
        "operation_id": operation_id,
        "message": "Aggiornamento richieste avviato in Operazioni.",
    }, 202


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
