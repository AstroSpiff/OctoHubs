"""FastAPI routes for configuration pages and updates."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, JSONResponse

from app_state import _JELLYSEERR_REFRESH_STATE
from core import config_manager as _config_manager
from core.config import _default_emby_settings
from core.config_manager import load_config
from core.log_sanitization import format_exception_for_log
from emby_actions import _prepare_emby_servers_for_view
from emby_runtime.event_bridge_configuration import (
    _event_bridge_servers_for_view,
    _event_bridge_timestamp_label,
    _event_bridge_transport_payload,
)
from emby_runtime.event_bridge_manager import get_event_bridge_manager
from emby_runtime.event_bridge_settings import normalize_event_bridge_config
from web.system_status_api_models import SystemStatusResponse

router = APIRouter()
logger = logging.getLogger(__name__)

_require_auth: Optional[Callable[[Request], Any]] = None


def init_config_routes(
    require_auth: Callable[[Request], Any],
) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Config routes not initialized: require_auth missing")
    return _require_auth(request)


@router.get("/configuration", include_in_schema=False)
async def configuration_page(request: Request):
    """Redirect the retired configuration template to the React workspace."""
    await run_in_threadpool(_require_auth_dep, request)
    return RedirectResponse(url="/app/configuration", status_code=303)


@router.get(
    "/api/system/status",
    responses={
        200: {
            "model": SystemStatusResponse,
            "description": "Snapshot completo oppure risposta di sezione non valida.",
        }
    },
)
async def system_status_route(
    request: Request,
    section: str = Query(
        default="",
        description="Identificativo opzionale della sola sezione da aggiornare.",
    ),
    check_services: bool = Query(
        default=False,
        description="Esegue una nuova verifica delle integrazioni prima di restituire la sezione servizi.",
    ),
):
    """Return all or one read-only health section for the configuration tab."""
    await run_in_threadpool(_require_auth_dep, request)
    section_id = section if isinstance(section, str) else ""
    should_check_services = check_services if isinstance(check_services, bool) else False

    payload = await run_in_threadpool(
        _build_system_status_snapshot,
        should_check_services,
        section_id.strip(),
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


SYSTEM_SEVERITY_RANK = {
    "ok": 0,
    "unknown": 0,
    "warning": 1,
    "error": 2,
}


SYSTEM_SEVERITY_LABELS = {
    "ok": "OK",
    "unknown": "Da verificare",
    "warning": "Avviso",
    "error": "Errore",
}


SYSTEM_STATUS_LABELS = {
    "ready": "Pronto",
    "config_error": "Errore configurazione",
    "connected": "Connesso",
    "disconnected": "Disconnesso",
    "synced": "Allineato",
    "pending": "In attesa",
    "unknown": "Da verificare",
    "check_failed": "Verifica fallita",
    "online": "Online",
    "offline": "Offline",
    "not_configured": "Non configurato",
    "configured": "Configurato",
    "disabled": "Disattivato",
    "not_seen": "Nessun contatto",
    "mismatch": "Disallineato",
    "http_only": "Solo HTTP",
    "running": "In esecuzione",
    "stopped": "Fermo",
    "recent_errors": "Errori recenti",
    "idle": "Nessuna attivita recente",
    "error": "In errore",
    "skipped": "Saltato",
    "done": "Completato",
    "empty": "Vuoto",
}


SYSTEM_SECTION_META = {
    "app": {
        "href": "/app/configuration/services",
        "refresh_interval_seconds": 60,
    },
    "database": {
        "href": "/app/configuration/services?focus=configuration-database",
        "refresh_interval_seconds": 60,
    },
    "services": {
        "href": "/app/configuration/services?focus=configuration-connections",
        "refresh_interval_seconds": 0,
        "check_label": "Verifica integrazioni",
    },
    "emby": {
        "href": "/app/emby-live?focus=emby-live-servers",
        "refresh_interval_seconds": 30,
        "check_label": "Verifica server",
    },
    "event-bridge": {
        "href": "/app/configuration/event-bridge?focus=event-bridge-configuration",
        "refresh_interval_seconds": 5,
    },
    "transcode-guard": {
        "href": "/app/transcode-guard?focus=transcode-guard-panel",
        "refresh_interval_seconds": 5,
    },
    "operations": {
        "href": "/app/emby-live?focus=emby-live-servers",
        "refresh_interval_seconds": 10,
    },
    "requests": {
        "href": "/app/research/requests?focus=requests-refresh",
        "refresh_interval_seconds": 10,
    },
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


SYSTEM_SERVICE_HREFS = {
    "jellyseerr": "/app/configuration/services?focus=configuration-connections",
    "prowlarr": "/app/configuration/services?focus=configuration-connections",
    "jackett": "/app/configuration/services?focus=configuration-connections",
    "qbittorrent": "/app/configuration/services?focus=configuration-connections",
    "mdblist": "/app/configuration/services?focus=configuration-metadata",
    "omdb": "/app/configuration/services?focus=configuration-metadata",
    "trakt": "/app/configuration/services?focus=configuration-catalogs",
    "justwatch": "/app/configuration/services?focus=configuration-catalogs",
    "database": "/app/configuration/services?focus=configuration-database",
}


def _build_system_status_snapshot(
    check_services: bool = False,
    section_id: str = "",
) -> dict[str, Any]:
    config, is_valid = load_config()
    builders = {
        "app": lambda: _system_app_section(config, is_valid),
        "database": lambda: _system_database_section(config, is_valid),
        "services": lambda: _system_services_section(config, check_services=check_services),
        "emby": lambda: _system_emby_section(config),
        "event-bridge": lambda: _system_event_bridge_section(config),
        "transcode-guard": _system_transcode_guard_section,
        "operations": _system_operations_section,
        "requests": _system_requests_section,
    }
    normalized_section_id = str(section_id or "").strip().lower()
    if normalized_section_id and normalized_section_id not in builders:
        return {
            "ok": False,
            "error": "Sezione stato non valida.",
            "generated_at": _event_bridge_timestamp_label(datetime.now(timezone.utc).isoformat()),
        }

    selected_ids = [normalized_section_id] if normalized_section_id else list(builders)
    sections = [builders[item_id]() for item_id in selected_ids]
    overall = _system_rollup_severity(sections)
    payload = {
        "ok": overall != "error",
        "severity": overall,
        "status_label": _system_severity_label(overall),
        "generated_at": _event_bridge_timestamp_label(datetime.now(timezone.utc).isoformat()),
        "summary": _system_summary_counts(sections),
        "sections": sections,
    }
    if normalized_section_id:
        payload["section"] = sections[0]
    return payload


def _system_app_section(config: dict[str, Any] | None, is_valid: bool) -> dict[str, Any]:
    severity = "ok" if config and is_valid else "error"
    return _system_section(
        "app",
        "Applicazione",
        [
            _system_item(
                "octohubs",
                "OctoHubs",
                severity,
                "Configurazione caricata" if severity == "ok" else "Configurazione non valida",
                detail="" if severity == "ok" else "Controlla il database PostgreSQL e le variabili di ambiente.",
                href="/app/configuration/services",
                status_code="ready" if severity == "ok" else "config_error",
                metrics=[
                    {"label": "Configurazione", "value": "PostgreSQL"},
                    {"label": "Event Bridge auth", "value": "Credenziali per-server"},
                ],
            )
        ],
    )


def _system_database_section(config: dict[str, Any] | None, is_valid: bool) -> dict[str, Any]:
    database_href = "/app/configuration/services?focus=configuration-database"
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
                href=database_href,
                status_code="disconnected",
            )
        )
        items.append(_system_backup_item())
        return _system_section("database", "Database", items)

    metrics = [
        {"label": "Host", "value": db_settings.get("HOST") or "URL"},
        {"label": "Nome DB", "value": db_settings.get("NAME") or "N/D"},
        {"label": "Utente", "value": db_settings.get("USER") or "N/D"},
    ]
    try:
        backend = _config_manager._DB_BACKEND or _config_manager._ensure_db_backend()
        migration_status = backend.get_migration_status()
    except Exception as exc:
        logger.error("Stato connessione database non disponibile:\n%s", format_exception_for_log(exc))
        items.extend(
            [
                _system_item(
                    "database-connection",
                    "Connessione database",
                    "error",
                    "Connessione non disponibile",
                    detail="Dettagli disponibili nei log dell'applicazione.",
                    href=database_href,
                    status_code="disconnected",
                    metrics=metrics,
                ),
                _system_item(
                    "database-migrations",
                    "Migrazioni",
                    "unknown",
                    "Migrazioni non verificabili",
                    detail="La connessione database non e' disponibile.",
                    href=database_href,
                    status_code="unknown",
                ),
            ]
        )
        items.append(_system_backup_item())
        return _system_section("database", "Database", items)

    items.append(
        _system_item(
            "database-connection",
            "Connessione database",
            "ok",
            "Connesso",
            href=database_href,
            status_code="connected",
            metrics=metrics,
        )
    )

    try:
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
                href=database_href,
                status_code="synced" if migration_severity == "ok" else "pending",
                metrics=[
                    {"label": "Applicate", "value": str(len(getattr(migration_status, "applied", []) or []))},
                    {"label": "Disponibili", "value": str(len(getattr(migration_status, "available", []) or []))},
                ],
            )
        )
    except Exception as exc:
        logger.error("Stato migrazioni non disponibile:\n%s", format_exception_for_log(exc))
        items.append(
            _system_item(
                "database-migrations",
                "Migrazioni",
                "warning",
                "Stato migrazioni non leggibile",
                detail="Dettagli disponibili nei log dell'applicazione.",
                href=database_href,
                status_code="unknown",
            )
        )

    items.append(_system_backup_item())
    return _system_section("database", "Database", items)


def _system_services_section(config: dict[str, Any] | None, *, check_services: bool) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    check_error = ""
    checked_at = ""
    if check_services:
        try:
            from services.manager import build_test_connections_snapshot_guarded

            payload, _status_code = build_test_connections_snapshot_guarded()
            payload_dict = payload if isinstance(payload, dict) else {}
            if not payload_dict or payload_dict.get("success") is False:
                check_error = "Verifica dei servizi non riuscita"
            statuses = payload_dict.get("statuses") or {}
            if not isinstance(statuses, dict):
                statuses = {}
            from app_state import get_connection_check_state

            checked_at = str(get_connection_check_state().get("checked_at") or "")
        except Exception:
            check_error = "Verifica dei servizi non riuscita"
    else:
        from app_state import get_connection_check_state

        last_check = get_connection_check_state()
        last_statuses = last_check.get("statuses")
        statuses = last_statuses if isinstance(last_statuses, dict) else {}
        checked_at = str(last_check.get("checked_at") or "")

    items: list[dict[str, Any]] = []
    for key, label in SYSTEM_SERVICE_LABELS.items():
        configured = _system_service_configured(config, key)
        service_href = SYSTEM_SERVICE_HREFS[key]
        if check_error:
            items.append(
                _system_item(
                    f"service-{key}",
                    label,
                    "warning",
                    "Verifica non riuscita",
                    detail=check_error,
                    href=service_href,
                    status_code="check_failed",
                )
            )
            continue
        if key in statuses:
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
                    href=service_href,
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
                href=service_href,
                status_code="configured" if configured else ("not_configured" if key != "database" else "disconnected"),
            )
        )
    return _system_section(
        "services",
        "Servizi e integrazioni",
        items,
        checked_at=checked_at,
    )


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
                    href="/app/configuration/servers",
                    status_code="not_configured",
                )
            ],
        )

    try:
        from emby_runtime.snapshots import _build_emby_health_status_snapshot

        payload, _status_code = _build_emby_health_status_snapshot()
        server_statuses = payload.get("data") if isinstance(payload, dict) else []
    except Exception as exc:
        logger.error("Stato Emby non disponibile:\n%s", format_exception_for_log(exc))
        return _system_section(
            "emby",
            "Server Emby",
            [
                _system_item(
                    "emby-health",
                    "Stato server",
                    "warning",
                    "Stato Emby non leggibile",
                    detail="Dettagli disponibili nei log dell'applicazione.",
                    href="/app/emby-live?focus=emby-live-servers",
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
                href="/app/emby-live?focus=emby-live-servers",
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
                    href="/app/configuration/event-bridge",
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
        differences = diagnostics.get("diffs") if isinstance(diagnostics.get("diffs"), list) else []
        difference_labels = [str(item.get("label") or "") for item in differences if isinstance(item, dict)]
        detail_parts = [str(diagnostics.get("last_config_ack_error") or "")]
        if difference_labels:
            detail_parts.append(f"Differenze: {', '.join(label for label in difference_labels if label)}")
        items.append(
            _system_item(
                f"event-bridge-{server.get('id')}",
                str(server.get("name") or "Server"),
                severity,
                f"{transport_label} · {sync_label}",
                detail=" · ".join(part for part in detail_parts if part),
                href="/app/configuration/event-bridge",
                status_code=status_code,
                metrics=[
                    {"label": "Plugin", "value": diagnostics.get("plugin_version") or "N/D"},
                    {"label": "Ultimo contatto", "value": diagnostics.get("last_seen_at") or "Mai"},
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
        logger.error("Stato Transcode Guard non disponibile:\n%s", format_exception_for_log(exc))
        return _system_section(
            "transcode-guard",
            "Transcode Guard",
            [
                _system_item(
                    "transcode-guard-status",
                    "Monitor",
                    "warning",
                    "Stato non leggibile",
                    detail="Dettagli disponibili nei log dell'applicazione.",
                    href="/app/transcode-guard",
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
                detail="Ultimo controllo disponibile nei log dell'applicazione." if last_result else "",
                href="/app/transcode-guard",
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
        logger.error("Centro operazioni non disponibile:\n%s", format_exception_for_log(exc))
        return _system_section(
            "operations",
            "Operazioni",
            [
                _system_item(
                    "operations-status",
                    "Centro operazioni",
                    "warning",
                    "Operazioni non leggibili",
                    detail="Dettagli disponibili nei log dell'applicazione.",
                    href="/app/emby-live",
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
    return _system_section(
        "operations",
        "Operazioni",
        [
            _system_item(
                "operations-status",
                "Centro operazioni",
                severity,
                summary,
                detail="Ultima operazione non completata. Consulta il centro operazioni.",
                href="/app/emby-live",
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
                href="/app/research/requests?focus=requests-refresh",
                status_code=status_code,
                metrics=[
                    {"label": "Completato", "value": _event_bridge_timestamp_label(state.get("completed_at")) or "Mai"},
                ],
            )
        ],
    )


def _system_backup_item() -> dict[str, Any]:
    """Describe the operator-owned backup boundary without guessing from files."""
    database_href = "/app/configuration/services?focus=configuration-database"
    return _system_item(
        "database-backups",
        "Backup PostgreSQL",
        "unknown",
        "Gestito esternamente",
        detail=(
            "Il database e i relativi backup sono gestiti dall'operatore; "
            "OctoHubs non puo verificarne esistenza o ripristinabilita."
        ),
        href=database_href,
        status_code="external",
        status_label="Gestito dall'operatore",
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


def _system_section(
    section_id: str,
    title: str,
    items: list[dict[str, Any]],
    *,
    checked_at: str = "",
) -> dict[str, Any]:
    severity = _system_rollup_severity(items)
    meta = SYSTEM_SECTION_META.get(section_id, {})
    return {
        "id": section_id,
        "title": title,
        "severity": severity,
        "status_code": severity,
        "status_label": _system_severity_label(severity),
        "items": items,
        "href": str(meta.get("href") or ""),
        "check_label": str(meta.get("check_label") or ""),
        "refresh_interval_seconds": int(meta.get("refresh_interval_seconds") or 0),
        "updated_at": _event_bridge_timestamp_label(datetime.now(timezone.utc).isoformat()),
        "checked_at": _event_bridge_timestamp_label(checked_at),
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
