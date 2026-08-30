#!/usr/bin/env python3
"""Print the structural and typing status of the OctoHubs external API."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from asgi import app
from web.external_api_audit import audit_external_openapi
from web.external_api_catalog import build_external_openapi


def _print_findings(label: str, findings, *, verbose: bool) -> None:
    print(f"{label}: {len(findings)}")
    if verbose:
        for finding in findings:
            print(f"  {finding.method} {finding.path} [{finding.code}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the generated OctoHubs external OpenAPI v1 contract")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero for structural violations, generic JSON responses, or undeclared mutation input.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every endpoint that still needs response or request typing.",
    )
    args = parser.parse_args()

    schema = build_external_openapi(app.openapi(), ["admin:all"])
    audit = audit_external_openapi(schema)
    print(f"Public v1 operations: {audit.operation_count}")
    _print_findings("Structural violations", audit.structural_issues, verbose=args.verbose)
    _print_findings("Generic JSON responses to type", audit.generic_response_operations, verbose=args.verbose)
    _print_findings(
        "Mutations without declared body or parameters",
        audit.undeclared_mutation_bodies,
        verbose=args.verbose,
    )
    return 1 if args.strict and not audit.is_publication_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
