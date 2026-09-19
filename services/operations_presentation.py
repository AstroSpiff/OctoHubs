"""Read-time presentation helpers for the shared operations center."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def present_operation_server_names(
    operations: Iterable[Mapping[str, Any]],
    server_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Replace internal Probe server IDs with configured display names."""

    presented: list[dict[str, Any]] = []
    for source in operations:
        operation = dict(source)
        details = operation.get("details")
        if not str(operation.get("kind") or "").startswith("probe_") or not isinstance(
            details,
            Mapping,
        ):
            presented.append(operation)
            continue
        raw_ids = details.get("server_ids")
        if not isinstance(raw_ids, list):
            presented.append(operation)
            continue
        labels = [
            str(server_names.get(str(server_id)) or server_id)
            for server_id in raw_ids
            if server_id
        ]
        if labels:
            operation["summary"] = (
                labels[0]
                if len(labels) == 1
                else f"{len(labels)} server · {', '.join(labels)}"
            )
        presented.append(operation)
    return presented
