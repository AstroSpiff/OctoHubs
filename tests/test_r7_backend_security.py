"""Focused regressions for the seventh backend security remediation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.mark.anyio
async def test_probe_debug_limit_is_bounded_before_snapshot(monkeypatch):
    from emby_probe import routes

    captured = []
    monkeypatch.setattr(routes, "_require_auth_dep", lambda _request: 7)
    monkeypatch.setattr(
        routes,
        "_probe_debug_recent_items_snapshot",
        lambda server_id, limit: captured.append((server_id, limit))
        or ({"success": True, "items": []}, 200),
    )
    request = SimpleNamespace(
        query_params={"server_id": "green", "limit": "1000000000000"}
    )

    response = await routes.probe_debug_recent_items(request)

    assert response.status_code == 200
    assert captured == [("green", 200)]


def test_probe_debug_snapshot_redacts_filesystem_paths(monkeypatch):
    from emby_probe import snapshots

    monkeypatch.setattr(
        snapshots,
        "load_config",
        lambda: ({"EMBY": {"SERVERS": [{"id": "green", "enabled": True}]}}, True),
    )
    monkeypatch.setattr(
        "emby_runtime.api_clients._call_emby_api",
        lambda *_args, **_kwargs: (
            True,
            {
                "Items": [
                    {
                        "Name": "Movie",
                        "Path": "/private/library/secret.strm",
                        "MediaSources": [{"Path": "/private/media/secret.mkv"}],
                    }
                ]
            },
        ),
    )

    payload, status = snapshots._probe_debug_recent_items_snapshot("green", 50)
    serialized = json.dumps(payload)

    assert status == 200
    assert "/private/" not in serialized
    assert payload["items"][0]["path"] == "[REDACTED]"
    assert payload["items"][0]["media_sources"][0]["Path"] == "[REDACTED]"
