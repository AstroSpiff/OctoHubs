# services/scan_results.py
import copy

from core.config_manager import _ensure_db_backend
from core.storage import StorageError


def save_results(summary):
    try:
        backend = _ensure_db_backend()
        backend.save_scan_result(summary)
    except StorageError as exc:
        print(f"   -> Non riesco a salvare i risultati nel database: {exc}")


def load_results_file():
    try:
        backend = _ensure_db_backend()
        return backend.load_last_result()
    except StorageError as exc:
        print(f"   -> Non riesco a leggere gli ultimi risultati dal database: {exc}")
        return None


def _merge_scan_summaries(previous, current):
    """Mantiene i risultati precedenti sostituendo soltanto quelli aggiornati dall'ultima ricerca."""
    if not current:
        return previous or {}
    merged = copy.deepcopy(current)
    new_items = []
    seen_keys = set()
    current_items = merged.get("items") or []
    current_generated = merged.get("generated_at")

    for item in current_items:
        normalized = copy.deepcopy(item)
        normalized["updated_at"] = current_generated
        normalized["is_stale"] = False
        key = (
            normalized.get("request_id"),
            normalized.get("season"),
            normalized.get("media_type"),
        )
        seen_keys.add(key)
        new_items.append(normalized)

    stale_items = []
    if previous and isinstance(previous.get("items"), list):
        for item in previous["items"]:
            key = (
                item.get("request_id"),
                item.get("season"),
                item.get("media_type"),
            )
            if key in seen_keys:
                continue
            stale = copy.deepcopy(item)
            stale["is_stale"] = True
            stale.setdefault("updated_at", previous.get("generated_at"))
            stale_items.append(stale)

    merged["items"] = new_items + stale_items
    merged["stale_count"] = len(stale_items)
    merged["previous_generated_at"] = previous.get("generated_at") if previous else None
    return merged
