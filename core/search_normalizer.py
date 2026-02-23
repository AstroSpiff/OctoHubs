from typing import Any, Dict, Iterable, List, Tuple

from core.scanner import sanitize_title


def _compute_size_gb(result: Dict[str, Any]) -> float:
    size_gb = result.get("size_gb")
    if size_gb is not None:
        return size_gb
    size_bytes = result.get("size", 0) or 0
    return round(size_bytes / (1024 ** 3), 2) if size_bytes else 0


def _compute_normalized_title(result: Dict[str, Any]) -> str:
    normalized = result.get("normalized_title")
    if normalized:
        return str(normalized)
    title = result.get("title") or ""
    return sanitize_title(str(title).lower())


def build_dedupe_key(result: Dict[str, Any]) -> Tuple[str, float]:
    """
    Create a unified dedupe key across manual + automatic searches.
    Uses normalized_title + size_gb like Ricerche & Riepilogo.
    """
    return (_compute_normalized_title(result), _compute_size_gb(result))


def dedupe_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return unique results using the unified dedupe key.
    Keeps first occurrence.
    """
    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        key = build_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
