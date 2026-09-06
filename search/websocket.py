"""One-shot WebSocket lifecycle for bounded streaming searches."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Awaitable, Callable

from starlette.websockets import WebSocketDisconnect

from core.async_lifecycle import cancel_and_drain_tasks
from core.log_sanitization import format_exception_for_log
from core.safe_output import safe_print as print
from core.websocket_io import accept_bounded, close_bounded, send_json_bounded
from search.state import SearchSessionError, claim_search_session, finish_search_session
from search.stream_limits import (
    SEARCH_STREAM_TIMEOUT_SECONDS,
    SearchClientDisconnected,
    SearchWorkloadLimitError,
)
from search.stream_protocol import SearchStreamProtocolError, receive_search_start


logger = logging.getLogger(__name__)
SEARCH_AUTHORIZATION_RECHECK_SECONDS = 10.0


async def _send_error(websocket: Any, message: str) -> None:
    try:
        await send_json_bounded(websocket, {"type": "error", "message": message})
    except WebSocketDisconnect:
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
        await close_bounded(websocket, code=1008)
        return

    accepted = False
    search_task: asyncio.Task[Any] | None = None
    auth_task: asyncio.Task[Any] | None = None
    try:
        await accept_bounded(websocket)
        accepted = True
        await send_json_bounded(
            websocket,
            {
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        payload = await receive_search_start(websocket)

        from core.config_manager import load_config
        from search.streaming import search_streaming_parallel

        config, is_valid = await asyncio.to_thread(load_config)
        if not is_valid or not config:
            await _send_error(websocket, "Configurazione non valida")
            return

        try:
            search_task = asyncio.create_task(
                asyncio.wait_for(
                    search_streaming_parallel(
                        query_variants=payload.query_variants,
                        search_types=payload.search_types,
                        selected_indexers=set(payload.indexers),
                        config=config,
                        websocket=websocket,
                        session_id=session_id,
                        owner_id=owner_id,
                        use_jellyseerr_logic=payload.use_jellyseerr_logic,
                        use_custom_rules=payload.use_custom_rules,
                        tmdb_id=payload.tmdb_id,
                        custom_rules=(
                            payload.custom_rules.model_dump(exclude_none=True)
                            if payload.custom_rules is not None
                            else None
                        ),
                        seasons=payload.seasons,
                    ),
                    timeout=SEARCH_STREAM_TIMEOUT_SECONDS,
                ),
                name=f"search:{session_id}:work",
            )
            async def watch_authorization() -> bool:
                while not search_task.done():
                    await asyncio.sleep(SEARCH_AUTHORIZATION_RECHECK_SECONDS)
                    if await authorize(websocket) is None:
                        return False
                return True

            auth_task = asyncio.create_task(
                watch_authorization(),
                name=f"search:{session_id}:authorization",
            )
            done, _pending = await asyncio.wait(
                {search_task, auth_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if auth_task in done and not auth_task.result():
                await close_bounded(websocket, code=1008)
                accepted = False
                return
            # Parent cancellation must not be forwarded directly to the owned
            # child: the lifecycle helper below issues exactly one cancellation
            # and retains ownership while the child runs its cleanup.
            stats = await asyncio.shield(search_task)
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
        logger.error(
            "[WebSocket /ws/search/%s] Error:\n%s",
            session_id,
            format_exception_for_log(exc),
        )
    finally:
        try:
            await cancel_and_drain_tasks(search_task, auth_task)
        finally:
            try:
                finish_search_session(session_id, owner_id)
            finally:
                if accepted:
                    await close_bounded(websocket, code=1000)
