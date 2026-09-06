"""Runtime bootstrapping helpers."""

from __future__ import annotations

import asyncio
import logging
import time
import os
from collections.abc import Awaitable, Callable

from app_state import initialize_operation_tracker, register_app_event_loop
from core.config_manager import _db_enabled, _ensure_db_backend, load_config
from core.env import octohubs_env
from core.log_sanitization import format_exception_for_log, sanitize_text_for_log
from core.safe_output import safe_print as print
from core.tasks import workflow_manager

logger = logging.getLogger(__name__)


def _log_startup_exception(context: str, error: BaseException, *, flush: bool = False) -> None:
    print(
        f"[STARTUP] {context}:",
        format_exception_for_log(error),
        sep="\n",
        flush=flush,
    )


def load_config_env_file() -> None:
    """Load environment variables from /config/.env if present."""
    config_dir = octohubs_env("OCTOHUBS_CONFIG_DIR", "/config")
    env_file_path = os.path.join(config_dir, ".env")
    if os.path.exists(env_file_path):
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file_path, override=False)  # Don't override existing ENV vars
            print(f"[STARTUP] Loaded environment variables from {env_file_path}")
        except Exception as exc:
            _log_startup_exception(
                f"Warning: Could not load {sanitize_text_for_log(env_file_path)}",
                exc,
            )


async def register_runtime_event_loop(storage=None) -> None:
    """Memorizza l'event loop usato da FastAPI per scheduling esterni."""
    print("\n" + "=" * 100, flush=True)
    print("🚀 OCTOHUBS STARTUP - MEGA LOGGING ENABLED", flush=True)
    print("=" * 100 + "\n", flush=True)
    register_app_event_loop(asyncio.get_running_loop())
    from emby_runtime.library_poller import get_library_poller

    resolved_storage = storage if storage is not None else _ensure_db_backend()
    poller = get_library_poller()
    poller.configure(resolved_storage, reopen=True)
    interrupted = await poller.finalize_interrupted_states()
    if interrupted:
        print(
            f"[STARTUP] {interrupted} scan librerie interrotti dal precedente riavvio.",
            flush=True,
        )


def _configure_workflow_tracking(db_storage):
    """Attach one resolved backend to workflows or disable tracking explicitly."""
    try:
        resolved = db_storage if db_storage is not None else _ensure_db_backend()
        workflow_manager.set_db_storage(resolved)
        workflow_manager.set_operation_tracker(initialize_operation_tracker())
        return resolved
    except Exception as exc:
        _log_startup_exception("⚠️ DatabaseStorage non disponibile per workflow", exc)
        workflow_manager.set_db_storage(None)
        workflow_manager.set_operation_tracker(None)
        return None


def _initialize_latest_runtime(config, is_valid, db_storage) -> None:
    """Initialize the database-backed Latest service from an existing backend."""
    if not (is_valid and config and _db_enabled(config.get("DATABASE", {}))):
        return
    from emby_latest import get_manager as get_latest_manager
    from emby_users.password_crypto import (
        PasswordCiphertextError,
        PasswordSecretError,
        finalize_password_secret_rotation,
        rotate_stored_password_ciphertexts,
    )

    if db_storage is None:
        return
    rotated_passwords = rotate_stored_password_ciphertexts(db_storage)
    if rotated_passwords:
        print(
            f"[STARTUP] Ricifrate {rotated_passwords} password Emby "
            "con PASSWORD_SECRET corrente."
        )
    try:
        finalized_rotation = finalize_password_secret_rotation()
    except PasswordSecretError as exc:
        raise PasswordCiphertextError(str(exc)) from exc
    if finalized_rotation:
        print("[STARTUP] Rotazione PASSWORD_SECRET resa persistente.")
    get_latest_manager(config, db_storage)


