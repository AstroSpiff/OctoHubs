# services/app_settings.py
from core import config_manager
from core.config_manager import _ensure_db_backend


@config_manager.serialized_config_update
def _update_app_settings_overrides(data):
    """Update application settings with overrides from data and save to database."""
    backend = _ensure_db_backend()
    persisted = backend.update_app_settings(data)

    # Publish the persisted values to the process-local cache only after commit.
    active = config_manager._ACTIVE_CONFIG or {}
    config_manager.publish_active_config_updates({
        key: persisted[key]
        for key in data
        if key in active and key in persisted
    })


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
