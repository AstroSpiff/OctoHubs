from __future__ import annotations

from pathlib import Path
import re

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL_DOCUMENTS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "README_ita.md",
    *(
        path
        for path in (PROJECT_ROOT / "docs").rglob("*.md")
        if not path.name.startswith("CODE_REVIEW")
    ),
)
INTEGRATION_GUIDES = (
    PROJECT_ROOT / "docs" / "INTEGRATIONS.md",
    PROJECT_ROOT / "docs" / "INTEGRATIONS_ita.md",
)
LEGACY_APPLICATION_PORT = re.compile(
    r"(?:https?://[^/:\s`'\"]+|\b(?:app|localhost|127\.0\.0\.1|HOST))\s*:\s*5000\b",
    re.IGNORECASE,
)
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operational_documentation_does_not_reference_application_port_5000() -> None:
    stale_references: list[str] = []
    for path in OPERATIONAL_DOCUMENTS:
        for line_number, line in enumerate(_read(path).splitlines(), start=1):
            if LEGACY_APPLICATION_PORT.search(line):
                stale_references.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}")

    assert not stale_references, "Legacy application port found: " + ", ".join(
        stale_references
    )


@pytest.mark.parametrize("guide", INTEGRATION_GUIDES, ids=lambda path: path.name)
def test_integration_guides_match_the_event_bridge_http_route(guide: Path) -> None:
    documentation = _read(guide)

    assert "http://HOST:5050/api/emby/event-bridge/events" in documentation
    assert "https://" in documentation
    assert "/api/emby/event-bridge/events" in documentation
    assert "/webhook/emby" not in documentation


def test_documented_event_bridge_endpoint_exists_in_runtime_router() -> None:
    from emby_runtime.transcode_guard_routes import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/api/emby/event-bridge/events" in paths


@pytest.mark.parametrize("guide", INTEGRATION_GUIDES, ids=lambda path: path.name)
def test_integration_guides_document_per_server_event_bridge_pairing(guide: Path) -> None:
    documentation = _read(guide)

    assert "X-OctoHubs-Server-Id" in documentation
    assert "X-Webhook-Secret" in documentation
    assert "WEBHOOK_SECRET`" in documentation  # explicitly identifies the removed legacy setting
    assert "curl --fail" not in documentation
