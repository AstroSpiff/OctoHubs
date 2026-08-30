"""Regression coverage for the public external OpenAPI audit."""

from __future__ import annotations

from web.external_api_audit import audit_external_openapi
from web.external_api_catalog import build_external_openapi


def _source_schema():
    return {
        "openapi": "3.1.0",
        "info": {"title": "OctoHubs", "version": "test"},
        "paths": {
            "/api/system/status": {
                "get": {
                    "summary": "Read system status",
                    "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/api/telegram/action": {
                "post": {
                    "summary": "Run Telegram action",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "OK", "content": {"application/json": {}}}},
                }
            },
        },
    }


def test_external_audit_accepts_a_structurally_complete_contract_and_reports_typing_work():
    schema = build_external_openapi(_source_schema(), ["read:status", "write:configuration"])

    audit = audit_external_openapi(schema)

    assert audit.operation_count == 2
    assert audit.is_structurally_valid
    assert not audit.is_publication_ready
    assert audit.structural_issues == ()
    assert [(item.method, item.path) for item in audit.generic_response_operations] == [
        ("POST", "/api/v1/telegram/action")
    ]
    assert audit.undeclared_mutation_bodies == ()


def test_external_audit_rejects_unversioned_broad_or_unauthenticated_operations():
    audit = audit_external_openapi({
        "paths": {
            "/api/unsafe": {
                "post": {
                    "responses": {"200": {"description": "OK"}},
                    "x-octohubs-required-scope": "admin:all",
                }
            }
        }
    })

    assert {issue.code for issue in audit.structural_issues} == {
        "unversioned-path",
        "missing-summary",
        "broad-scope",
        "missing-bearer-auth",
        "csrf-contract",
        "missing-auth-responses",
    }
    assert [(item.method, item.path) for item in audit.undeclared_mutation_bodies] == [
        ("POST", "/api/unsafe")
    ]


def test_external_audit_accepts_an_explicitly_bodyless_command():
    audit = audit_external_openapi({
        "paths": {
            "/api/v1/operations/clear-completed": {
                "post": {
                    "summary": "Clear completed operations",
                    "security": [{"BearerAuth": []}],
                    "x-octohubs-required-scope": "run:operations",
                    "x-octohubs-csrf": "not-required-with-bearer-token",
                    "x-octohubs-request-contract": "none-intentional",
                    "responses": {
                        "200": {"description": "OK", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "401": {"description": "Unauthorized"},
                        "403": {"description": "Forbidden"},
                    },
                }
            }
        }
    })

    assert audit.is_structurally_valid
    assert audit.is_publication_ready
    assert audit.undeclared_mutation_bodies == ()


def test_current_application_external_contract_has_no_structural_violations(monkeypatch):
    import runtime.app_setup as app_setup
    from services import interface_order_migration

    # This is an OpenAPI-only audit. Database/bootstrap behavior is covered by
    # dedicated tests and must not make a local PostgreSQL service a prerequisite.
    monkeypatch.setenv("PASSWORD_SECRET", "test-password-secret-that-is-long-enough")
    monkeypatch.setattr(app_setup, "init_auth", lambda **_kwargs: True)
    monkeypatch.setattr(app_setup, "initialize_runtime_services", lambda: None)
    monkeypatch.setattr(
        interface_order_migration,
        "migrate_legacy_interface_orders",
        lambda: {"completed": False, "already_completed": True, "profiles": 0},
    )

    app = app_setup.create_app()
    schema = build_external_openapi(app.openapi(), ["admin:all"])
    audit = audit_external_openapi(schema)

    assert audit.operation_count >= 100
    assert audit.is_structurally_valid, audit.structural_issues
    assert audit.is_publication_ready
    assert audit.generic_response_operations == ()
    assert audit.undeclared_mutation_bodies == ()
