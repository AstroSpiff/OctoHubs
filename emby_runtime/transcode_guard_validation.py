"""Resource bounds for Transcode Guard settings supplied by users or storage."""

from __future__ import annotations

import json
from typing import Any


MAX_TRANSCODE_GUARD_RULES = 100
MAX_TRANSCODE_GUARD_RULE_DEPTH = 4
MAX_TRANSCODE_GUARD_GROUP_CHILDREN = 50
MAX_TRANSCODE_GUARD_LIST_ITEMS = 50
MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH = 128
MAX_TRANSCODE_GUARD_NAME_LENGTH = 160
MAX_TRANSCODE_GUARD_MESSAGE_LENGTH = 2048
MAX_TRANSCODE_GUARD_TEXT_BYTES = 128 * 1024
MAX_TRANSCODE_GUARD_PERSISTED_BYTES = 256 * 1024

_SCOPE_FIELDS = (
    "server_ids",
    "excluded_users",
    "excluded_clients",
    "excluded_devices",
    "excluded_ips",
)
_SHORT_TEXT_FIELDS = (
    "id",
    "profile",
    "mode",
    "video_state",
    "audio_state",
    "remux_state",
    "transformation_state",
    "message_display_mode",
)


def _text_bytes(value: Any, *, maximum: int, field: str) -> int:
    if not isinstance(value, str):
        return 0
    encoded_length = len(value.encode("utf-8"))
    if encoded_length > maximum:
        raise ValueError(f'Il campo Transcode Guard "{field}" supera il limite consentito.')
    return encoded_length


def _sequence_text_bytes(value: Any, *, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        _text_bytes(
            value,
            maximum=(MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH + 1) * MAX_TRANSCODE_GUARD_LIST_ITEMS,
            field=field,
        )
        items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        return 0
    if len(items) > MAX_TRANSCODE_GUARD_LIST_ITEMS:
        raise ValueError(f'Il campo Transcode Guard "{field}" contiene troppi elementi.')
    total = 0
    for item in items:
        total += _text_bytes(
            item,
            maximum=MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH,
            field=field,
        )
    return total


def _node_text_bytes(node: dict[str, Any]) -> int:
    total = 0
    for field in _SHORT_TEXT_FIELDS:
        total += _text_bytes(
            node.get(field),
            maximum=MAX_TRANSCODE_GUARD_IDENTIFIER_LENGTH,
            field=field,
        )
    total += _text_bytes(
        node.get("name"),
        maximum=MAX_TRANSCODE_GUARD_NAME_LENGTH,
        field="name",
    )
    for field in ("message_header", "message_text"):
        total += _text_bytes(
            node.get(field),
            maximum=MAX_TRANSCODE_GUARD_MESSAGE_LENGTH,
            field=field,
        )
    for field in _SCOPE_FIELDS:
        total += _sequence_text_bytes(node.get(field), field=field)
    return total


def validate_transcode_guard_settings_payload(raw: Any) -> None:
    """Reject expansive settings iteratively before rule normalization recurses."""

    if not isinstance(raw, dict):
        return

    text_bytes = _node_text_bytes(raw)
    raw_rules = raw.get("rules")
    if raw_rules is None:
        return
    if not isinstance(raw_rules, list):
        return
    if len(raw_rules) > MAX_TRANSCODE_GUARD_RULES:
        raise ValueError("La configurazione Transcode Guard contiene troppe regole.")

    rule_count = 0
    leaf_count = 0
    stack = [(rule, 1) for rule in reversed(raw_rules) if isinstance(rule, dict)]
    while stack:
        rule, depth = stack.pop()
        rule_count += 1
        if rule_count > MAX_TRANSCODE_GUARD_RULES:
            raise ValueError("La configurazione Transcode Guard contiene troppe regole.")
        if depth > MAX_TRANSCODE_GUARD_RULE_DEPTH:
            raise ValueError("La configurazione Transcode Guard contiene gruppi troppo profondi.")

        text_bytes += _node_text_bytes(rule)
        if text_bytes > MAX_TRANSCODE_GUARD_TEXT_BYTES:
            raise ValueError("La configurazione Transcode Guard contiene troppo testo.")

        children = rule.get("children")
        is_group = str(rule.get("type") or "rule").strip().lower() == "group"
        if not is_group or not isinstance(children, list) or not children:
            leaf_count += 1
            if leaf_count > MAX_TRANSCODE_GUARD_RULES:
                raise ValueError("La configurazione Transcode Guard contiene troppe regole finali.")
            continue
        if len(children) > MAX_TRANSCODE_GUARD_GROUP_CHILDREN:
            raise ValueError("Un gruppo Transcode Guard contiene troppi elementi.")
        stack.extend(
            (child, depth + 1)
            for child in reversed(children)
            if isinstance(child, dict)
        )


def validate_transcode_guard_persisted_size(settings: dict[str, Any]) -> None:
    """Bound the canonical JSON written to storage without truncating settings."""

    try:
        encoded = json.dumps(
            settings,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("La configurazione Transcode Guard non è serializzabile.") from exc
    if len(encoded) > MAX_TRANSCODE_GUARD_PERSISTED_BYTES:
        raise ValueError("La configurazione Transcode Guard supera la dimensione consentita.")
