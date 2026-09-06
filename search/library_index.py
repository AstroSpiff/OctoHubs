"""Helpers to build Emby library title index for search."""

from __future__ import annotations

class LibraryIndexUnavailableError(RuntimeError):
    """Raised when library membership cannot be determined authoritatively."""


def _load_emby_library_title_index(normalized_titles=None):
    candidates = {
        str(value)
        for value in (normalized_titles or ())
        if isinstance(value, str) and value
    }
    if not candidates:
        return set()
    try:
        from core.config_manager import _ensure_db_backend

        backend = _ensure_db_backend()
        return set(backend.get_probe_matching_titles(candidates))
    except Exception as exc:
        raise LibraryIndexUnavailableError(
            "Impossibile verificare la presenza nella libreria Emby"
        ) from exc


__all__ = ["LibraryIndexUnavailableError", "_load_emby_library_title_index"]
