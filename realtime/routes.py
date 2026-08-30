"""FastAPI routes for SSE and WebSocket wiring."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from app_helpers import DateTimeEncoder
from emby_runtime.snapshots import _build_emby_status_stream_payload
from emby_runtime.runtime_api_models import EmbyStatusSnapshotResponse
from core.tasks import workflow_manager
from realtime.external_api_models import ExternalRealtimeChangesResponse
from realtime.external_change_feed import EXTERNAL_CHANGE_RETENTION, read_external_changes
from realtime.subscribers import sse_subscribers, websocket_subscribers
from emby_runtime.scan_websocket_manager import get_scan_connection_manager

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None


def init_realtime_routes(require_auth: Callable[[Request], Any]) -> None:
    global _require_auth
    _require_auth = require_auth


def _require_auth_dep(request: Request | WebSocket):
    if _require_auth is None:
        raise RuntimeError("Realtime routes not initialized: require_auth missing")
    return _require_auth(request)


@router.get(
    "/api/realtime/changes",
    response_model=ExternalRealtimeChangesResponse,
    summary="Read external realtime changes",
)
async def external_realtime_changes_api(
    request: Request,
    after: int = Query(default=0, ge=0, description="Cursor returned by the preceding response."),
    limit: int = Query(default=100, ge=1, le=EXTERNAL_CHANGE_RETENTION, description="Maximum changes to return."),
):
    """Return safe invalidations; reread the relevant canonical v1 resource."""
    _require_auth_dep(request)
    return read_external_changes(after=after, limit=limit)


async def _authorize_websocket(websocket: WebSocket) -> Any | None:
    """Reject realtime sockets that do not originate from an authenticated session."""
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and urlparse(origin).netloc.lower() != str(host or "").lower():
        await websocket.close(code=1008)
        return None

    try:
        return _require_auth_dep(websocket)
    except HTTPException:
        await websocket.close(code=1008)
        return None


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    if not await _authorize_websocket(websocket):
        return
    await websocket.accept()
    subscriber = websocket_subscribers.subscribe(maxsize=100)
    try:
        await websocket.send_json({
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
        })
        while True:
            try:
                event_data = await subscriber.get(timeout=20)
                await websocket.send_json(event_data)
            except asyncio.TimeoutError:
                await websocket.send_json({
                    "MessageType": "KeepAlive",
                    "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
                })
    except WebSocketDisconnect:
        pass
    finally:
        websocket_subscribers.unsubscribe(subscriber)


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

    Args:
        websocket: Istanza WebSocket FastAPI
        client_id: ID univoco client (generato dal frontend)
    """
    if not await _authorize_websocket(websocket):
        return

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
    from search.websocket import handle_search_websocket

    await handle_search_websocket(websocket, session_id, _authorize_websocket)


@router.get("/api/emby/events-stream")
async def emby_events_stream_api(request: Request):
    _require_auth_dep(request)

    async def event_stream():
        subscriber = sse_subscribers.subscribe(maxsize=50)

        initial_event = {
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
        yield f"data: {json.dumps(initial_event, cls=DateTimeEncoder)}\n\n"

        try:
            while True:
                try:
                    event_data = await subscriber.get(timeout=20)
                    msg = f"data: {json.dumps(event_data, cls=DateTimeEncoder)}\n\n"
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_subscribers.unsubscribe(subscriber)

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


@router.get("/api/emby/status", response_model=EmbyStatusSnapshotResponse)
async def emby_status_snapshot_api(request: Request):
    """Return one complete status snapshot when the SSE feed is unavailable."""
    _require_auth_dep(request)
    payload = await asyncio.to_thread(_build_emby_status_stream_payload)
    return Response(
        content=json.dumps(payload, cls=DateTimeEncoder),
        media_type="application/json",
    )


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
