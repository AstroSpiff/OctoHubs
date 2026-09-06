#!/usr/bin/env python3
"""Minimal external API client for OctoHubs Bearer-token smoke tests."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from urllib.parse import urljoin, urlsplit


DEFAULT_BASE_URL = "http://127.0.0.1:5050"
DEFAULT_DENIED_BODY = {"action": "bot.save", "data": {"id": "scope-check"}}
SAFE_CONTROL_READ_PATHS = (
    "/api/v1/system/status",
    "/api/v1/operations",
    "/api/v1/realtime/changes",
    "/api/v1/emby/streams",
    "/api/v1/emby/transcode-guard/stats",
    "/api/v1/emby/users/list",
    "/api/v1/emby/collections",
    "/api/v1/emby/probe/libraries",
)


@dataclass
class ApiResponse:
    status: int
    payload: Any


@dataclass
class ControlPlaneVerification:
    """Safe external-client verification derived from the token's own contract."""

    reads: list[tuple[str, int]]
    operations: list[tuple[str, str, str]]


class OctoHubsApiError(RuntimeError):
    """Raised when OctoHubs returns an unexpected API response."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _url_origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("redirect URL has no supported origin")
    return scheme, hostname, parsed.port or (443 if scheme == "https" else 80)


class _SameOriginRedirectHandler(request.HTTPRedirectHandler):
    """Allow redirects only while the Bearer credential stays on one origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved = urljoin(req.full_url, newurl)
        if _url_origin(req.full_url) != _url_origin(resolved):
            raise OctoHubsApiError(
                "Refused cross-origin redirect while sending an API Bearer token",
                status=code,
            )
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def _open_url(http_request: request.Request, timeout: float):
    opener = request.build_opener(_SameOriginRedirectHandler())
    return opener.open(http_request, timeout=timeout)


