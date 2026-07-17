"""Runtime bootstrapping helpers."""

from __future__ import annotations

import asyncio
import os

from app_state import get_operation_tracker, register_app_event_loop
from core.config_manager import _db_enabled, _ensure_db_backend, load_config
from core.tasks import workflow_manager


def load_config_env_file() -> None:
    """Load environment variables from /config/.env if present."""
    config_dir = os.path.dirname(os.environ.get("OCTOHUB_CONFIG_FILE", "/config/config.json"))
    env_file_path = os.path.join(config_dir, ".env")
    if os.path.exists(env_file_path):
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file_path, override=False)  # Don't override existing ENV vars
            print(f"[STARTUP] Loaded environment variables from {env_file_path}")
        except Exception as exc:
            print(f"[STARTUP] Warning: Could not load {env_file_path}: {exc}")


async def register_runtime_event_loop() -> None:
    """Memorizza l'event loop usato da FastAPI per scheduling esterni."""
    print("\n" + "=" * 100, flush=True)
    print("🚀 OCTOHUB STARTUP - MEGA LOGGING ENABLED", flush=True)
    print("=" * 100 + "\n", flush=True)
    register_app_event_loop(asyncio.get_event_loop())


def initialize_runtime_services() -> None:
    """Initialize background services."""
    from emby_probe import get_probe_manager
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

    get_probe_manager().configure(_ensure_db_backend)
    _initialize_emby_websockets()
    workflow_manager.set_callbacks(
        trigger_scan_func=_wf_trigger_scan,
        check_scan_func=_wf_check_scan,
        trigger_probe_func=_wf_trigger_probe,
        check_probe_func=_wf_check_probe,
        stop_probe_func=_wf_stop_probe,
        refresh_cache_func=_wf_refresh_cache,
        notify_func=_wf_notify,
    )

    # Configura DatabaseStorage per workflow tracking
    db_storage = None
    try:
        db_storage = _ensure_db_backend()
        workflow_manager.set_db_storage(db_storage)
        workflow_manager.set_operation_tracker(get_operation_tracker())
    except Exception as exc:
        print(f"[STARTUP] ⚠️ DatabaseStorage non disponibile per workflow: {exc}")
        workflow_manager.set_db_storage(None)
        workflow_manager.set_operation_tracker(None)

    # Initialize configuration and AutoScheduler at startup
    try:
        print("[STARTUP] Inizializzazione configurazione e AutoScheduler...")
        config, is_valid = load_config()
        if is_valid:
            print("[STARTUP] Configurazione caricata correttamente, AutoScheduler attivo.")
        else:
            print("[STARTUP] Configurazione non valida, AutoScheduler non attivo.")
        if is_valid and config and _db_enabled(config.get("DATABASE", {})):
            from emby_latest import get_manager as get_latest_manager

            if db_storage is None:
                try:
                    db_storage = _ensure_db_backend()
                except Exception as exc:
                    print(f"[STARTUP] ⚠️ DatabaseStorage non disponibile per Latest: {exc}")
                    db_storage = None
            if db_storage is not None:
                get_latest_manager(config, db_storage)
    except Exception as exc:
        print(f"[STARTUP] Errore init runtime services: {exc}")
