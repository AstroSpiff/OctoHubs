"""FastAPI routes for configuration pages and updates."""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app_helpers import _get_total_blacklist_counts
from app_state import _JELLYSEERR_REFRESH_STATE
from core import config_manager as _config_manager
from core.config import CONFIG_FILE, _default_auto_tasks, _default_emby_settings, _clean_sort_mode
from core.config_manager import load_config, _db_enabled
from core.storage import StorageError
from core.utils import _split_csv_field, _coerce_request_int
from emby_actions import _prepare_emby_servers_for_view
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_plugin_client import push_event_bridge_settings_to_plugin
from emby_runtime.event_bridge_settings import (
    event_bridge_settings_for_server,
    normalize_event_bridge_config,
    normalize_event_bridge_settings,
)
from services.app_settings import _update_app_settings_overrides, _parse_auto_task_payload
from services.runtime_env import runtime_secret_configured, save_runtime_secret
from telegram import _default_telegram_settings, _load_telegram_settings, _build_telegram_alerts

router = APIRouter()

EVENT_BRIDGE_SETTING_LABELS = {
    "ENABLED": "Abilita",
    "WEBSOCKET_ENABLED": "WebSocket",
    "HTTP_FALLBACK_ENABLED": "Fallback HTTP",
    "WEBSOCKET_RECONNECT_SECONDS": "Reconnect WS",
    "CAPTURE_PLAYBACK_EVENTS": "Playback",
    "CAPTURE_SESSION_EVENTS": "Sessione",
    "CAPTURE_PLUGIN_EVENTS": "Plugin",
    "EVENT_BATCH_INTERVAL_SECONDS": "Batch secondi",
    "HTTP_TIMEOUT_SECONDS": "Timeout HTTP",
    "RETRY_COUNT": "Retry HTTP",
    "INCLUDE_RAW_PAYLOAD": "Raw",
    "PLAYBACK_EVENT_NAMES": "Eventi playback",
    "SESSION_EVENT_NAMES": "Eventi sessione",
    "PLUGIN_EVENT_NAMES": "Eventi plugin",
}

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[..., None]] = None
_get_flash_messages: Optional[Callable[[Request], list]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_templates: Optional[Jinja2Templates] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None


def init_config_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[..., None],
    get_flash_messages: Callable[[Request], list],
    get_csrf_token: Callable[[Request], str],
    templates: Jinja2Templates,
    resolve_next_url: Callable[[Optional[str], str], str],
) -> None:
    global _require_auth, _validate_csrf, _flash, _get_flash_messages, _get_csrf_token
    global _templates, _resolve_next_url
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _get_flash_messages = get_flash_messages
    _get_csrf_token = get_csrf_token
    _templates = templates
    _resolve_next_url = resolve_next_url


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Config routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Config routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Config routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _get_flash_messages_dep(request: Request) -> list:
    if _get_flash_messages is None:
        raise RuntimeError("Config routes not initialized: get_flash_messages missing")
    return _get_flash_messages(request)


