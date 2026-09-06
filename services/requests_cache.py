# services/requests_cache.py
from core.config_manager import _ensure_db_backend


def _load_cached_requests_overview():
    """Load the cached requests overview from the configured database."""
    backend = _ensure_db_backend()
    data, timestamp = backend.load_request_overview()
    return data or [], timestamp


def _save_cached_requests_overview(data):
    """Save the cached requests overview to the configured database."""
    backend = _ensure_db_backend()
    backend.save_request_overview(data)
