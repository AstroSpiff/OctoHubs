"""Compact history helpers for Latest Publications.

The visible Latest cache can be pruned aggressively. This history stores only
stable identities, version keys, and notification state so classification can
remain correct after old cards have disappeared from the UI cache.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

from core.utils import _parse_date_value


HISTORY_SECTIONS = ("movies", "series", "episodes")


def ensure_history(server_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return the per-server publication history, creating missing sections."""
    if not isinstance(server_state, dict):
        return {"movies": {}, "series": {}, "episodes": {}}

    history = server_state.get("history")
    if not isinstance(history, dict):
        history = {}
        server_state["history"] = history

    for section in HISTORY_SECTIONS:
        if not isinstance(history.get(section), dict):
            history[section] = {}

    return history


def get_history_entry(history: Dict[str, Any], section: str, key: Any) -> Optional[Dict[str, Any]]:
    """Look up a history entry by section/key."""
    if not isinstance(history, dict) or section not in HISTORY_SECTIONS:
        return None
    entries = history.get(section)
    if not isinstance(entries, dict):
        return None
    text_key = str(key or "").strip()
    if not text_key:
        return None
    entry = entries.get(text_key)
    return entry if isinstance(entry, dict) else None


def find_movie_identity_entry(
    entries: Any,
    *,
    state_key: Any = None,
    item_id: Any = None,
    signature: Any = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Find movie state through its current key or persisted identity aliases."""
    matches = matching_movie_identity_entries(
        entries,
        state_key=state_key,
        item_id=item_id,
        signature=signature,
    )
    if not matches:
        return "", None

    def preference(match: tuple[str, Dict[str, Any]]) -> tuple[int, int, int]:
        key, entry = match
        notification_evidence = int(
            isinstance(entry.get("notified_publications"), dict)
            or isinstance(entry.get("notified_destinations"), dict)
        )
        direct = int(key == str(state_key or "").strip())
        return int(bool(entry.get("notified"))), notification_evidence, direct

    preferred_key, preferred = max(matches, key=preference)
    merged = dict(preferred)
    entries_to_merge = [entry for _key, entry in matches]
    merged.update(mediainfo_snapshot(*entries_to_merge))
    merged.update(notification_snapshot(*entries_to_merge))
    return preferred_key, merged


def matching_movie_identity_entries(
    entries: Any,
    *,
    state_key: Any = None,
    item_id: Any = None,
    signature: Any = None,
) -> list[tuple[str, Dict[str, Any]]]:
    """Return every state alias belonging to the current movie identity."""
    if not isinstance(entries, dict):
        return []

    connected = _movie_identity_tokens(state_key)
    item_text = str(item_id or "").strip()
    signature_text = str(signature or "").strip()
    if item_text:
        connected.add(("item", item_text))
    if signature_text:
        connected.add(("signature", signature_text))

    remaining = [
        (str(key), candidate, _movie_identity_tokens(key, candidate))
        for key, candidate in entries.items()
        if isinstance(candidate, dict)
    ]
    return _consume_connected_movie_aliases(connected, remaining)


def _movie_identity_tokens(
    key: Any,
    entry: Optional[Dict[str, Any]] = None,
) -> set[tuple[str, str]]:
    output: set[tuple[str, str]] = set()
    key_text = str(key or "").strip()
    if key_text:
        output.add(("key", key_text))
    if not isinstance(entry, dict):
        return output
    for kind, value in (
        ("item", entry.get("item_id")),
        ("signature", entry.get("signature")),
    ):
        text = str(value or "").strip()
        if text:
            output.add((kind, text))
    return output


def _consume_connected_movie_aliases(
    connected: set[tuple[str, str]],
    remaining: list[tuple[str, Dict[str, Any], set[tuple[str, str]]]],
) -> list[tuple[str, Dict[str, Any]]]:
    matches: list[tuple[str, Dict[str, Any]]] = []
    changed = True
    while changed:
        changed = False
        pending = []
        for key, candidate, candidate_tokens in remaining:
            if connected & candidate_tokens:
                matches.append((key, candidate))
                connected.update(candidate_tokens)
                changed = True
            else:
                pending.append((key, candidate, candidate_tokens))
        remaining = pending
    return matches


def find_history_movie_entry(
    history: Dict[str, Any],
    *,
    state_key: Any = None,
    item_id: Any = None,
    signature: Any = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Find movie history while tolerating provider-signature enrichment."""
    entries = history.get("movies") if isinstance(history, dict) else None
    return find_movie_identity_entry(
        entries,
        state_key=state_key,
        item_id=item_id,
        signature=signature,
    )


def is_notified(*entries: Optional[Dict[str, Any]]) -> bool:
    """Return True if any state/history entry is fully notified."""
    for entry in entries:
        if isinstance(entry, dict) and bool(entry.get("notified")):
            return True
    return False


def media_source_key_set(*entries: Optional[Dict[str, Any]]) -> set[str]:
    """Collect known media source keys from state/history entries."""
    keys: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        values = entry.get("media_source_keys")
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value or "").strip()
            if text:
                keys.add(text)
    return keys