class OctoHubsApiClient:
    """Small standard-library client for external OctoHubs API checks."""

    def __init__(self, base_url: str, token: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        if not self.base_url:
            raise ValueError("base_url is required")
        if not self.token:
            raise ValueError("token is required")

    def request(self, method: str, path: str, body: Any = None) -> ApiResponse:
        target = f"{self.base_url}/{path.lstrip('/')}"
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "octohubs-api-client/1.0",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        http_request = request.Request(target, data=data, headers=headers, method=method.upper())
        try:
            with _open_url(http_request, timeout=self.timeout) as response:
                return ApiResponse(response.status, _decode_body(response.read()))
        except error.HTTPError as exc:
            payload = _decode_body(exc.read())
            raise OctoHubsApiError(
                f"OctoHubs returned HTTP {exc.code} for {method.upper()} {path}",
                status=exc.code,
                payload=payload,
            ) from exc
        except error.URLError as exc:
            raise OctoHubsApiError(f"Cannot reach OctoHubs at {target}: {exc.reason}") from exc

    def get_status(self) -> ApiResponse:
        return self.request("GET", "/api/v1/system/status")

    def get_servers(self) -> ApiResponse:
        return self.request("GET", "/api/v1/emby/servers")

    def get_catalog(self) -> ApiResponse:
        """Read the public API contract limited to this token's scopes."""
        return self.request("GET", "/api/v1/external/openapi.json")

    def call_documented(self, method: str, path: str, body: Any = None) -> ApiResponse:
        """Call only an operation exposed by this token's own OpenAPI catalog."""
        normalized_method = method.strip().lower()
        normalized_path = "/" + path.lstrip("/")
        catalog = self.get_catalog().payload
        paths = catalog.get("paths", {}) if isinstance(catalog, dict) else {}
        operation = paths.get(normalized_path, {}).get(normalized_method)
        if not isinstance(operation, dict):
            raise OctoHubsApiError(
                f"{method.upper()} {normalized_path} is not exposed by this token's API contract"
            )
        return self.request(normalized_method, normalized_path, body)

    def verify_control_plane(self) -> ControlPlaneVerification:
        """Verify safe reads and discover callable operations without invoking them.

        The result comes from the scope-filtered catalog. Only GET endpoints
        are called, so the check cannot start, stop, sync or modify data.
        Use :meth:`call_documented` to opt into a real action.
        """
        catalog = self.get_catalog().payload
        paths = catalog.get("paths", {}) if isinstance(catalog, dict) else {}
        if not isinstance(paths, dict):
            raise OctoHubsApiError("External API catalog has no paths object")

        reads = []
        for path in SAFE_CONTROL_READ_PATHS:
            path_item = paths.get(path)
            operation = path_item.get("get") if isinstance(path_item, dict) else None
            if isinstance(operation, dict):
                reads.append((path, self.request("GET", path).status))

        if not any(path == "/api/v1/system/status" for path, _status in reads):
            raise OctoHubsApiError("The token catalog does not expose GET /api/v1/system/status")

        operations = []
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue
                if operation.get("x-octohubs-operation-kind") == "operation":
                    operations.append((
                        method.upper(),
                        path,
                        str(operation.get("x-octohubs-required-scope") or ""),
                    ))
        return ControlPlaneVerification(reads=reads, operations=operations)

    def expect_denied(self, method: str, path: str, body: Any = None) -> ApiResponse:
        try:
            response = self.request(method, path, body)
        except OctoHubsApiError as exc:
            if exc.status == 403:
                return ApiResponse(exc.status, exc.payload)
            raise
        raise OctoHubsApiError(
            f"Expected HTTP 403 for {method.upper()} {path}, got HTTP {response.status}",
            status=response.status,
            payload=response.payload,
        )


def _decode_body(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def _load_json_argument(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid JSON body: {exc}") from exc


def _print_response(label: str, response: ApiResponse) -> None:
    print(f"{label}: HTTP {response.status}")
    if response.payload is not None:
        print(json.dumps(response.payload, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OctoHubs external API smoke client")
    parser.add_argument("--base-url", default=os.environ.get("OCTOHUBS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token-file", help="Read the API token from a protected file")
    parser.add_argument("--timeout", type=float, default=15.0)

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="GET /api/v1/system/status")
    subparsers.add_parser("servers", help="GET /api/v1/emby/servers")
    subparsers.add_parser("catalog", help="GET /api/v1/external/openapi.json filtered to token scopes")

    call = subparsers.add_parser(
        "call",
        help="Call an operation only after verifying it is exposed by this token's OpenAPI contract",
    )
    call.add_argument("method", help="HTTP method, for example GET or POST")
    call.add_argument("path", help="Canonical /api/v1/... path")
    call.add_argument("--body", type=_load_json_argument, default=None, help="Optional JSON request body")

    denied = subparsers.add_parser("expect-denied", help="Expect a 403 for a request outside token scope")
    denied.add_argument("--method", default="POST")
    denied.add_argument("--path", default="/api/v1/telegram/action")
    denied.add_argument("--body", type=_load_json_argument, default=None)

    smoke = subparsers.add_parser("smoke", help="Run safe read + expected-denial checks")
    smoke.add_argument("--include-servers", action="store_true", help="Also call GET /api/v1/emby/servers")
    smoke.add_argument("--skip-denied", action="store_true", help="Skip the expected 403 check")
    subparsers.add_parser(
        "verify",
        help="Verify safe reads and discover authorized operations without invoking them",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    token = os.environ.get("OCTOHUBS_API_TOKEN", "")
    if getattr(args, "token_file", None):
        with open(args.token_file, encoding="utf-8") as token_handle:
            token = token_handle.read().strip()
        if not token:
            raise ValueError("token file is empty")
    client = OctoHubsApiClient(args.base_url, token, args.timeout)

    if args.command == "status":
        _print_response("status", client.get_status())
        return 0
    if args.command == "servers":
        _print_response("servers", client.get_servers())
        return 0
    if args.command == "catalog":
        _print_response("catalog", client.get_catalog())
        return 0
    if args.command == "call":
        _print_response("call", client.call_documented(args.method, args.path, args.body))
        return 0
    if args.command == "expect-denied":
        body = DEFAULT_DENIED_BODY if args.body is None else args.body
        _print_response("denied", client.expect_denied(args.method, args.path, body))
        return 0
    if args.command == "smoke":
        _print_response("status", client.get_status())
        if args.include_servers:
            _print_response("servers", client.get_servers())
        if not args.skip_denied:
            _print_response(
                "denied",
                client.expect_denied("POST", "/api/v1/telegram/action", DEFAULT_DENIED_BODY),
            )
        return 0
    if args.command == "verify":
        result = client.verify_control_plane()
        for path, status in result.reads:
            print(f"read: {path} -> HTTP {status}")
        if result.operations:
            print("authorized operations (not invoked):")
            for method, path, scope in result.operations:
                print(f"  {method} {path} [{scope}]")
        else:
            print("authorized operations: none")
        return 0
    raise OctoHubsApiError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OctoHubsApiError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        payload = getattr(exc, "payload", None)
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
