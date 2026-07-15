# services/requests_cache.py
from core.config_manager import _ensure_db_backend


def _load_cached_requests_overview():
    """Load cached requests overview from file or database."""
    try:
        backend = _ensure_db_backend()
        data, timestamp = backend.load_request_overview()
        return data or [], timestamp
    except Exception:
        pass
    return [], None


def _save_cached_requests_overview(data):
    """Save cached requests overview to file or database."""
    try:
        backend = _ensure_db_backend()
        backend.save_request_overview(data)
    except Exception:
        pass