def _get_csrf_token_dep(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Config routes not initialized: get_csrf_token missing")
    return _get_csrf_token(request)


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Config routes not initialized: templates missing")
    return _templates


def _resolve_next_url_dep(next_param: Optional[str], default_page: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Config routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_param, default_page)


@router.get("/configuration", response_class=HTMLResponse)
async def configuration_page(request: Request):
    """Configuration page."""
    _require_auth_dep(request)

    config, is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    auto_tasks = (config.get("AUTO_TASKS") if config and config.get("AUTO_TASKS") else _default_auto_tasks())
    collection_config = (config or {}).get("COLLECTIONS", {})
    total_blacklist_count, total_incomplete_count = _get_total_blacklist_counts()

    telegram_settings = _default_telegram_settings()
    telegram_ready = False
    telegram_alerts = {"groups": {}, "channels": {}}

    if config and _db_enabled(config.get("DATABASE", {})):
        telegram_ready = True
        telegram_settings = _load_telegram_settings()
        telegram_alerts = _build_telegram_alerts(telegram_settings)

    messages = _get_flash_messages_dep(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return _get_csrf_token_dep(request)

    requests_refresh_warning = _JELLYSEERR_REFRESH_STATE.get("last_warning")
    requests_refresh_warning_at = _JELLYSEERR_REFRESH_STATE.get("last_warning_at")
    event_bridge_config = normalize_event_bridge_config((config or {}).get("EVENT_BRIDGE", {}))
    event_bridge_status = get_event_bridge_manager().status()
    event_bridge_servers = _event_bridge_servers_for_view(emby_servers, event_bridge_config, event_bridge_status)

    return _templates_dep().TemplateResponse(
        request,
        "configuration.html",
        {
            "request": request,
            "has_config": is_valid,
            "config": config,
            "emby_config": emby_config,
            "emby_servers": emby_servers,
            "auto_tasks": auto_tasks,
            "collection_config": collection_config,
            "telegram_settings": telegram_settings,
            "telegram_bots": telegram_settings.get("BOTS", []),
            "telegram_groups": telegram_settings.get("GROUPS", []),
            "telegram_channels": telegram_settings.get("CHANNELS", []),
            "telegram_presets": telegram_settings.get("PRESETS", []),
            "telegram_alerts": telegram_alerts,
            "telegram_ready": telegram_ready,
            "active_page": "config",
            "total_blacklist_count": total_blacklist_count,
            "total_incomplete_count": total_incomplete_count,
            "requests_refresh_warning": requests_refresh_warning,
            "requests_refresh_warning_at": requests_refresh_warning_at,
            "event_bridge_settings": event_bridge_config["DEFAULT"],
            "event_bridge_config": event_bridge_config,
            "event_bridge_servers": event_bridge_servers,
            "event_bridge_status": event_bridge_status,
            "webhook_secret_configured": runtime_secret_configured("WEBHOOK_SECRET"),
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
        },
    )


@router.get("/configuration/event-bridge/status")
async def event_bridge_status_route(request: Request):
    """Return live Event Bridge diagnostics for the configuration page."""
    _require_auth_dep(request)

    config, _is_valid = load_config()
    emby_config = (config or {}).get("EMBY") if config else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    event_bridge_config = normalize_event_bridge_config((config or {}).get("EVENT_BRIDGE", {}))
    event_bridge_status = get_event_bridge_manager().status()
    event_bridge_servers = _event_bridge_servers_for_view(emby_servers, event_bridge_config, event_bridge_status)

    return JSONResponse(
        {
            "ok": True,
            "connected": event_bridge_status.get("connected", 0),
            "servers": [_event_bridge_status_payload(item) for item in event_bridge_servers],
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/system/status")
async def system_status_route(request: Request, check_services: bool = False):
    """Return a read-only health rollup for the configuration system tab."""
    _require_auth_dep(request)

    payload = await run_in_threadpool(_build_system_status_snapshot, check_services)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post("/configuration/event-bridge")
async def update_event_bridge_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update Emby Event Bridge transport settings."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "config")
    form = await request.form()
    current_config, _is_valid = load_config()
    current_bridge = normalize_event_bridge_config((current_config or {}).get("EVENT_BRIDGE", {}))
    server_ids = _form_list(form, "event_bridge_server_ids")
    submitted_server_settings = {
        server_id: normalize_event_bridge_settings(_event_bridge_settings_payload(form, f"event_bridge_{server_id}_"))
        for server_id in server_ids
    }
    bridge_config = _merged_event_bridge_config(current_bridge, submitted_server_settings)
    webhook_secret = str(form.get("webhook_secret") or "").strip()
    if webhook_secret:
        try:
            save_runtime_secret("WEBHOOK_SECRET", webhook_secret)
        except (OSError, ValueError) as exc:
            _flash_dep(request, f"Errore Event Bridge Emby: {exc}", "error")
            return RedirectResponse(url=next_url, status_code=303)

    try:
        _save_event_bridge_settings(bridge_config)
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio Event Bridge: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        pushed = 0
        http_pushed = 0
        http_failed: list[str] = []
        manager = get_event_bridge_manager()
        connected_ids = {
            item.get("server_id")
            for item in manager.status().get("servers", [])
            if isinstance(item, dict) and item.get("connected")
        }
        target_ids = set(submitted_server_settings) | {str(item or "") for item in connected_ids if item}
        raw_servers = _raw_emby_servers_by_id(current_config)
        websocket_target_ids = set(target_ids)
        for server_id in sorted(target_ids):
            settings = event_bridge_settings_for_server(bridge_config, server_id)
            http_ok, http_error, _response = await run_in_threadpool(
                push_event_bridge_settings_to_plugin,
                raw_servers.get(server_id),
                server_id,
                settings,
            )
            if http_ok:
                http_pushed += 1
                manager.record_plugin_configuration_response(server_id, _response)
                websocket_target_ids.discard(server_id)
            elif raw_servers.get(server_id):
                http_failed.append(f"{server_id}: {http_error}")

        for server_id in sorted(websocket_target_ids):
            pushed += await manager.push_configuration(
                server_id,
                event_bridge_settings_for_server(bridge_config, server_id),
            )
    except Exception as exc:
        _flash_dep(request, f"Event Bridge salvato, push WebSocket non riuscito: {exc}", "warning")
    else:
        parts = []
        if http_pushed:
            parts.append(f"{http_pushed} plugin aggiornati via HTTP")
        if pushed:
            parts.append(f"{pushed} plugin aggiornati via WebSocket")
        suffix = f" ({', '.join(parts)})" if parts else ""
        if http_failed:
            detail = "; ".join(http_failed[:3])
            _flash_dep(request, f"Event Bridge salvato{suffix}, ma push HTTP plugin fallito: {detail}", "warning")
        else:
            _flash_dep(request, f"Event Bridge aggiornato{suffix}", "success")
    return RedirectResponse(url=next_url, status_code=303)


SYSTEM_SEVERITY_RANK = {
    "ok": 0,
    "unknown": 0,
    "warning": 1,
    "error": 2,
}


SYSTEM_SEVERITY_LABELS = {
    "ok": "OK",
    "unknown": "N/D",
    "warning": "Avviso",
    "error": "Errore",
}


SYSTEM_STATUS_LABELS = {
    "ready": "Pronto",
    "config_error": "Config errore",
    "connected": "Connesso",
    "disconnected": "Disconnesso",
    "synced": "Allineato",
    "pending": "In attesa",
    "unknown": "Sconosciuto",
    "check_failed": "Verifica fallita",
    "online": "Online",
    "offline": "Offline",
    "not_configured": "Non configurato",
    "configured": "Configurato",
    "disabled": "Disattivato",
    "not_seen": "Non visto",
    "mismatch": "Disallineato",
    "http_only": "Solo HTTP",
    "running": "In esecuzione",
    "stopped": "Fermo",
    "recent_errors": "Errori recenti",
    "idle": "In attesa",
    "error": "In errore",
    "skipped": "Saltato",
    "done": "Completato",
    "empty": "Vuoto",
}


SYSTEM_SERVICE_LABELS = {
    "jellyseerr": "Jellyseerr",
    "prowlarr": "Prowlarr",
    "jackett": "Jackett",
    "qbittorrent": "qBittorrent",
    "mdblist": "MDBList",
    "omdb": "OMDb",
    "trakt": "Trakt",
    "justwatch": "JustWatch",
    "database": "Database",
}


def _build_system_status_snapshot(check_services: bool = False) -> dict[str, Any]:
    config, is_valid = load_config()
    sections = [
        _system_app_section(config, is_valid),
        _system_database_section(config, is_valid),
        _system_services_section(config, check_services=check_services),
        _system_emby_section(config),
        _system_event_bridge_section(config),
        _system_transcode_guard_section(),
        _system_operations_section(),
        _system_requests_section(),
    ]
    overall = _system_rollup_severity(sections)
    return {
        "ok": overall != "error",
        "severity": overall,
        "status_label": _system_severity_label(overall),
        "generated_at": _event_bridge_timestamp_label(datetime.now(timezone.utc).isoformat()),
        "summary": _system_summary_counts(sections),
        "sections": sections,
    }


def _system_app_section(config: dict[str, Any] | None, is_valid: bool) -> dict[str, Any]:
    severity = "ok" if config and is_valid else "error"
    config_path = str(CONFIG_FILE)
    return _system_section(
        "app",
        "Applicazione",
        [
            _system_item(
                "octohubs",
                "OctoHubs",
                severity,
                "Configurazione caricata" if severity == "ok" else "Configurazione non valida",
                detail="" if severity == "ok" else "Controlla database e file di configurazione.",
                href="/configuration#services",
                status_code="ready" if severity == "ok" else "config_error",
                metrics=[
                    {"label": "Config", "value": config_path},
                    {"label": "Webhook secret", "value": "Configurato" if runtime_secret_configured("WEBHOOK_SECRET") else "Non configurato"},
                ],
            )
        ],
    )


def _system_database_section(config: dict[str, Any] | None, is_valid: bool) -> dict[str, Any]:
    db_settings = ((config or {}).get("DATABASE") or {}) if isinstance(config, dict) else {}
    items: list[dict[str, Any]] = []
    if not db_settings.get("ENABLED"):
        items.append(
            _system_item(
                "database-connection",
                "Connessione database",
                "error",
                "Database non abilitato o non raggiungibile",
                detail="OctoHubs ha bisogno del database per funzionare correttamente.",
                href="/configuration#services",
                status_code="disconnected",
            )
        )
        return _system_section("database", "Database", items)

    metrics = [
        {"label": "Host", "value": db_settings.get("HOST") or "URL"},
        {"label": "Nome DB", "value": db_settings.get("NAME") or "N/D"},
        {"label": "Utente", "value": db_settings.get("USER") or "N/D"},
    ]
    items.append(
        _system_item(
            "database-connection",
            "Connessione database",
            "ok" if is_valid else "error",
            "Connesso" if is_valid else "Connessione non disponibile",
            href="/configuration#services",
            status_code="connected" if is_valid else "disconnected",
            metrics=metrics,
        )
    )

    try:
        backend = _config_manager._DB_BACKEND or _config_manager._ensure_db_backend()
        migration_status = backend.get_migration_status()
        pending = list(getattr(migration_status, "pending", []) or [])
        unknown = list(getattr(migration_status, "unknown_applied", []) or [])
        if pending:
            migration_severity = "warning"
            migration_summary = f"{len(pending)} migrazioni pendenti"
        elif unknown:
            migration_severity = "warning"
            migration_summary = f"{len(unknown)} migrazioni sconosciute"
        else:
            migration_severity = "ok"
            migration_summary = "Migrazioni allineate"
        items.append(
            _system_item(
                "database-migrations",
                "Migrazioni",
                migration_severity,
                migration_summary,
                detail=", ".join((pending or unknown)[:4]),
                href="/configuration#services",
                status_code="synced" if migration_severity == "ok" else "pending",
                metrics=[
                    {"label": "Applicate", "value": str(len(getattr(migration_status, "applied", []) or []))},
                    {"label": "Disponibili", "value": str(len(getattr(migration_status, "available", []) or []))},
                ],
            )
        )
    except Exception as exc:
        items.append(
            _system_item(
                "database-migrations",
                "Migrazioni",
                "warning",
                "Stato migrazioni non leggibile",
                detail=str(exc),
                href="/configuration#services",
                status_code="unknown",
            )
        )

    items.append(_system_backup_item())
    return _system_section("database", "Database", items)


def _system_services_section(config: dict[str, Any] | None, *, check_services: bool) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    check_error = ""
    if check_services:
        try:
            from services.manager import _build_test_connections_snapshot

            payload, _status_code = _build_test_connections_snapshot()
            statuses = payload.get("statuses") if isinstance(payload, dict) else {}
            if not isinstance(statuses, dict):
                statuses = {}
        except Exception as exc:
            check_error = str(exc)

    items: list[dict[str, Any]] = []
    for key, label in SYSTEM_SERVICE_LABELS.items():
        configured = _system_service_configured(config, key)
        if check_error:
            items.append(
                _system_item(
                    f"service-{key}",
                    label,
                    "warning",
                    "Verifica non riuscita",
                    detail=check_error,
                    href="/configuration#services",
                    status_code="check_failed",
                )
            )
            continue
        if check_services and key in statuses:
            status = statuses.get(key) if isinstance(statuses.get(key), dict) else {}
            status_configured = status.get("configured")
            if status_configured is False:
                configured = False
            if key == "database" and status.get("enabled") is False:
                configured = False
            if not configured and key != "database":
                severity = "unknown"
                summary = "Non configurato"
            elif status.get("ok"):
                severity = "ok"
                summary = "Online"
            else:
                severity = "error" if configured or key == "database" else "unknown"
                summary = "Errore" if severity == "error" else "Non configurato"
            items.append(
                _system_item(
                    f"service-{key}",
                    label,
                    severity,
                    summary,
                    detail=str(status.get("message") or ""),
                    href="/configuration#services",
                    status_code=(
                        "online"
                        if severity == "ok"
                        else "error"
                        if severity == "error"
                        else "not_configured"
                        if not configured
                        else "unknown"
                    ),
                )
            )
            continue

        items.append(
            _system_item(
                f"service-{key}",
                label,
                "unknown" if configured or key != "database" else "error",
                "Configurato, non verificato" if configured else ("Non configurato" if key != "database" else "Non disponibile"),
                href="/configuration#services",
                status_code="configured" if configured else ("not_configured" if key != "database" else "disconnected"),
            )
        )
    return _system_section("services", "Servizi esterni", items)


def _system_emby_section(config: dict[str, Any] | None) -> dict[str, Any]:
    servers = (((config or {}).get("EMBY") or {}).get("SERVERS") or []) if isinstance(config, dict) else []
    if not servers:
        return _system_section(
            "emby",
            "Server Emby",
            [
                _system_item(
                    "emby-empty",
                    "Server Emby",
                    "warning",
                    "Nessun server configurato",
                    href="/configuration#emby-servers",
                    status_code="not_configured",
                )
            ],
        )

    try:
        from emby_runtime.snapshots import _build_emby_health_status_snapshot

        payload, _status_code = _build_emby_health_status_snapshot()
        server_statuses = payload.get("data") if isinstance(payload, dict) else []
    except Exception as exc:
        return _system_section(
            "emby",
            "Server Emby",
            [
                _system_item(
                    "emby-health",
                    "Health server",
                    "warning",
                    "Stato Emby non leggibile",
                    detail=str(exc),
                    href="/emby#actions",
                    status_code="unknown",
                )
            ],
        )

    items: list[dict[str, Any]] = []
    for server in server_statuses or []:
        if not isinstance(server, dict):
            continue
        error = str(server.get("error") or "")
        disabled = "disabilitato" in error.lower()
        ok = bool(server.get("ok"))
        severity = "ok" if ok else ("unknown" if disabled else "error")
        items.append(
            _system_item(
                f"emby-{server.get('server_id') or server.get('name')}",
                str(server.get("name") or "Server Emby"),
                severity,
                "Online" if ok else (error or "Errore"),
                detail="" if ok else error,
                href="/emby#actions",
                status_code="online" if ok else ("disabled" if disabled else "offline"),
                metrics=[
                    {"label": "Versione", "value": server.get("version") or "N/D"},
                    {"label": "Stream attivi", "value": str(server.get("active_streams") or 0)},
                ],
            )
        )
    return _system_section("emby", "Server Emby", items)


def _system_event_bridge_section(config: dict[str, Any] | None) -> dict[str, Any]:
    emby_config = (config or {}).get("EMBY") if isinstance(config, dict) else _default_emby_settings()
    raw_servers = (emby_config.get("SERVERS") if emby_config else []) or []
    emby_servers = _prepare_emby_servers_for_view(raw_servers, lazy=True)
    bridge_config = normalize_event_bridge_config((config or {}).get("EVENT_BRIDGE", {}) if isinstance(config, dict) else {})
    bridge_status = get_event_bridge_manager().status()
    bridge_servers = _event_bridge_servers_for_view(emby_servers, bridge_config, bridge_status)
    if not bridge_servers:
        return _system_section(
            "event-bridge",
            "Event Bridge",
            [
                _system_item(
                    "event-bridge-empty",
                    "Plugin Event Bridge",
                    "unknown",
                    "Nessun server da mostrare",
                    href="/configuration#event-bridge",
                    status_code="not_configured",
                )
            ],
        )

    items: list[dict[str, Any]] = []
    for server in bridge_servers:
        diagnostics = server.get("diagnostics") or {}
        status = server.get("status") if isinstance(server.get("status"), dict) else {}
        sync_status = str(diagnostics.get("sync_status") or "unknown")
        ack_status = str(diagnostics.get("last_config_ack_status") or "")
        if ack_status and ack_status not in {"applied", "pending"}:
            severity = "error"
            status_code = "config_error"
        elif sync_status == "mismatch":
            severity = "warning"
            status_code = "mismatch"
        elif status.get("connected") and sync_status == "aligned":
            severity = "ok"
            status_code = "connected"
        elif status.get("connected") or status.get("received_count"):
            severity = "warning" if not status.get("connected") else "unknown"
            status_code = "http_only" if not status.get("connected") else "connected"
        else:
            severity = "unknown"
            status_code = "not_seen"

        transport_label = _event_bridge_transport_payload(status).get("label") or "Non visto"
        sync_label = diagnostics.get("sync_label") or "Report plugin assente"
        items.append(
            _system_item(
                f"event-bridge-{server.get('id')}",
                str(server.get("name") or "Server"),
                severity,
                f"{transport_label} · {sync_label}",
                detail=str(diagnostics.get("last_config_ack_error") or ""),
                href="/configuration#event-bridge",
                status_code=status_code,
                metrics=[
                    {"label": "Plugin", "value": diagnostics.get("plugin_version") or "N/D"},
                    {"label": "Ultimo evento", "value": diagnostics.get("last_event") or "Mai"},
                    {"label": "Config confermata", "value": diagnostics.get("last_config_ack_at") or "Mai"},
                ],
            )
        )
    return _system_section("event-bridge", "Event Bridge", items)


def _system_transcode_guard_section() -> dict[str, Any]:
    try:
        from emby_runtime.transcode_guard import get_transcode_guard_service

        status = get_transcode_guard_service().get_status()
    except Exception as exc:
        return _system_section(
            "transcode-guard",
            "Transcode Guard",
            [
                _system_item(
                    "transcode-guard-status",
                    "Monitor",
                    "warning",
                    "Stato non leggibile",
                    detail=str(exc),
                    href="/emby#transcode-guard",
                    status_code="unknown",
                )
            ],
        )

    settings = status.get("settings") if isinstance(status, dict) else {}
    enabled = bool((settings or {}).get("enabled"))
    running = bool(status.get("running")) if isinstance(status, dict) else False
    active_violations = status.get("active_violations") if isinstance(status, dict) else []
    if enabled and running:
        severity = "warning" if active_violations else "ok"
        summary = "Attivo"
        status_code = "running"
    elif enabled:
        severity = "warning"
        summary = "Abilitato ma non in esecuzione"
        status_code = "stopped"
    else:
        severity = "unknown"
        summary = "Disattivato"
        status_code = "disabled"
    last_result = status.get("last_result") if isinstance(status.get("last_result"), dict) else {}
    return _system_section(
        "transcode-guard",
        "Transcode Guard",
        [
            _system_item(
                "transcode-guard-status",
                "Monitor",
                severity,
                summary,
                detail=str(last_result.get("message") or last_result.get("error") or ""),
                href="/emby#transcode-guard",
                status_code=status_code,
                metrics=[
                    {"label": "Violazioni attive", "value": str(len(active_violations or []))},
                    {"label": "Interventi recenti", "value": str(len(status.get("recent_events") or []))},
                    {"label": "Stream registrati", "value": str(len(status.get("stream_history") or []))},
                ],
            )
        ],
    )


def _system_operations_section() -> dict[str, Any]:
    try:
        from app_state import get_operation_tracker

        operations = get_operation_tracker().list_operations()
    except Exception as exc:
        return _system_section(
            "operations",
            "Operazioni",
            [
                _system_item(
                    "operations-status",
                    "Centro operazioni",
                    "warning",
                    "Operazioni non leggibili",
                    detail=str(exc),
                    href="/emby#actions",
                    status_code="unknown",
                )
            ],
        )
    active = [item for item in operations if item.get("status") in {"queued", "running"}]
    failed = [item for item in operations if item.get("status") in {"error", "interrupted"}]
    severity = "warning" if failed and not active else "ok"
    status_code = "running" if active else ("recent_errors" if failed else "idle")
    summary = f"{len(active)} attive"
    if failed:
        summary += f" · {len(failed)} con problemi recenti"
    latest_failed = failed[0] if failed else {}
    return _system_section(
        "operations",
        "Operazioni",
        [
            _system_item(
                "operations-status",
                "Centro operazioni",
                severity,
                summary,
                detail=str(latest_failed.get("message") or latest_failed.get("error") or ""),
                href="/emby#actions",
                status_code=status_code,
                metrics=[
                    {"label": "Totali recenti", "value": str(len(operations))},
                    {"label": "Ultimo update", "value": _event_bridge_timestamp_label((operations[0] or {}).get("updated_at")) if operations else "Mai"},
                ],
            )
        ],
    )


def _system_requests_section() -> dict[str, Any]:
    state = _JELLYSEERR_REFRESH_STATE
    running = bool(state.get("running"))
    last_status = str(state.get("last_status") or "")
    if running:
        severity = "ok"
        summary = "Refresh richieste in corso"
        status_code = "running"
    elif last_status == "error":
        severity = "warning"
        summary = "Ultimo refresh in errore"
        status_code = "error"
    elif last_status == "skipped":
        severity = "warning"
        summary = "Ultimo refresh saltato"
        status_code = "skipped"
    elif last_status == "success":
        severity = "ok"
        summary = "Ultimo refresh completato"
        status_code = "done"
    else:
        severity = "unknown"
        summary = "Nessun refresh recente"
        status_code = "idle"
    return _system_section(
        "requests",
        "Richieste",
        [
            _system_item(
                "requests-refresh",
                "Aggiornamento richieste",
                severity,
                summary,
                detail=str(state.get("last_error") or state.get("last_warning") or ""),
                href="/dashboard#requests",
                status_code=status_code,
                metrics=[
                    {"label": "Completato", "value": _event_bridge_timestamp_label(state.get("completed_at")) or "Mai"},
                ],
            )
        ],
    )


def _system_backup_item() -> dict[str, Any]:
    root = Path(os.environ.get("OCTOHUBS_DB_BACKUP_DIR") or "backups/db")
    try:
        files = [
            item for item in root.glob("*")
            if item.is_file() and item.suffix in {".dump", ".sqlite3", ".json"}
        ] if root.exists() else []
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        if not root.exists():
            return _system_item(
                "database-backups",
                "Backup database",
                "unknown",
                "Cartella backup non ancora presente",
                detail=str(root),
                href="/configuration#services",
                status_code="empty",
            )
        latest = files[0] if files else None
        return _system_item(
            "database-backups",
            "Backup database",
            "ok" if latest else "unknown",
            f"Ultimo backup: {latest.name}" if latest else "Nessun backup trovato",
            detail=str(root),
            href="/configuration#services",
            status_code="ready" if latest else "empty",
            metrics=[{"label": "File", "value": str(len(files))}],
        )
    except Exception as exc:
        return _system_item(
            "database-backups",
            "Backup database",
            "warning",
            "Backup non leggibili",
            detail=str(exc),
            href="/configuration#services",
            status_code="unknown",
        )


def _system_service_configured(config: dict[str, Any] | None, key: str) -> bool:
    config = config or {}
    if key == "jellyseerr":
        return bool(config.get("JELLYSEERR_URL") and config.get("JELLYSEERR_API_KEY"))
    if key == "prowlarr":
        return bool(config.get("PROWLARR_URL") and config.get("PROWLARR_API_KEY"))
    if key == "jackett":
        return bool(config.get("JACKETT_URL") and config.get("JACKETT_API_KEY"))
    if key == "qbittorrent":
        return bool(config.get("QBITTORRENT_URL") and config.get("QBITTORRENT_USERNAME") and config.get("QBITTORRENT_PASSWORD"))
    if key == "mdblist":
        return bool(config.get("MDBLIST_API_KEYS"))
    if key == "omdb":
        return bool(config.get("OMDB_API_KEYS") or config.get("OMDB_API_KEY"))
    if key == "trakt":
        trakt = config.get("TRAKT") if isinstance(config.get("TRAKT"), dict) else {}
        return bool(trakt.get("ENABLED") and trakt.get("ACCESS_TOKEN"))
    if key == "justwatch":
        justwatch = config.get("JUSTWATCH") if isinstance(config.get("JUSTWATCH"), dict) else {}
        return bool(justwatch.get("ENABLED"))
    if key == "database":
        database = config.get("DATABASE") if isinstance(config.get("DATABASE"), dict) else {}
        return bool(database.get("ENABLED"))
    return False


def _system_section(section_id: str, title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    severity = _system_rollup_severity(items)
    return {
        "id": section_id,
        "title": title,
        "severity": severity,
        "status_code": severity,
        "status_label": _system_severity_label(severity),
        "items": items,
    }


def _system_item(
    item_id: str,
    label: str,
    severity: str,
    summary: str,
    *,
    detail: str = "",
    href: str = "",
    metrics: list[dict[str, Any]] | None = None,
    status_label: str = "",
    status_code: str = "",
) -> dict[str, Any]:
    severity = severity if severity in SYSTEM_SEVERITY_RANK else "unknown"
    code = str(status_code or severity or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "id": str(item_id or label),
        "label": str(label or "Stato"),
        "severity": severity,
        "status_code": code,
        "status_label": status_label or SYSTEM_STATUS_LABELS.get(code) or _system_severity_label(severity),
        "summary": str(summary or ""),
        "detail": str(detail or ""),
        "href": str(href or ""),
        "metrics": [
            {"label": str(metric.get("label") or ""), "value": str(metric.get("value") or "")}
            for metric in (metrics or [])
            if isinstance(metric, dict)
        ],
    }


def _system_rollup_severity(items_or_sections: list[dict[str, Any]]) -> str:
    result = "unknown"
    for item in items_or_sections or []:
        severity = str(item.get("severity") or "unknown")
        if severity == "ok" and result == "unknown":
            result = "ok"
            continue
        if SYSTEM_SEVERITY_RANK.get(severity, 0) > SYSTEM_SEVERITY_RANK.get(result, 0):
            result = severity
    return result


def _system_summary_counts(sections: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"ok": 0, "warning": 0, "error": 0, "unknown": 0}
    for section in sections or []:
        for item in section.get("items") or []:
            severity = str(item.get("severity") or "unknown")
            counts[severity if severity in counts else "unknown"] += 1
    return counts


def _system_severity_label(severity: str) -> str:
    return SYSTEM_SEVERITY_LABELS.get(severity, "N/D")


def _save_event_bridge_settings(settings: dict[str, Any]) -> None:
    if _config_manager._ACTIVE_CONFIG is not None:
        _config_manager._ACTIVE_CONFIG["EVENT_BRIDGE"] = settings
    backend = _config_manager._ensure_db_backend()
    app_settings = backend.load_app_settings() or {}
    app_settings["EVENT_BRIDGE"] = settings
    backend.save_app_settings(app_settings)


def _merged_event_bridge_config(
    current_bridge: dict[str, Any],
    submitted_server_settings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current_bridge = normalize_event_bridge_config(current_bridge)
    merged_servers = {
        str(server_id): settings
        for server_id, settings in (current_bridge.get("SERVERS") or {}).items()
        if str(server_id or "").strip()
    }
    merged_servers.update(submitted_server_settings or {})
    return normalize_event_bridge_config(
        {
            "DEFAULT": current_bridge["DEFAULT"],
            "SERVERS": merged_servers,
        }
    )


def _event_bridge_settings_payload(form: Any, prefix: str) -> dict[str, Any]:
    return {
        "ENABLED": bool(form.get(prefix + "enabled")),
        "WEBSOCKET_ENABLED": bool(form.get(prefix + "websocket_enabled")),
        "HTTP_FALLBACK_ENABLED": bool(form.get(prefix + "http_fallback_enabled")),
        "WEBSOCKET_RECONNECT_SECONDS": form.get(prefix + "ws_reconnect_seconds"),
        "CAPTURE_PLAYBACK_EVENTS": bool(form.get(prefix + "capture_playback")),
        "CAPTURE_SESSION_EVENTS": bool(form.get(prefix + "capture_session")),
        "CAPTURE_PLUGIN_EVENTS": bool(form.get(prefix + "capture_plugin")),
        "EVENT_BATCH_INTERVAL_SECONDS": form.get(prefix + "batch_interval_seconds"),
        "HTTP_TIMEOUT_SECONDS": form.get(prefix + "http_timeout_seconds"),
        "RETRY_COUNT": form.get(prefix + "retry_count"),
        "INCLUDE_RAW_PAYLOAD": bool(form.get(prefix + "include_raw_payload")),
        "PLAYBACK_EVENT_NAMES": form.get(prefix + "playback_event_names"),
        "SESSION_EVENT_NAMES": form.get(prefix + "session_event_names"),
        "PLUGIN_EVENT_NAMES": form.get(prefix + "plugin_event_names"),
    }


def _raw_emby_servers_by_id(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    servers = ((config or {}).get("EMBY") or {}).get("SERVERS") or []
    result: dict[str, dict[str, Any]] = {}
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id = str(server.get("id") or server.get("server_id") or "").strip()
        if server_id:
            result[server_id] = server
    return result


def _event_bridge_servers_for_view(
    emby_servers: list[dict[str, Any]],
    bridge_config: dict[str, Any],
    event_bridge_status: dict[str, Any],
) -> list[dict[str, Any]]:
    status_by_id = {
        str(item.get("server_id") or ""): item
        for item in (event_bridge_status or {}).get("servers", [])
        if isinstance(item, dict)
    }
    items: list[dict[str, Any]] = []
    for server in emby_servers or []:
        server_id = str(server.get("id") or server.get("server_id") or "").strip()
        if not server_id:
            continue
        name = server.get("alias") or server.get("original_name") or server.get("name") or server_id
        settings = event_bridge_settings_for_server(bridge_config, server_id)
        diagnostics = _event_bridge_diagnostics(settings, status_by_id.get(server_id))
        items.append(
            {
                "id": server_id,
                "name": name,
                "icon": server.get("icon") or "fa-server",
                "icon_color": server.get("icon_color") or "#3b82f6",
                "settings": settings,
                "status": status_by_id.get(server_id),
                "settings_editable": _event_bridge_settings_editable(status_by_id.get(server_id)),
                "diagnostics": diagnostics,
            }
        )
    return items


def _event_bridge_settings_editable(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    return bool(
        status.get("connected")
        or status.get("received_count")
        or status.get("plugin_settings")
        or status.get("last_plugin_settings_at")
        or status.get("last_config_ack_status")
    )


def _event_bridge_status_payload(bridge_server: dict[str, Any]) -> dict[str, Any]:
    status = bridge_server.get("status") if isinstance(bridge_server.get("status"), dict) else {}
    diagnostics = bridge_server.get("diagnostics") if isinstance(bridge_server.get("diagnostics"), dict) else {}
    return {
        "id": str(bridge_server.get("id") or ""),
        "name": str(bridge_server.get("name") or ""),
        "settings_editable": bool(bridge_server.get("settings_editable")),
        "settings": normalize_event_bridge_settings(bridge_server.get("settings") or {}),
        "transport": _event_bridge_transport_payload(status),
        "config_ack": _event_bridge_config_ack_payload(status),
        "diagnostics": _event_bridge_diagnostics_payload(diagnostics),
    }


def _event_bridge_transport_payload(status: dict[str, Any]) -> dict[str, str]:
    if status.get("connected"):
        return {"label": "WebSocket connesso", "class_name": "status-ok"}
    if status.get("received_count"):
        return {"label": "HTTP ricevuto", "class_name": "status-skip"}
    return {"label": "Non visto", "class_name": "status-skip"}


def _event_bridge_config_ack_payload(status: dict[str, Any]) -> dict[str, str]:
    ack_status = str(status.get("last_config_ack_status") or "").strip()
    if not ack_status:
        return {"label": "", "class_name": "status-skip", "title": ""}

    if ack_status == "applied":
        label = "Config applicata"
        class_name = "status-ok"
    elif ack_status == "pending":
        label = "Config inviata"
        class_name = "status-skip"
    else:
        label = "Config errore"
        class_name = "status-fail"

    return {
        "label": label,
        "class_name": class_name,
        "title": str(
            status.get("last_config_ack_error")
            or _event_bridge_timestamp_label(status.get("last_config_ack_at"))
            or _event_bridge_timestamp_label(status.get("last_config_sent_at"))
            or ""
        ),
    }


def _event_bridge_diagnostics_payload(diagnostics: dict[str, Any]) -> dict[str, Any]:
    plugin_version = str(diagnostics.get("plugin_version") or "").strip()
    sync_status = str(diagnostics.get("sync_status") or "unknown").strip()
    return {
        "sync_status": sync_status,
        "sync_label": str(diagnostics.get("sync_label") or "Report plugin assente"),
        "sync_class": _event_bridge_sync_class(sync_status),
        "plugin_version": plugin_version,
        "plugin_version_label": f"Plugin {plugin_version}" if plugin_version else "Plugin non rilevato",
        "last_seen_at": str(diagnostics.get("last_seen_at") or "Mai"),
        "last_event": str(diagnostics.get("last_event") or "Mai"),
        "last_event_at": str(diagnostics.get("last_event_at") or ""),
        "last_config_sent_at": str(diagnostics.get("last_config_sent_at") or "Mai"),
        "last_config_ack_at": str(diagnostics.get("last_config_ack_at") or "Mai"),
        "last_config_ack_error": str(diagnostics.get("last_config_ack_error") or ""),
        "last_plugin_settings_at": str(diagnostics.get("last_plugin_settings_at") or "Mai"),
        "target_count": diagnostics.get("target_count"),
        "target_count_label": (
            str(diagnostics.get("target_count"))
            if diagnostics.get("target_count") is not None
            else "Non riportate"
        ),
        "plugin_targets": _event_bridge_targets_payload(diagnostics.get("plugin_targets")),
        "diffs": _event_bridge_diffs_payload(diagnostics.get("diffs")),
    }


def _event_bridge_sync_class(sync_status: str) -> str:
    if sync_status == "aligned":
        return "status-ok"
    if sync_status == "mismatch":
        return "status-fail"
    return "status-skip"


def _event_bridge_targets_payload(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    targets: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        targets.append({"name": str(item.get("name") or "OctoHubs").strip(), "url": url})
    return targets


def _event_bridge_diffs_payload(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    diffs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        diffs.append(
            {
                "label": str(item.get("label") or ""),
                "octohubs": str(item.get("octohubs") or ""),
                "plugin": str(item.get("plugin") or ""),
            }
        )
    return diffs


def _event_bridge_diagnostics(settings: dict[str, Any], status: dict[str, Any] | None) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    plugin_settings = status.get("plugin_settings") if isinstance(status.get("plugin_settings"), dict) else {}
    plugin_targets = status.get("plugin_targets") if isinstance(status.get("plugin_targets"), list) else []
    diffs = _event_bridge_setting_differences(settings, plugin_settings)
    if not plugin_settings:
        sync_status = "unknown"
        sync_label = "Report plugin assente"
    elif diffs:
        sync_status = "mismatch"
        sync_label = "Config diversa"
    else:
        sync_status = "aligned"
        sync_label = "Config allineata"

    target_count = status.get("plugin_target_count")
    if target_count is None and plugin_targets:
        target_count = len(plugin_targets)

    last_event = _event_bridge_last_event_label(status)
    return {
        "sync_status": sync_status,
        "sync_label": sync_label,
        "diffs": diffs,
        "plugin_settings_seen": bool(plugin_settings),
        "plugin_version": status.get("plugin_version") or "",
        "target_count": target_count,
        "plugin_targets": plugin_targets,
        "last_event": last_event,
        "last_seen_at": _event_bridge_timestamp_label(status.get("last_seen_at")),
        "last_event_at": _event_bridge_timestamp_label(status.get("last_event_at")),
        "last_plugin_settings_at": _event_bridge_timestamp_label(status.get("last_plugin_settings_at")),
        "last_config_sent_at": _event_bridge_timestamp_label(status.get("last_config_sent_at")),
        "last_config_ack_at": _event_bridge_timestamp_label(status.get("last_config_ack_at")),
        "last_config_ack_status": status.get("last_config_ack_status") or "",
        "last_config_ack_error": status.get("last_config_ack_error") or "",
    }


def _event_bridge_setting_differences(expected: dict[str, Any], reported: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(reported, dict) or not reported:
        return []

    expected = normalize_event_bridge_settings(expected)
    reported = normalize_event_bridge_settings(reported)
    diffs: list[dict[str, str]] = []
    for key, label in EVENT_BRIDGE_SETTING_LABELS.items():
        expected_value = expected.get(key)
        reported_value = reported.get(key)
        if _event_bridge_comparable_value(expected_value) == _event_bridge_comparable_value(reported_value):
            continue
        diffs.append(
            {
                "label": label,
                "octohubs": _event_bridge_value_label(expected_value),
                "plugin": _event_bridge_value_label(reported_value),
            }
        )
    return diffs


def _event_bridge_comparable_value(value: Any) -> Any:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value]
    return value


def _event_bridge_value_label(value: Any) -> str:
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "vuoto"
    if value is None or value == "":
        return "vuoto"
    return str(value)


def _event_bridge_last_event_label(status: dict[str, Any]) -> str:
    event_name = str(status.get("last_event_name") or "").strip()
    event_type = str(status.get("last_event_type") or "").strip()
    if event_name and event_type and event_name.lower() != event_type.lower():
        return f"{event_name} ({event_type})"
    return event_name or event_type or ""


def _event_bridge_timestamp_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _event_bridge_trim_timestamp(text)

    label = parsed.isoformat(sep=" ", timespec="seconds")
    return label.replace("+00:00", " UTC")


def _event_bridge_trim_timestamp(value: str) -> str:
    text = value.replace("T", " ")
    if "." not in text:
        return text

    prefix, suffix = text.split(".", 1)
    for marker in ("+", "-"):
        if marker in suffix:
            timezone = suffix[suffix.find(marker):]
            return f"{prefix}{timezone}".replace("+00:00", " UTC")
    if "Z" in suffix:
        return f"{prefix} UTC"
    return prefix


def _form_list(form: Any, name: str) -> list[str]:
    getter = getattr(form, "getlist", None)
    values = getter(name) if callable(getter) else [form.get(name)]
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


@router.post("/update-scheduler")
async def update_scheduler_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update scheduler automation settings."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from services.scheduler_manager import sync_auto_scheduler
    from core.config import DEFAULT_CONFIG as CONFIG_DEFAULTS, _normalize_time_list

    config, is_valid = load_config()
    next_url = _resolve_next_url_dep(next_page, "dashboard")

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    form_data = await request.form()

    defaults = _default_auto_tasks()
    current = config.get("AUTO_TASKS") or defaults
    updated = copy.deepcopy(current)

    def _parse_auto_section(section_key: str, fallback: dict) -> dict:
        if form_data.get(section_key) is not None:
            parsed = _parse_auto_task_payload(form_data, section_key, fallback)
            return parsed if isinstance(parsed, dict) else fallback
        enabled = bool(form_data.get(f"{section_key}_enabled"))
        mode = form_data.get(f"{section_key}_mode") or fallback.get("mode", "interval")
        if mode not in ("interval", "fixed"):
            mode = "interval"
        interval_default = fallback.get("interval_minutes", 60)
        interval = _coerce_request_int(form_data.get(f"{section_key}_interval"), interval_default, 1)
        times_raw = form_data.get(f"{section_key}_times")
        if times_raw is None:
            times = fallback.get("times") or []
        else:
            if not isinstance(times_raw, str):
                times_raw = str(times_raw)
            times = _normalize_time_list(times_raw)
        return {
            "enabled": enabled,
            "mode": mode,
            "interval_minutes": interval,
            "times": times,
        }

    updated["scan"] = _parse_auto_section("scan", current.get("scan", defaults["scan"]))
    updated["refresh"] = _parse_auto_section("refresh", current.get("refresh", defaults["refresh"]))
    updated["workflow"] = _parse_auto_section("workflow", current.get("workflow", defaults["workflow"]))
    updated["sync"] = _parse_auto_section(
        "sync",
        current.get("sync", defaults.get("sync", {"enabled": False, "mode": "interval", "interval_minutes": 60, "times": []})),
    )
    collections_enabled = form_data.get("collections_auto_refresh_enabled")
    collections_mode = form_data.get("collections_auto_refresh_mode") or "interval"
    collections_interval_raw = form_data.get("collections_auto_refresh_interval")
    collections_times_raw = form_data.get("collections_auto_refresh_times")
    if collections_times_raw is not None and not isinstance(collections_times_raw, str):
        collections_times_raw = str(collections_times_raw)
    interval_default = CONFIG_DEFAULTS["COLLECTIONS"]["AUTO_REFRESH_INTERVAL_MINUTES"]
    collections_interval = _coerce_request_int(collections_interval_raw, interval_default, 5, 10080)
    collections_times = _split_csv_field(collections_times_raw)
    if collections_mode not in ("interval", "fixed"):
        collections_mode = "interval"
    collections_payload = {
        "AUTO_REFRESH_ENABLED": bool(collections_enabled),
        "AUTO_REFRESH_INTERVAL_MINUTES": collections_interval,
        "AUTO_REFRESH_MODE": collections_mode,
        "AUTO_REFRESH_TIMES": collections_times,
    }

    try:
        _update_app_settings_overrides({
            "AUTO_TASKS": updated,
            "COLLECTIONS": collections_payload,
        })
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio automazioni: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if _config_manager._ACTIVE_CONFIG is None:
        _config_manager._ACTIVE_CONFIG = copy.deepcopy(CONFIG_DEFAULTS)
    _config_manager._ACTIVE_CONFIG["AUTO_TASKS"] = updated
    _config_manager._ACTIVE_CONFIG["COLLECTIONS"] = collections_payload
    config["AUTO_TASKS"] = updated
    config["COLLECTIONS"] = collections_payload

    sync_auto_scheduler(is_valid)

    _flash_dep(request, "Automazioni aggiornate.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/update-rules")
async def update_rules_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    csrf_token: str = Form(None, alias="csrf_token"),
    target_languages: str = Form(""),
    exclude_tags: str = Form(""),
    query_languages: str = Form(""),
    use_original_title: str = Form(None),
    use_alt_titles_original: str = Form(None),
    sanitize_titles: str = Form(None),
    ignore_year_for_tv: str = Form(None),
    require_audio_language: str = Form(None),
    include_target_lang_base: str = Form(None),
    search_episode_variants: str = Form(None),
    skip_available_content: str = Form(None),
    skip_unreleased_content: str = Form(None),
    skip_season_query_when_episode_search: str = Form(None),
    min_seeders: str = Form("0"),
    query_terms: str = Form(""),
    filter_terms: str = Form(""),
    season_templates: str = Form(""),
    use_alt_titles_language: str = Form(None),
    alt_titles_language: str = Form("all"),
    alt_titles_language_custom: str = Form(""),
    use_prowlarr: str = Form(None),
    use_jackett: str = Form(None),
    results_sort: str = Form(None),
    tv_sort_primary: str = Form(None),
    tv_sort_secondary: str = Form(None),
    movie_sort_primary: str = Form(None),
    movie_sort_secondary: str = Form(None),
):
    """Update search rules configuration (JustWatch, language, sort, etc.)."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    from core.config import (
        _normalize_sort_settings,
        _default_search_rules,
        TV_SORT_KEYS,
        MOVIE_SORT_KEYS,
        DEFAULT_CONFIG,
    )

    config, is_valid = load_config()
    if not is_valid or not config:
        _flash_dep(request, "Config non valida. Controlla le connessioni.", "error")
        return RedirectResponse(url="/dashboard", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "dashboard")

    target_langs = _split_csv_field(target_languages)
    exclude_tags_list = _split_csv_field(exclude_tags)
    query_langs = _split_csv_field(query_languages)

    base_rules = config.get("SEARCH_RULES") or _default_search_rules()
    rules = copy.deepcopy(base_rules)

    bool_rules = [
        ("use_original_title", use_original_title),
        ("use_alt_titles_original", use_alt_titles_original),
        ("sanitize_titles", sanitize_titles),
        ("ignore_year_for_tv", ignore_year_for_tv),
        ("require_audio_language", require_audio_language),
        ("include_target_lang_base", include_target_lang_base),
        ("search_episode_variants", search_episode_variants),
        ("skip_available_content", skip_available_content),
        ("skip_unreleased_content", skip_unreleased_content),
    ]

    for rule_key, form_value in bool_rules:
        rules[rule_key] = bool(form_value)

    if rules["search_episode_variants"]:
        rules["skip_season_queries_when_episode_search"] = bool(skip_season_query_when_episode_search)
    else:
        rules["skip_season_queries_when_episode_search"] = False

    rules["min_seeders"] = max(0, _coerce_request_int(min_seeders or "0"))

    rules["query_terms"] = _split_csv_field(query_terms)
    rules["filter_terms"] = _split_csv_field(filter_terms)
    rules["season_templates"] = _split_csv_field(season_templates) or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    rules["query_languages"] = query_langs

    use_alt_language = bool(use_alt_titles_language)
    selected_language = alt_titles_language or "all"
    if selected_language == "custom":
        custom_value = (alt_titles_language_custom or "").strip().lower()
        selected_language = custom_value or "all"
    rules["use_alt_titles_language"] = use_alt_language
    rules["alt_titles_language"] = selected_language if use_alt_language else "disabled"

    rules["use_prowlarr"] = bool(use_prowlarr)
    rules["use_jackett"] = bool(use_jackett)

    if results_sort:
        rules["results_sort"] = results_sort

    rules["tv_sort_primary"] = _clean_sort_mode(
        tv_sort_primary if tv_sort_primary is not None else rules.get("tv_sort_primary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_primary"],
    )
    rules["tv_sort_secondary"] = _clean_sort_mode(
        tv_sort_secondary if tv_sort_secondary is not None else rules.get("tv_sort_secondary"),
        TV_SORT_KEYS,
        base_rules.get("tv_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["tv_sort_secondary"],
        allow_empty=True,
    )
    rules["movie_sort_primary"] = _clean_sort_mode(
        movie_sort_primary if movie_sort_primary is not None else rules.get("movie_sort_primary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_primary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_primary"],
    )
    rules["movie_sort_secondary"] = _clean_sort_mode(
        movie_sort_secondary if movie_sort_secondary is not None else rules.get("movie_sort_secondary"),
        MOVIE_SORT_KEYS,
        base_rules.get("movie_sort_secondary") or DEFAULT_CONFIG["SEARCH_RULES"]["movie_sort_secondary"],
        allow_empty=True,
    )

    rules = _normalize_sort_settings(rules)

    try:
        _update_app_settings_overrides({
            "TARGET_LANGUAGES": target_langs,
            "EXCLUDE_TAGS": exclude_tags_list,
            "SEARCH_RULES": rules,
        })
    except StorageError as exc:
        _flash_dep(request, f"Errore salvataggio regole: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if _config_manager._ACTIVE_CONFIG is None:
        _config_manager._ACTIVE_CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    _config_manager._ACTIVE_CONFIG["TARGET_LANGUAGES"] = target_langs
    _config_manager._ACTIVE_CONFIG["EXCLUDE_TAGS"] = exclude_tags_list
    _config_manager._ACTIVE_CONFIG["SEARCH_RULES"] = rules

    _flash_dep(request, "Regole aggiornate con successo", "success")
    return RedirectResponse(url=next_url, status_code=303)
