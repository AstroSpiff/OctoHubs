"""One-shot WebSocket lifecycle for bounded streaming searches."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from starlette.websockets import WebSocketDisconnect

from search.state import SearchSessionError, claim_search_session, finish_search_session
from search.stream_limits import (
    SEARCH_STREAM_TIMEOUT_SECONDS,
    SearchClientDisconnected,
    SearchWorkloadLimitError,
)
from search.stream_protocol import SearchStreamProtocolError, receive_search_start


async def _send_error(websocket: Any, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message})
    except Exception:
        pass


async def handle_search_websocket(
    websocket: Any,
    session_id: str,
    authorize: Callable[[Any], Awaitable[Any | None]],
) -> None:
    auth_subject = await authorize(websocket)
    if auth_subject is None:
        return

    try:
        owner_id = int(auth_subject)
        claim_search_session(session_id, owner_id)
    except (TypeError, ValueError, SearchSessionError):
        await websocket.close(code=1008)
        return

    accepted = False
    try:
        await websocket.accept()
        accepted = True
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        payload = await receive_search_start(websocket)

        from core.config_manager import load_config
        from search.streaming import search_streaming_parallel

        config, is_valid = load_config()
        if not is_valid or not config:
            await _send_error(websocket, "Configurazione non valida")
            return

        try:
            stats = await asyncio.wait_for(
                search_streaming_parallel(
                    query_variants=payload.query_variants,
                    search_types=payload.search_types,
                    selected_indexers=set(payload.indexers),
                    config=config,
                    websocket=websocket,
                    session_id=session_id,
                    use_jellyseerr_logic=payload.use_jellyseerr_logic,
                    use_custom_rules=payload.use_custom_rules,
                    tmdb_id=payload.tmdb_id,
                    custom_rules=payload.custom_rules,
                    seasons=payload.seasons,
                ),
                timeout=SEARCH_STREAM_TIMEOUT_SECONDS,
            )
            print(f"[WebSocket /ws/search/{session_id}] Ricerca completata: {stats}")
        except SearchWorkloadLimitError as exc:
            await _send_error(websocket, str(exc))
        except SearchClientDisconnected:
            return
        except TimeoutError:
            await _send_error(websocket, "Tempo massimo della ricerca superato")
    except SearchStreamProtocolError as exc:
        await _send_error(websocket, str(exc))
    except WebSocketDisconnect:
        print(f"[WebSocket /ws/search/{session_id}] Client disconnected")
    except Exception as exc:
        print(f"[WebSocket /ws/search/{session_id}] Error: {exc}")
    finally:
        finish_search_session(session_id, owner_id)
        if accepted:
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
