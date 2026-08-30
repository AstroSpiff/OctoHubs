"""Structural audit for the public OctoHubs v1 OpenAPI contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_HTTP_OPERATIONS = frozenset({"get", "put", "post", "delete", "patch", "head", "options"})
_MUTATION_OPERATIONS = frozenset({"put", "post", "patch"})


@dataclass(frozen=True)
class ExternalApiContractIssue:
    """One deterministic finding from the generated external contract."""

    code: str
    method: str
    path: str
    detail: str


@dataclass(frozen=True)
class ExternalApiContractAudit:
    """Audit result, split between structural and publication-quality checks."""

    operation_count: int
    structural_issues: tuple[ExternalApiContractIssue, ...]
    generic_response_operations: tuple[ExternalApiContractIssue, ...]
    undeclared_mutation_bodies: tuple[ExternalApiContractIssue, ...]

    @property
    def is_structurally_valid(self) -> bool:
        return not self.structural_issues

    @property
    def is_publication_ready(self) -> bool:
        """Return whether the public v1 contract has no typing ambiguity."""
        return (
            self.is_structurally_valid
            and not self.generic_response_operations
            and not self.undeclared_mutation_bodies
        )


def _operation_entries(schema: Mapping[str, Any]):
    for path, path_item in sorted(dict(schema.get("paths") or {}).items()):
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in sorted(path_item.items()):
            if method.lower() not in _HTTP_OPERATIONS or not isinstance(operation, Mapping):
                continue
            yield str(path), str(method).upper(), operation


def _has_success_response(operation: Mapping[str, Any]) -> bool:
    return any(str(status).startswith("2") for status in dict(operation.get("responses") or {}))


def audit_external_openapi(schema: Mapping[str, Any]) -> ExternalApiContractAudit:
    """Audit the generated public schema without requiring a running server.

    Structural issues make a route unsafe to publish. Generic JSON responses
    and undeclared mutation inputs are also surfaced separately so the strict
    quality gate can reject them without confusing explicit bodyless commands.
    """
    structural: list[ExternalApiContractIssue] = []
    generic: list[ExternalApiContractIssue] = []
    body_gaps: list[ExternalApiContractIssue] = []
    operations = list(_operation_entries(schema))

    for path, method, operation in operations:
        def issue(code: str, detail: str) -> ExternalApiContractIssue:
            return ExternalApiContractIssue(code, method, path, detail)

        if not path.startswith("/api/v1/"):
            structural.append(issue("unversioned-path", "Il contratto esterno deve esporre solo /api/v1/."))
        if not str(operation.get("summary") or "").strip():
            structural.append(issue("missing-summary", "Manca un summary OpenAPI leggibile dal client."))
        scope = str(operation.get("x-octohubs-required-scope") or "")
        if not scope:
            structural.append(issue("missing-scope", "Manca lo scope minimo richiesto."))
        elif scope == "admin:all":
            structural.append(issue("broad-scope", "admin:all non e ammesso nel contratto pubblico v1."))
        if operation.get("security") != [{"BearerAuth": []}]:
            structural.append(issue("missing-bearer-auth", "Manca la sicurezza Bearer del contratto esterno."))
        if operation.get("x-octohubs-csrf") != "not-required-with-bearer-token":
            structural.append(issue("csrf-contract", "Manca la dichiarazione CSRF per token Bearer."))
        responses = dict(operation.get("responses") or {})
        if "401" not in responses or "403" not in responses:
            structural.append(issue("missing-auth-responses", "Mancano le risposte standard 401 e/o 403."))
        if not _has_success_response(operation):
            structural.append(issue("missing-success-response", "Manca almeno una risposta 2xx."))

        if operation.get("x-octohubs-response-contract") == "generic":
            generic.append(issue("generic-response", "La risposta JSON e intenzionalmente aperta, non ancora tipizzata campo per campo."))
        request_contract = operation.get("x-octohubs-request-contract")
        has_declared_input = bool(operation.get("requestBody") or operation.get("parameters"))
        if method.lower() in _MUTATION_OPERATIONS and request_contract not in {"none-intentional", "declared", "parameters-only"} and (
            request_contract == "none-declared" or (request_contract is None and not has_declared_input)
        ):
            body_gaps.append(issue("undeclared-mutation-body", "La mutazione non dichiara un body o parametri OpenAPI."))

    return ExternalApiContractAudit(
        operation_count=len(operations),
        structural_issues=tuple(structural),
        generic_response_operations=tuple(generic),
        undeclared_mutation_bodies=tuple(body_gaps),
    )
