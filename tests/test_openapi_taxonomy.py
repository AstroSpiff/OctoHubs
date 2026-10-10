"""Contract and recurrence gates for the domain-oriented OpenAPI catalog."""

from __future__ import annotations

from collections.abc import Mapping

from runtime.app_setup import create_app
from web.external_api_catalog import build_external_openapi
from web.openapi_taxonomy import OPENAPI_TAGS, UNCLASSIFIED_TAG


_HTTP_OPERATIONS = frozenset({"get", "put", "post", "delete", "patch", "head", "options"})


def _operations(schema: Mapping):
    for path, path_item in (schema.get("paths") or {}).items():
        for method, operation in path_item.items():
            if method.lower() in _HTTP_OPERATIONS:
                yield str(path), method.lower(), operation


def _application_schema(monkeypatch):
    monkeypatch.setenv(
        "PASSWORD_SECRET",
        "test-only-openapi-taxonomy-password-secret-000000000000",
    )
    return create_app().openapi()


def test_complete_schema_groups_every_operation_by_one_known_domain(monkeypatch):
    schema = _application_schema(monkeypatch)
    declared_tags = [str(tag["name"]) for tag in schema["tags"]]
    known_tags = {definition.name for definition in OPENAPI_TAGS}
    operations = list(_operations(schema))

    assert len(operations) >= 200
    assert schema["x-octohubs-taxonomy"] == "domain-subdomain-v1"
    assert UNCLASSIFIED_TAG not in declared_tags
    assert all(len(operation.get("tags") or []) == 1 for _, _, operation in operations)
    assert all(operation["tags"][0] in known_tags for _, _, operation in operations)
    assert {operation["tags"][0] for _, _, operation in operations} == set(declared_tags)
    assert all(str(tag.get("description") or "").strip() for tag in schema["tags"])


def test_taxonomy_assigns_representative_paths_to_their_bounded_context(monkeypatch):
    schema = _application_schema(monkeypatch)
    expected = {
        ("/api/emby/users/list", "get"): "Emby · Utenti",
        ("/api/emby/probe/queue/groups", "get"): "Emby · Media Probe",
        ("/api/emby/latest/refresh", "post"): "Emby · Pubblicazioni",
        ("/api/research/torrents/send", "post"): "Ricerca · Download",
        ("/api/account/tokens", "post"): "Account · Token API",
        ("/api/workflow/start", "post"): "Sistema · Operazioni e workflow",
        ("/api/event-bridge/status", "get"): "Integrazioni · Event Bridge",
    }

    assert {
        key: schema["paths"][key[0]][key[1]]["tags"][0]
        for key in expected
    } == expected


def test_external_catalog_keeps_only_used_domain_definitions(monkeypatch):
    source = _application_schema(monkeypatch)
    external = build_external_openapi(source)
    operations = list(_operations(external))
    used_tags = {operation["tags"][0] for _, _, operation in operations}
    declared_tags = [str(tag["name"]) for tag in external["tags"]]

    assert operations
    assert all(len(operation.get("tags") or []) == 1 for _, _, operation in operations)
    assert set(declared_tags) == used_tags
    assert UNCLASSIFIED_TAG not in declared_tags
    assert "Accesso · Sessione e installazione" not in declared_tags
    assert all(str(tag.get("description") or "").strip() for tag in external["tags"])
