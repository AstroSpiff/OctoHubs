"""FastAPI routes for SSE and WebSocket wiring."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app_helpers import DateTimeEncoder
from emby_runtime.snapshots import _build_emby_status_stream_payload
from core.tasks import workflow_manager
from realtime.manager import _sse_event_queues, _sse_queues_lock, _ws_event_queues, _ws_queues_lock
from emby_runtime.scan_websocket_manager import get_scan_connection_manager

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_realtime_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Realtime routes not initialized: require_auth missing")
    return _require_auth(request)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    client_queue: Queue = Queue(maxsize=100)
    with _ws_queues_lock:
        _ws_event_queues.append(client_queue)
    try:
        await websocket.send_json({
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
        })
        while True:
            try:
                event_data = await asyncio.to_thread(client_queue.get, True, 20)
                await websocket.send_json(event_data)
            except Empty:
                await websocket.send_json({
                    "MessageType": "KeepAlive",
                    "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
                })
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_queues_lock:
            if client_queue in _ws_event_queues:
                _ws_event_queues.remove(client_queue)


@router.websocket("/ws/scan/{client_id}")
async def websocket_scan_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint per aggiornamenti scansione librerie in tempo reale.

    Sostituisce il polling HTTP inefficiente con push events real-time.

    Messaggi inviati dal server al client:
        - {"type": "progress", "job_id": "...", "progress": 0.45, "message": "Scanning..."}
        - {"type": "completed", "job_id": "...", "summary": {...}}
        - {"type": "error", "job_id": "...", "error": "..."}
        - {"type": "subscribed", "job_id": "..."}

    Messaggi ricevuti dal client:
        - {"action": "subscribe", "job_id": "..."}
        - {"action": "unsubscribe", "job_id": "..."}
        - {"action": "cancel", "job_id": "..."}

    Args:
        websocket: Istanza WebSocket FastAPI
        client_id: ID univoco client (generato dal frontend)
    """
    manager = get_scan_connection_manager()
    await manager.connect(client_id, websocket)

    try:
        while True:
            # Ricevi messaggi dal client
            data = await websocket.receive_json()

            action = data.get("action")
            job_id = data.get("job_id")
            print(
                f"[WebSocket /ws/scan/{client_id}] Received: action={action}, job_id={job_id}",
                flush=True,
            )

            if action == "subscribe" and job_id:
                # Sottoscrivi client a job
                await manager.subscribe_to_job(client_id, job_id)
                await manager.send_personal_message(
                    client_id,
                    {
                        "type": "subscribed",
                        "job_id": job_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            elif action == "unsubscribe" and job_id:
                # Rimuovi subscription
                await manager.unsubscribe_from_job(client_id, job_id)
                await manager.send_personal_message(
                    client_id,
                    {
                        "type": "unsubscribed",
                        "job_id": job_id,
                    },
                )

            elif action == "cancel" and job_id:
                # TODO: Implementare cancellazione job
                # Richiede integrazione con LibraryScanTracker
                await manager.send_personal_message(
                    client_id,
                    {
                        "type": "cancel_requested",
                        "job_id": job_id,
                        "message": "Cancellazione job non ancora implementata",
                    },
                )

            elif action == "ping":
                # Keepalive / heartbeat
                await manager.send_personal_message(
                    client_id,
                    {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

    except WebSocketDisconnect:
        # Client disconnesso normalmente
        pass
    except Exception as e:
        # Errore imprevisto
        print(f"[WebSocket /ws/scan/{client_id}] Error: {e}", flush=True)
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup: rimuovi client e subscriptions
        await manager.disconnect(client_id)


@router.websocket("/ws/search/{session_id}")
async def websocket_search_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint per ricerca streaming in tempo reale.

    I risultati vengono inviati al client appena arrivano da Prowlarr/Jackett,
    senza attendere il completamento di tutte le query.

    Messaggi inviati dal server al client:
        - {"type": "connected", "session_id": "..."}
        - {"type": "query_started", "query": "...", "indexer": "prowlarr|jackett", "media_type": "movie|tv"}
        - {"type": "result", "data": {...}, "query": "...", "indexer": "..."}
        - {"type": "query_completed", "query": "...", "indexer": "...", "count": 10, "duration": 2.3}
        - {"type": "all_completed", "total_results": 45, "total_duration": 18.5}
        - {"type": "error", "query": "...", "indexer": "...", "error": "..."}

    Args:
        websocket: Istanza WebSocket FastAPI
        session_id: ID univoco sessione di ricerca
    """
    await websocket.accept()

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Attendi parametri di ricerca dal client
        data = await websocket.receive_json()
        action = data.get("action")

        if action == "start_search":
            # Estrai parametri di ricerca
            query_variants = data.get("query_variants", [])
            search_types = data.get("search_types", [])
            selected_indexers = set(data.get("indexers", []))
            use_jellyseerr_logic = bool(data.get("use_jellyseerr_logic", False))
            use_custom_rules = bool(data.get("use_custom_rules", False))
            tmdb_id = data.get("tmdb_id", "")
            custom_rules = data.get("custom_rules")

            print(
                f"[WebSocket /ws/search/{session_id}] Avvio ricerca: {len(query_variants)} variants, "
                f"{len(selected_indexers)} indexers, jellyseerr={use_jellyseerr_logic}"
            )

            # Carica config
            from core.config_manager import load_config
            from search.streaming import search_streaming_parallel

            config, is_valid = load_config()

            if not is_valid or not config:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Configurazione non valida",
                    }
                )
                return

            # Esegui ricerca streaming
            stats = await search_streaming_parallel(
                query_variants=query_variants,
                search_types=search_types,
                selected_indexers=selected_indexers,
                config=config,
                websocket=websocket,
                session_id=session_id,
                use_jellyseerr_logic=use_jellyseerr_logic,
                use_custom_rules=use_custom_rules,
                tmdb_id=tmdb_id,
                custom_rules=custom_rules,
            )

            print(f"[WebSocket /ws/search/{session_id}] Ricerca completata: {stats}")

        # Mantieni connessione aperta per keepalive
        while True:
            try:
                data = await websocket.receive_json()
                action = data.get("action")

                if action == "ping":
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

            except Exception as e:
                print(f"[WebSocket /ws/search/{session_id}] Receive error: {e}")
                break

    except WebSocketDisconnect:
        print(f"[WebSocket /ws/search/{session_id}] Client disconnected")
    except Exception as e:
        print(f"[WebSocket /ws/search/{session_id}] Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup se necessario
        pass


@router.get("/emby/events-stream")
async def emby_events_stream(request: Request):
    _require_auth_dep(request)

    async def event_stream():
        client_queue: Queue = Queue(maxsize=50)
        with _sse_queues_lock:
            _sse_event_queues.append(client_queue)

        initial_event = {
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
        yield f"data: {json.dumps(initial_event, cls=DateTimeEncoder)}\n\n"

        try:
            while True:
                try:
                    event_data = await asyncio.to_thread(client_queue.get, True, 20)
                    msg = f"data: {json.dumps(event_data, cls=DateTimeEncoder)}\n\n"
                    yield msg
                except Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_queues_lock:
                if client_queue in _sse_event_queues:
                    _sse_event_queues.remove(client_queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/emby/events-stream")
async def emby_events_stream_api(request: Request):
    return await emby_events_stream(request)


@router.get("/emby/status-stream")
async def emby_status_stream(request: Request):
    _require_auth_dep(request)

    async def event_stream():
        while True:
            try:
                payload = await asyncio.to_thread(_build_emby_status_stream_payload)
                msg = f"data: {json.dumps(payload, cls=DateTimeEncoder)}\n\n"
                yield msg
                await asyncio.sleep(2)
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/emby/status-stream")
async def emby_status_stream_api(request: Request):
    return await emby_status_stream(request)


@router.get("/api/workflow/events")
async def workflow_events(request: Request):
    _require_auth_dep(request)

    async def generate():
        status = workflow_manager.get_status()
        yield f"data: {json.dumps(status)}\n\n"
        last_status = status
        updates_without_change = 0

        while True:
            await asyncio.sleep(2)
            status = workflow_manager.get_status()

            # Invia aggiornamento se cambiato O ogni 5 poll (10 secondi) per aggiornare il timer
            if status != last_status:
                yield f"data: {json.dumps(status)}\n\n"
                last_status = status
                updates_without_change = 0
            else:
                updates_without_change += 1
                # Ogni 5 poll (10 secondi), invia comunque per aggiornare il timer elapsed
                if updates_without_change >= 5:
                    yield f"data: {json.dumps(status)}\n\n"
                    updates_without_change = 0

            if status.get("status") in ("completed", "failed", "idle"):
                await asyncio.sleep(1)
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
