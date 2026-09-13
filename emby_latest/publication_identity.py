"""Stable identities for visible Latest publication events."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional, Tuple

from core.utils import _parse_date_value, normalize_path


_EVENT_FIELDS = ("batch_id", "update_type", "update_label", "changes", "added_at")
def _text(value: Any) -> str:
    return str(value or "").strip()


def publication_logical_aliases(
    entry: Dict[str, Any],
    family: str,
) -> Tuple[Tuple[str, str, str], ...]:
    """Return stable aliases for one title despite enrichment/grouping drift."""
    server_id = _text(entry.get("server_id"))
    aliases = []
    for kind, value in (
        ("item", entry.get("item_id")),
        ("signature", entry.get("signature")),
    ):
        identity = _text(value)
        if server_id and identity:
            aliases.append((family, server_id, f"{kind}:{identity}"))
    return tuple(aliases)


def _canonical_timestamp(value: Any) -> str:
    parsed = _parse_date_value(value)
    return parsed.isoformat() if parsed is not None else _text(value)


def _change_identity(change: Dict[str, Any]) -> Tuple[str, ...]:
    """Identify a source without depending on mutable MediaInfo metadata."""
    # Match the collector's canonical version key: a normalized path wins over
    # the MediaSource ID. Emby may reuse an ID for a replaced file, while the
    # path is what the state tracker uses to recognise a genuinely new source.
    # Episode titles and coordinates are descriptive metadata and can be
    # corrected later; they must not split an otherwise durable source.
    path = normalize_path(change.get("path"))
    if path:
        return ("path", path)

    source_id = _text(change.get("media_source_id"))
    if source_id:
        return ("source_id", source_id)

    added_at = _canonical_timestamp(change.get("added_at"))
    source_name = normalize_path(change.get("source_name"))
    if source_name:
        return ("source_name", source_name, added_at)

    # Historical entries can lack every durable source identifier. In that
    # case retain enough immutable-looking evidence to avoid conflating two
    # unrelated versions, while canonicalizing the timestamp representation.
    return (
        "fallback",
        added_at,
        _text(change.get("season_number")),
        _text(change.get("episode_number")),
        _text(change.get("episode_title")).casefold(),
    )


def publication_event_key(
    entry: Dict[str, Any],
    family: str,
) -> Optional[Tuple[Any, ...]]:
    """Identify a publication by its actual changed sources, not refresh batch."""
    if not isinstance(entry, dict):
        return None
    server_id = _text(entry.get("server_id"))
    if not server_id:
        return None
    changes = entry.get("changes")
    if not isinstance(changes, list) or not changes:
        return None
    identities = [
        _change_identity(change)
        for change in changes
        if isinstance(change, dict)
    ]
    identities = [identity for identity in identities if any(identity)]
    if not identities:
        return None
    # Durable source identities are already scoped by server and are more
    # stable than either a provider signature or a representative Emby item ID.
    return family, server_id, tuple(sorted(identities))


def _events_are_equivalent(
    left: Dict[str, Any],
    right: Dict[str, Any],
    family: str,
) -> bool:
    left_key = publication_event_key(left, family)
    right_key = publication_event_key(right, family)
    if left_key is None or left_key != right_key:
        return False
    identities = left_key[-1]
    if not any(identity[0] == "fallback" for identity in identities):
        return True
    # Fallback metadata is not globally unique. Require at least one stable
    # logical alias, but allow either item ID or provider signature to evolve.
    return bool(
        set(publication_logical_aliases(left, family))
        & set(publication_logical_aliases(right, family))
    )


def is_existing_snapshot(entry: Dict[str, Any]) -> bool:
    """Return whether an entry describes no new user-visible publication."""
    if _text(entry.get("update_type")).lower() == "existing":
        return True
    changes = entry.get("changes")
    valid_changes = [change for change in changes or [] if isinstance(change, dict)]
    return bool(valid_changes) and all(
        _text(change.get("kind")).lower() == "existing"
        for change in valid_changes
    )


def _classification_rank(entry: Dict[str, Any]) -> int:
    update_type = _text(entry.get("update_type")).lower()
    if update_type == "new":
        return 0
    if update_type == "update":
        return 1
    if is_existing_snapshot(entry):
        return 3
    return 2


def _preferred_event(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    def preference(entry: Dict[str, Any]) -> Tuple[int, str]:
        batch_id = _text(entry.get("batch_id"))
        return _classification_rank(entry), batch_id or "\uffff"

    return left if preference(left) <= preference(right) else right


def _event_timestamp(entry: Dict[str, Any]) -> float:
    values = [entry.get("added_at")]
    changes = entry.get("changes")
    if isinstance(changes, list):
        values.extend(
            change.get("added_at")
            for change in changes
            if isinstance(change, dict)
        )
    parsed = [_parse_date_value(value) for value in values]
    timestamps = [value.timestamp() for value in parsed if value is not None]
    return max(timestamps, default=float("-inf"))


def _with_event_envelope(
    metadata_source: Dict[str, Any],
    event_source: Dict[str, Any],
) -> Dict[str, Any]:
    output = dict(metadata_source)
    for field in _EVENT_FIELDS:
        if field in event_source:
            output[field] = deepcopy(event_source[field])
    return output


def _equivalence_components(
    nodes: list[Dict[str, Any]],
    candidate_count: int,
    family: str,
) -> tuple[Dict[int, list[int]], Any]:
    """Build transitive event components while exposing only candidates."""
    parents = list(range(len(nodes)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = root(left)
        right_root = root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(nodes)):
        for right in range(left + 1, len(nodes)):
            if _events_are_equivalent(nodes[left], nodes[right], family):
                union(left, right)

    components: Dict[int, list[int]] = {}
    for index in range(candidate_count):
        components.setdefault(root(index), []).append(index)
    return components, root


def _component_event(
    nodes: list[Dict[str, Any]],
    root: Any,
    component_root: int,
) -> Dict[str, Any]:
    members = [
        node for index, node in enumerate(nodes) if root(index) == component_root
    ]
    event_source = members[0]
    for member in members[1:]:
        event_source = _preferred_event(event_source, member)
    return event_source


def deduplicate_publication_events(
    entries: Iterable[Any],
    family: str,
    *,
    bridge_entries: Iterable[Any] = (),
    preferred_entries: Iterable[Any] = (),
) -> list[Dict[str, Any]]:
    """Collapse only identical publication events while preserving true updates."""
    raw_candidates = [entry for entry in entries or [] if isinstance(entry, dict)]
    preferred_ids = {
        id(entry) for entry in preferred_entries or [] if isinstance(entry, dict)
    }
    candidate_is_preferred = [id(entry) in preferred_ids for entry in raw_candidates]
    candidates = [dict(entry) for entry in raw_candidates]
    bridges = [
        dict(entry) for entry in bridge_entries or [] if isinstance(entry, dict)
    ]
    nodes = [*candidates, *bridges]
    components, root = _equivalence_components(nodes, len(candidates), family)

    output = []
    for indices in sorted(components.values(), key=lambda values: values[0]):
        metadata_index = next(
            (index for index in indices if candidate_is_preferred[index]),
            indices[0],
        )
        metadata_source = candidates[metadata_index]
        event_source = _component_event(nodes, root, root(indices[0]))
        output.append(_with_event_envelope(metadata_source, event_source))
    return output


def _matching_event_component(
    candidate: Dict[str, Any],
    cached_entries: list[Dict[str, Any]],
    family: str,
) -> list[Dict[str, Any]]:
    """Find the complete cached alias chain connected to one event."""
    connected = [candidate]
    remaining = list(cached_entries)
    changed = True
    while changed:
        changed = False
        pending = []
        for entry in remaining:
            if any(
                _events_are_equivalent(entry, known, family)
                for known in connected
            ):
                connected.append(entry)
                changed = True
            else:
                pending.append(entry)
        remaining = pending
    return connected[1:]


def _visible_events_by_alias(
    cached: list[Dict[str, Any]],
    family: str,
) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    visible: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for entry in cached:
        if is_existing_snapshot(entry):
            continue
        for alias in publication_logical_aliases(entry, family):
            current = visible.get(alias)
            if current is None or _event_timestamp(entry) > _event_timestamp(current):
                visible[alias] = entry
            elif _event_timestamp(entry) == _event_timestamp(current):
                visible[alias] = _preferred_event(current, entry)
    return visible


def _event_source_for_candidate(
    candidate: Dict[str, Any],
    raw_cached: list[Dict[str, Any]],
    visible_by_alias: Dict[Tuple[str, str, str], Dict[str, Any]],
    family: str,
) -> Optional[Dict[str, Any]]:
    matching_events = _matching_event_component(candidate, raw_cached, family)
    event_source = None
    for matching in matching_events:
        event_source = (
            matching
            if event_source is None
            else _preferred_event(event_source, matching)
        )
    if event_source is not None or not is_existing_snapshot(candidate):
        return event_source
    candidates = [
        visible_by_alias[alias]
        for alias in publication_logical_aliases(candidate, family)
        if alias in visible_by_alias
    ]
    return max(
        candidates,
        key=lambda entry: (
            _event_timestamp(entry),
            -_classification_rank(entry),
        ),
    ) if candidates else None


def reconcile_publication_events(
    fresh_entries: Iterable[Any],
    cached_entries: Iterable[Any],
    family: str,
) -> list[Dict[str, Any]]:
    """Keep an existing event's meaning when a refresh observes no new source."""
    raw_cached = [dict(entry) for entry in cached_entries or [] if isinstance(entry, dict)]
    cached = deduplicate_publication_events(raw_cached, family)
    visible_by_alias = _visible_events_by_alias(cached, family)

    reconciled: list[Dict[str, Any]] = []
    for candidate in fresh_entries or []:
        if not isinstance(candidate, dict):
            continue
        event_source = _event_source_for_candidate(
            candidate,
            raw_cached,
            visible_by_alias,
            family,
        )
        reconciled.append(
            _with_event_envelope(candidate, event_source)
            if event_source is not None
            else dict(candidate)
        )
    return deduplicate_publication_events(reconciled, family)