def initialize_runtime_services(*, config=None, is_valid=None, db_storage=None) -> None:
    """Initialize background services."""
    from app_state import set_connection_check_state
    from services.background_jobs import initialize_background_jobs
    from services.connection_check_guard import connection_check_coordinator
    from emby_users.password_crypto import (
        PasswordCiphertextError,
    )
    from emby_probe import get_probe_manager
    from emby_runtime.event_bridge_manager import initialize_event_bridge_manager
    from realtime.manager import _initialize_emby_websockets
    from services.workflows import (
        _wf_trigger_scan,
        _wf_check_scan,
        _wf_trigger_probe,
        _wf_check_probe,
        _wf_stop_probe,
        _wf_refresh_cache,
        _wf_notify,
    )
    from realtime.status_snapshot import initialize_status_snapshot_cache
    from emby_latest.api_handlers import start_accepting_latest_refresh

    initialize_status_snapshot_cache()
    start_accepting_latest_refresh()
    connection_check_coordinator.reset()
    set_connection_check_state({}, None)
    from emby_runtime.scan_websocket_manager import initialize_scan_connection_manager

    initialize_scan_connection_manager()
    initialize_event_bridge_manager()
    initialize_background_jobs()
    workflow_manager.start_accepting()
    storage_provider = (lambda: db_storage) if db_storage is not None else _ensure_db_backend
    get_probe_manager().configure(storage_provider, reopen=True)
    _initialize_emby_websockets()
    try:
        from emby_runtime.transcode_guard import get_transcode_guard_service

        get_transcode_guard_service().start()
        print("[STARTUP] Transcode Guard monitor pronto.")
    except Exception as exc:
        _log_startup_exception("⚠️ Transcode Guard non avviato", exc)
    workflow_manager.set_callbacks(
        trigger_scan_func=_wf_trigger_scan,
        check_scan_func=_wf_check_scan,
        trigger_probe_func=_wf_trigger_probe,
        check_probe_func=_wf_check_probe,
        stop_probe_func=_wf_stop_probe,
        refresh_cache_func=_wf_refresh_cache,
        notify_func=_wf_notify,
    )

    db_storage = _configure_workflow_tracking(db_storage)

    # Initialize configuration and AutoScheduler at startup
    try:
        print("[STARTUP] Inizializzazione configurazione e AutoScheduler...")
        if is_valid is None:
            config, is_valid = load_config()
        if is_valid:
            print("[STARTUP] Configurazione caricata correttamente, AutoScheduler attivo.")
        else:
            print("[STARTUP] Configurazione non valida, AutoScheduler non attivo.")
        _initialize_latest_runtime(config, is_valid, db_storage)
    except PasswordCiphertextError:
        raise
    except Exception as exc:
        _log_startup_exception("Errore init runtime services", exc)


def _threaded_shutdown_steps() -> tuple[tuple[str, Callable[[float], bool]], ...]:
    from emby_probe import get_probe_manager
    from emby_latest.api_handlers import shutdown_latest_refresh
    from emby_runtime.transcode_guard import get_transcode_guard_service
    from services.scheduler_manager import shutdown_scheduler
    from search.outbound_execution import shutdown_search_executor
    from services.background_jobs import shutdown_background_jobs

    return (
        ("auto scheduler", shutdown_scheduler),
        ("workflow", workflow_manager.shutdown),
        ("Latest refresh", shutdown_latest_refresh),
        ("search executor", shutdown_search_executor),
        ("Emby realtime", _shutdown_emby_realtime),
        ("background jobs", shutdown_background_jobs),
        ("probe", get_probe_manager().shutdown),
        ("Transcode Guard", get_transcode_guard_service().shutdown),
    )


def _shutdown_emby_realtime(timeout_seconds: float) -> bool:
    """Stop the event source before draining its Sessions dispatcher."""
    from emby_runtime.websocket_manager import get_websocket_manager
    from realtime.manager import shutdown_session_refresh_dispatcher

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    websocket_stopped = get_websocket_manager().stop_all(
        max(0.0, deadline - time.monotonic())
    )
    dispatcher_stopped = shutdown_session_refresh_dispatcher(
        max(0.0, deadline - time.monotonic())
    )
    return bool(websocket_stopped and dispatcher_stopped)


def _async_shutdown_steps() -> tuple[tuple[str, Callable[[], Awaitable[None]]], ...]:
    from emby_runtime.event_bridge_manager import get_event_bridge_manager
    from emby_runtime.library_poller import get_library_poller
    from emby_runtime.scan_websocket_manager import get_scan_connection_manager

    return (
        ("Event Bridge manager", get_event_bridge_manager().shutdown),
        ("library poller", get_library_poller().stop_all),
        ("scan WebSocket manager", get_scan_connection_manager().shutdown),
    )


