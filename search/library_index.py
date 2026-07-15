"""Helpers to build Emby library title index for search."""

from __future__ import annotations

from core.scanner import sanitize_title


def _load_emby_library_title_index():
    try:
        from core.config_manager import _ensure_db_backend

        backend = _ensure_db_backend()
    except Exception:
        return set()
    try:
        entries = backend.get_probe_queue()
    except Exception:
        entries = []
    try:
        history_entries = backend.get_probe_history(limit=5000)
    except Exception:
        history_entries = []
    titles = set()
    for entry in entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    for entry in history_entries:
        for key in ("series_name", "name"):
            value = entry.get(key)
            if value:
                titles.add(sanitize_title(str(value).lower()))
    return titles
