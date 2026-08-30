"""OpenAPI contract coverage for Emby Live and Transcode Guard."""

from __future__ import annotations

from fastapi import FastAPI

from emby_runtime.routes import router as runtime_router
from emby_runtime.runtime_api_models import EmbyStatusSnapshotResponse
from emby_runtime.transcode_guard_api_models import (
    TranscodeGuardStatsResponse,
    TranscodeGuardStreamDetailResponse,
)
from emby_runtime.transcode_guard_routes import router as transcode_router
from realtime.routes import router as realtime_router


def test_runtime_routes_publish_live_snapshot_models():
    app = FastAPI()
    app.include_router(runtime_router)
    schema = app.openapi()

    assert schema["paths"]["/api/emby/streams"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EmbyStreamsSnapshotResponse"
    assert schema["paths"]["/api/emby/probe/libraries"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EmbyProbeLibrariesResponse"
    assert schema["paths"]["/api/emby/server-status/{server_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EmbyServerStatusResponse"


def test_emby_status_fallback_publishes_a_typed_snapshot_contract():
    app = FastAPI()
    app.include_router(realtime_router)
    schema = app.openapi()

    response = schema["paths"]["/api/emby/status"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/EmbyStatusSnapshotResponse"

    payload = EmbyStatusSnapshotResponse.model_validate({
        "success": True,
        "servers": {
            "green": {
                "server": {
                    "id": "green",
                    "name": "Green",
                    "enabled": True,
                    "icon": "fa-server",
                    "icon_color": "#22c55e",
                    "icon_style": "solid",
                },
                "status": {"ok": True},
                "running_tasks": [],
                "streams": [],
                "probe_status": None,
            }
        },
    })
    assert payload.servers["green"].server.name == "Green"


def test_transcode_guard_routes_publish_stats_and_detail_models():
    app = FastAPI()
    app.include_router(transcode_router)
    schema = app.openapi()

    stats = schema["paths"]["/api/emby/transcode-guard/stats"]["get"]["responses"]["200"]
    detail = schema["paths"]["/api/emby/transcode-guard/streams/{stream_id}"]["get"]["responses"]["200"]
    assert stats["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TranscodeGuardStatsResponse"
    assert detail["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/TranscodeGuardStreamDetailResponse"


def test_transcode_guard_stat_models_accept_existing_snapshot_shapes():
    stats = TranscodeGuardStatsResponse.model_validate({
        "ok": True,
        "filters": {"period": "7d", "server_id": "", "user": "", "client": "", "issues_only": False, "sort": "issues_desc", "limit": 160},
        "summary": {"users": 1, "streams": 1, "correct": 1, "issue_streams": 0, "technical_issues": 0, "warnings": 0, "stops": 0, "resolved": 0, "exits": 1, "resolution_changes": 0, "relapses": 0, "active": 0, "problem_rate": 0},
        "users": [],
        "history": [{"id": "stream-1", "at": "2026-08-29T12:00:00+00:00", "started_at": "", "ended_at": "", "user": "Roy", "title": "Film", "server_id": "green", "server_name": "Green", "client": "Web", "device": "Mac", "quality": "Diretto", "outcome": "exit", "tags": [], "violations_committed": [], "actions": ["exit"], "action_records": [{"action": "exit", "source": "plugin", "at": "2026-08-29T12:00:00+00:00"}], "duration_seconds": 45, "playback_percent": 30, "rule_name": "", "reason": ""}],
        "facets": {"servers": [], "users": [], "clients": []},
    })
    detail = TranscodeGuardStreamDetailResponse.model_validate({"ok": True, "stream": stats.history[0].model_dump()})

    assert stats.history[0].outcome == "exit"
    assert detail.stream.action_records[0].source == "plugin"
