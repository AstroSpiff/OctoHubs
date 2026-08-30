"""Public API version routing without duplicating OctoHubs handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any


API_V1_PREFIX = "/api/v1"
_EXTERNAL_API_PREFIXES = (
    "/api/system/status",
    "/api/emby/",
    "/api/research/",
    "/api/operations",
    "/api/workflow/",
    "/api/test-connections",
    "/api/trakt/",
    "/api/configuration/",
    "/api/telegram/",
    "/api/event-bridge/",
    "/api/realtime/",
    "/api/account/",
    "/api/admin/",
    "/api/external/openapi.json",
)
_EXTERNAL_API_EXCLUDED_PATHS = frozenset(
    {
        # Inbound plugin hooks and browser streaming use another auth/transport.
        "/api/emby/event-bridge/events",
        "/api/emby/events-stream",
        "/api/emby/status-stream",
        "/api/emby/transcode-guard/player-event",
        "/api/workflow/events",
    }
)


def is_external_api_path(path: str) -> bool:
    """Return whether an unversioned route belongs to the public control API."""
    normalized_path = str(path or "")
    return (
        normalized_path not in _EXTERNAL_API_EXCLUDED_PATHS
        and normalized_path.startswith(_EXTERNAL_API_PREFIXES)
    )


def versioned_external_api_path(path: str) -> str | None:
    """Return the public v1 path for one eligible internal API route."""
    normalized_path = str(path or "")
    if not is_external_api_path(normalized_path):
        return None
    return f"{API_V1_PREFIX}{normalized_path.removeprefix('/api')}"


def canonical_v1_external_api_path(path: str) -> str | None:
    """Resolve a v1 request to its sole existing handler, if it is public."""
    normalized_path = str(path or "")
    if not normalized_path.startswith(f"{API_V1_PREFIX}/"):
        return None
    canonical_path = "/api" + normalized_path[len(API_V1_PREFIX) :]
    return canonical_path if is_external_api_path(canonical_path) else None


class ApiV1GatewayMiddleware:
    """Translate only public ``/api/v1`` requests before route matching.

    The rewrite intentionally happens at ASGI scope level: FastAPI reaches the
    existing route and service, so v1 never owns a second handler or business
    implementation. Private browser/session APIs are deliberately left as 404.
    """

    def __init__(self, app: Callable[..., Awaitable[Any]]):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        requested_path = str(scope.get("path") or "")
        canonical_path = canonical_v1_external_api_path(requested_path)
        if canonical_path is None:
            successor_path = versioned_external_api_path(requested_path)
            if successor_path is None:
                await self.app(scope, receive, send)
                return

            await self._send_retired_legacy_api_response(send, successor_path)
            return

        rewritten_scope = dict(scope)
        rewritten_scope["path"] = canonical_path
        rewritten_scope["raw_path"] = canonical_path.encode("utf-8")
        rewritten_scope["octohubs_api_version"] = "v1"
        rewritten_scope["octohubs_external_path"] = requested_path
        await self.app(rewritten_scope, receive, send)

    @staticmethod
    async def _send_retired_legacy_api_response(
        send: Callable[..., Awaitable[Any]], successor_path: str
    ) -> None:
        """Reject retired public API paths while retaining one internal handler."""

        body = json.dumps(
            {
                "detail": "Percorso API storico ritirato. Usa /api/v1/.",
                "successor": successor_path,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 410,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"link", f'<{successor_path}>; rel="successor-version"'.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