def mediainfo_snapshot(*entries: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge MediaInfo evidence and derive completeness from actual coverage."""
    source_keys = media_source_key_set(*entries)
    mediainfo_keys = {
        str(value or "").strip()
        for entry in entries
        if isinstance(entry, dict)
        for value in entry.get("mediainfo_source_keys") or []
        if str(value or "").strip()
    }
    return {
        "media_source_keys": sorted(source_keys),
        "mediainfo_source_keys": sorted(mediainfo_keys),
        "mediainfo_complete": bool(source_keys) and source_keys.issubset(
            mediainfo_keys
        ),
    }


def merge_key_lists(
    primary: Iterable[Any],
    existing: Iterable[Any],
    fallback: Iterable[Any] = (),
    max_count: int = 0,
) -> List[str]:
    """Merge version keys, keeping primary keys first and preserving uniqueness."""
    output: List[str] = []
    seen: set[str] = set()

    def add_many(values: Iterable[Any]) -> None:
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            output.append(text)

    add_many(primary)
    add_many(existing)
    if not output:
        add_many(fallback)

    if max_count > 0:
        return output[:max_count]
    return output


def _later_timestamp(current: str, candidate: Any) -> str:
    candidate_text = str(candidate or "").strip()
    if not candidate_text:
        return current
    current_dt = _parse_date_value(current)
    candidate_dt = _parse_date_value(candidate_text)
    if current_dt is None or (
        candidate_dt is not None and candidate_dt > current_dt
    ):
        return candidate_text
    return current


def _merge_publication_notifications(
    publications: Dict[str, Any],
    incoming: Dict[str, Any],
) -> None:
    for publication_key, publication in incoming.items():
        if not isinstance(publication, dict):
            continue
        current = publications.get(publication_key)
        current = current if isinstance(current, dict) else {}
        merged = {**current, **deepcopy(publication)}
        merged_destinations = {}
        for values in (
            current.get("notified_destinations"),
            publication.get("notified_destinations"),
        ):
            if isinstance(values, dict):
                merged_destinations.update(deepcopy(values))
        if merged_destinations:
            merged["notified_destinations"] = merged_destinations
        merged["notified"] = bool(
            current.get("notified") or publication.get("notified")
        )
        merged["notified_at"] = _later_timestamp(
            str(current.get("notified_at") or ""),
            publication.get("notified_at"),
        )
        publications[str(publication_key)] = merged


def notification_snapshot(*entries: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge notification evidence without dropping alias/destination history."""
    notified = False
    notified_at = ""
    destinations: Dict[str, Any] = {}
    publications: Dict[str, Any] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        notified = notified or bool(entry.get("notified"))
        notified_at = _later_timestamp(notified_at, entry.get("notified_at"))
        entry_destinations = entry.get("notified_destinations")
        if isinstance(entry_destinations, dict):
            destinations.update(deepcopy(entry_destinations))
        entry_publications = entry.get("notified_publications")
        if isinstance(entry_publications, dict):
            _merge_publication_notifications(publications, entry_publications)

    snapshot: Dict[str, Any] = {
        "notified": notified,
        "notified_at": notified_at,
    }
    if destinations:
        snapshot["notified_destinations"] = destinations
    if publications:
        snapshot["notified_publications"] = publications
    return snapshot


def update_history_entry(
    history: Dict[str, Any],
    section: str,
    key: Any,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge payload into a history entry and return the stored entry."""
    if section not in HISTORY_SECTIONS:
        raise ValueError(f"Unsupported history section: {section}")
    if not isinstance(history.get(section), dict):
        history[section] = {}

    text_key = str(key or "").strip()
    if not text_key:
        return {}

    existing = history[section].get(text_key)
    if not isinstance(existing, dict):
        existing = {}
    merged = {**existing, **payload}

    if "media_source_keys" in existing or "media_source_keys" in payload:
        merged["media_source_keys"] = merge_key_lists(
            payload.get("media_source_keys") or [],
            existing.get("media_source_keys") or [],
        )
    if "seasons" in existing or "seasons" in payload:
        seasons = set()
        for value in list(existing.get("seasons") or []) + list(payload.get("seasons") or []):
            try:
                seasons.add(int(value))
            except (TypeError, ValueError):
                continue
        merged["seasons"] = sorted(seasons)

    merged.update(notification_snapshot(existing, payload))
    history[section][text_key] = merged
    return merged
