"""Bounded materialization for JSON/text returned by external HTTP services."""

from __future__ import annotations

import json
from typing import Any

import requests


DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_JSON_DEPTH = 64
DEFAULT_MAX_JSON_NODES = 100_000
DEFAULT_MAX_STRING_LENGTH = 1 * 1024 * 1024


class UpstreamResponseError(requests.RequestException):
    """An upstream response violated the local transport or shape budget."""


def close_response_safely(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def require_success_and_close(response: Any) -> None:
    """Check an HTTP status for operations that do not consume a body."""
    try:
        response.raise_for_status()
    finally:
        close_response_safely(response)


def _declared_length(response: Any) -> int | None:
    headers = getattr(response, "headers", {})
    raw_value = headers.get("Content-Length") if hasattr(headers, "get") else None
    if raw_value is None:
        return None
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        raise UpstreamResponseError("Content-Length upstream non valido") from None


def _validate_content_type(response: Any) -> None:
    headers = getattr(response, "headers", {})
    value = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if value and value != "application/json" and not value.endswith("+json"):
        raise UpstreamResponseError("Content-Type upstream non JSON")


def _raise_for_status(response: Any, *, required: bool) -> None:
    if not required:
        return
    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        raise_for_status()


def _read_streamed_bytes(response: Any, *, limit: int) -> bytes | None:
    iter_content = getattr(response, "iter_content", None)
    if not callable(iter_content):
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise UpstreamResponseError("Risposta upstream troppo grande")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_fallback_bytes(response: Any) -> bytes:
    """Materialize the small response doubles used by unit tests."""
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return str(getattr(response, "text", "") or "").encode("utf-8")


def _ensure_size(raw: bytes, *, limit: int) -> bytes:
    if len(raw) > limit:
        raise UpstreamResponseError("Risposta upstream troppo grande")
    return raw


def read_bounded_response_bytes(
    response: Any,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    require_success: bool = True,
) -> bytes:
    """Read a response incrementally and always close it."""
    limit = max(1, int(max_bytes))
    try:
        _raise_for_status(response, required=require_success)
        declared = _declared_length(response)
        if declared is not None and declared > limit:
            raise UpstreamResponseError("Risposta upstream troppo grande")
        streamed = _read_streamed_bytes(response, limit=limit)
        if streamed is not None:
            return streamed
        return _ensure_size(_read_fallback_bytes(response), limit=limit)
    finally:
        close_response_safely(response)


def _validate_json_shape(
    payload: Any,
    *,
    max_depth: int = DEFAULT_MAX_JSON_DEPTH,
    max_nodes: int = DEFAULT_MAX_JSON_NODES,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
) -> None:
    stack: list[tuple[Any, int]] = [(payload, 0)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > max_nodes:
            raise UpstreamResponseError("Risposta JSON upstream troppo complessa")
        if depth > max_depth:
            raise UpstreamResponseError("Risposta JSON upstream troppo profonda")
        if isinstance(value, str):
            if len(value) > max_string_length:
                raise UpstreamResponseError("Campo JSON upstream troppo grande")
        elif isinstance(value, dict):
            if len(value) > max_nodes:
                raise UpstreamResponseError("Oggetto JSON upstream troppo grande")
            stack.extend((key, depth + 1) for key in value)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            if len(value) > max_nodes:
                raise UpstreamResponseError("Array JSON upstream troppo grande")
            stack.extend((item, depth + 1) for item in value)


def read_bounded_json_response(
    response: Any,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    allow_empty: bool = False,
    require_success: bool = True,
) -> Any:
    """Decode a bounded JSON response and validate its structural budget."""
    json_reader = getattr(response, "json", None)
    if not isinstance(response, requests.Response) and callable(json_reader):
        return _read_json_from_test_double(
            response,
            json_reader,
            max_bytes=max_bytes,
            require_success=require_success,
        )

    try:
        _raise_for_status(response, required=require_success)
        _validate_content_type(response)
    except Exception:
        close_response_safely(response)
        raise
    raw = read_bounded_response_bytes(
        response,
        max_bytes=max_bytes,
        require_success=False,
    )
    return _decode_json_bytes(raw, allow_empty=allow_empty)


def _decode_json_bytes(raw: bytes, *, allow_empty: bool) -> Any:
    if not raw and allow_empty:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamResponseError("Risposta JSON upstream non valida") from exc
    _validate_json_shape(payload)
    return payload


def _read_json_from_test_double(
    response: Any,
    json_reader: Any,
    *,
    max_bytes: int,
    require_success: bool,
) -> Any:
    try:
        _raise_for_status(response, required=require_success)
        try:
            payload = json_reader()
            encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        except requests.RequestException:
            raise
        except (RecursionError, TypeError, ValueError) as exc:
            raise UpstreamResponseError("Risposta JSON upstream non valida") from exc
        _ensure_size(encoded, limit=max(1, int(max_bytes)))
        _validate_json_shape(payload)
        return payload
    finally:
        close_response_safely(response)


def read_bounded_text_response(
    response: Any,
    *,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    require_success: bool = True,
) -> str:
    raw = read_bounded_response_bytes(
        response,
        max_bytes=max_bytes,
        require_success=require_success,
    )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UpstreamResponseError("Risposta testuale upstream non valida") from exc
