"""Bounded WebSocket I/O shared without importing feature route packages."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.websockets import WebSocketDisconnect


WEBSOCKET_ACCEPT_TIMEOUT_SECONDS = 5.0
WEBSOCKET_SEND_TIMEOUT_SECONDS = 5.0
WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 1.0


async def accept_bounded(
    websocket: Any,
    *,
    timeout: float = WEBSOCKET_ACCEPT_TIMEOUT_SECONDS,
) -> None:
    """Accept a connection without letting an incomplete handshake pin ownership."""
    try:
        await asyncio.wait_for(websocket.accept(), timeout=timeout)
    except WebSocketDisconnect:
        raise
    except Exception as exc:
        raise WebSocketDisconnect(code=1011) from exc


async def send_json_bounded(
    websocket: Any,
    payload: Any,
    *,
    timeout: float = WEBSOCKET_SEND_TIMEOUT_SECONDS,
) -> None:
    """Send one frame without allowing a stalled client to pin its handler."""
    try:
        await asyncio.wait_for(websocket.send_json(payload), timeout=timeout)
    except WebSocketDisconnect:
        raise
    except Exception as exc:
        raise WebSocketDisconnect(code=1011) from exc


async def close_bounded(
    websocket: Any,
    *,
    code: int = 1000,
    timeout: float = WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
) -> bool:
    """Attempt the close handshake within a fixed deadline."""
    try:
        await asyncio.wait_for(websocket.close(code=code), timeout=timeout)
    except Exception:
        return False
    return True
