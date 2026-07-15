"""HTTP response helpers for JSON payloads."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.utils import json_error, json_success


def error_response(message, status_code=400, **extra) -> JSONResponse:
    """Create JSONResponse for error using json_error from utils."""
    data, code = json_error(message, status_code, **extra)
    return JSONResponse(data, status_code=code)


def success_response(message=None, status_code=200, **extra) -> JSONResponse:
    """Create JSONResponse for success using json_success from utils."""
    data, code = json_success(message, status_code, **extra)
    return JSONResponse(data, status_code=code)
