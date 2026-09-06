"""Unauthenticated process and dependency health probes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from runtime import health as runtime_health


router = APIRouter(include_in_schema=False)
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}


@router.get("/health/live", response_class=PlainTextResponse)
def liveness_probe() -> PlainTextResponse:
    """Report that the ASGI process can serve requests, without checking dependencies."""
    return PlainTextResponse("ok\n", headers=_NO_STORE_HEADERS)


def _readiness_response() -> PlainTextResponse:
    if runtime_health.runtime_ready():
        return PlainTextResponse("ok\n", headers=_NO_STORE_HEADERS)
    return PlainTextResponse("not ready\n", status_code=503, headers=_NO_STORE_HEADERS)


@router.get("/health", response_class=PlainTextResponse)
def readiness_probe() -> PlainTextResponse:
    """Compatibility readiness endpoint used by reverse proxies."""
    return _readiness_response()


@router.get("/health/ready", response_class=PlainTextResponse)
def explicit_readiness_probe() -> PlainTextResponse:
    """Report readiness only after startup and a successful database query."""
    return _readiness_response()
