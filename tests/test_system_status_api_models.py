"""Contract coverage for the external system-status endpoint."""

from __future__ import annotations

from fastapi import FastAPI

from web.config_routes import router
from web.system_status_api_models import (
    SystemStatusInvalidSectionResponse,
    SystemStatusSnapshotResponse,
)


def test_system_status_route_publishes_the_snapshot_contract():
    app = FastAPI()
    app.include_router(router)

    schema = app.openapi()
    response_schema = schema["paths"]["/api/system/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert {item["$ref"] for item in response_schema["anyOf"]} == {
        "#/components/schemas/SystemStatusSnapshotResponse",
        "#/components/schemas/SystemStatusInvalidSectionResponse",
    }
    assert "SystemStatusSection" in schema["components"]["schemas"]
    assert "SystemStatusItem" in schema["components"]["schemas"]


def test_system_status_models_accept_existing_snapshot_shapes():
    snapshot = SystemStatusSnapshotResponse.model_validate({
        "ok": True,
        "severity": "ok",
        "status_label": "OK",
        "generated_at": "2026-08-29T12:00:00+00:00",
        "summary": {"ok": 1, "warning": 0, "error": 0, "unknown": 0},
        "sections": [{
            "id": "app",
            "title": "Applicazione",
            "severity": "ok",
            "status_code": "ok",
            "status_label": "OK",
            "items": [{
                "id": "octohubs",
                "label": "OctoHubs",
                "severity": "ok",
                "status_code": "ready",
                "status_label": "Pronto",
                "summary": "Configurazione caricata",
                "detail": "",
                "href": "/app/configuration/services",
                "metrics": [{"label": "Config", "value": "/config/config.json"}],
            }],
            "href": "/app/configuration/services",
            "check_label": "",
            "refresh_interval_seconds": 60,
            "updated_at": "2026-08-29T12:00:00+00:00",
            "checked_at": "",
        }],
    })
    invalid = SystemStatusInvalidSectionResponse.model_validate({
        "ok": False,
        "error": "Sezione stato non valida.",
        "generated_at": "2026-08-29T12:00:00+00:00",
    })

    assert snapshot.sections[0].items[0].metrics[0].label == "Config"
    assert invalid.ok is False