async def _run_threaded_shutdown_step(
    name: str,
    callback: Callable[[float], bool],
    timeout_seconds: float,
) -> bool:
    try:
        stopped = await asyncio.to_thread(callback, timeout_seconds)
    except Exception as exc:
        logger.error("[SHUTDOWN] Arresto %s non riuscito:\n%s", name, format_exception_for_log(exc))
        return False
    if not stopped:
        logger.warning("[SHUTDOWN] %s non terminato entro %.1fs", name, timeout_seconds)
    return bool(stopped)


async def _run_async_shutdown_step(
    name: str,
    callback: Callable[[], Awaitable[bool | None]],
    timeout_seconds: float,
) -> bool:
    try:
        stopped = await asyncio.wait_for(callback(), timeout=timeout_seconds)
        if stopped is False:
            logger.warning("[SHUTDOWN] %s non terminato entro %.1fs", name, timeout_seconds)
            return False
        return True
    except TimeoutError:
        logger.warning("[SHUTDOWN] %s non terminato entro %.1fs", name, timeout_seconds)
    except Exception as exc:
        logger.error("[SHUTDOWN] Arresto %s non riuscito:\n%s", name, format_exception_for_log(exc))
    return False


async def shutdown_runtime_services(timeout_seconds: float = 5.0) -> bool:
    """Stop runtime workers concurrently, then release subscribers and DB pools."""
    from app_state import (
        clear_app_event_loop,
        set_connection_check_state,
        shutdown_operation_tracker,
    )
    from core.auth import shutdown_auth
    from core.config_manager import close_database_backend
    from realtime.subscribers import sse_subscribers, websocket_subscribers
    from services.connection_check_guard import connection_check_coordinator
    from services.scheduler_manager import begin_scheduler_shutdown
    from emby_latest.api_handlers import begin_latest_refresh_shutdown
    from emby_probe import get_probe_manager
    from realtime.status_snapshot import (
        begin_status_snapshot_shutdown,
        shutdown_status_snapshot_cache,
    )

    timeout_seconds = max(0.1, float(timeout_seconds))
    # Close every downstream admission gate before producers and consumers are
    # drained concurrently. This makes the shutdown snapshot monotonic.
    begin_scheduler_shutdown()
    begin_latest_refresh_shutdown()
    workflow_manager.begin_shutdown()
    get_probe_manager().begin_shutdown()
    begin_status_snapshot_shutdown()
    worker_steps = [
        _run_threaded_shutdown_step(name, callback, timeout_seconds)
        for name, callback in _threaded_shutdown_steps()
    ]
    worker_steps.extend(
        _run_async_shutdown_step(name, callback, timeout_seconds)
        for name, callback in _async_shutdown_steps()
    )
    worker_steps.append(
        _run_async_shutdown_step(
            "status snapshot producers",
            lambda: shutdown_status_snapshot_cache(timeout_seconds),
            timeout_seconds,
        )
    )

    workers_stopped = False
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*worker_steps),
            timeout=timeout_seconds + 0.5,
        )
        workers_stopped = all(results)
    except TimeoutError:
        logger.warning("[SHUTDOWN] Timeout globale durante l'arresto dei worker")
    finally:
        connection_check_coordinator.reset()
        set_connection_check_state({}, None)
        sse_subscribers.close_all()
        websocket_subscribers.close_all()
        clear_app_event_loop()

    if workers_stopped:
        tracker_stopped = await _run_threaded_shutdown_step(
            "operation tracker",
            shutdown_operation_tracker,
            timeout_seconds,
        )
        workers_stopped = workers_stopped and tracker_stopped

    if workers_stopped:
        pools_closed = True
        try:
            if shutdown_auth() is False:
                pools_closed = False
        except Exception as exc:
            pools_closed = False
            logger.error(
                "[SHUTDOWN] Chiusura autenticazione non riuscita:\n%s",
                format_exception_for_log(exc),
            )
        try:
            close_database_backend()
        except Exception as exc:
            pools_closed = False
            logger.error(
                "[SHUTDOWN] Chiusura database applicativo non riuscita:\n%s",
                format_exception_for_log(exc),
            )
        workers_stopped = workers_stopped and pools_closed
    else:
        logger.warning("[SHUTDOWN] Pool database lasciati al processo: worker ancora attivi")
    return workers_stopped
