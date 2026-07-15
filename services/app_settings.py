# services/app_settings.py
from core import config_manager
from core.config_manager import _ensure_db_backend
from core.storage import StorageError


def _update_app_settings_overrides(data):
    """Update application settings with overrides from data and save to database."""
    if config_manager._ACTIVE_CONFIG is None:
        return

    # Aggiorna la configurazione in memoria
    for key, value in data.items():
        if key in config_manager._ACTIVE_CONFIG:
            config_manager._ACTIVE_CONFIG[key] = value

    # Salva nel database
    try:
        backend = _ensure_db_backend()
        app_settings = backend.load_app_settings() or {}
        app_settings.update(data)
        backend.save_app_settings(app_settings)
    except StorageError:
        raise


def _refresh_request_overview_rules(config):
    """Refresh request overview rules from config."""
    return config.get("REQUEST_OVERVIEW_RULES", [])


def _parse_auto_task_payload(form, key, fallback):
    """Parse auto task payload from form data."""
    try:
        import json
        value = form.get(key, fallback)
        if isinstance(value, str):
            return json.loads(value)
        return value
    except Exception:
        return fallback
