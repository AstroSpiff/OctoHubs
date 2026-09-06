"""FastAPI routes for SSE and WebSocket wiring."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app_helpers import DateTimeEncoder
from emby_runtime.snapshots import _build_emby_status_stream_payload
from emby_runtime.runtime_api_models import EmbyStatusSnapshotResponse
from core.tasks import workflow_manager
from realtime.external_api_models import ExternalRealtimeChangesResponse
from realtime.external_change_feed import EXTERNAL_CHANGE_RETENTION, read_external_changes
from realtime.subscribers import sse_subscribers, websocket_subscribers
from realtime.connection_limits import acquire_connection, auth_subject_id
from realtime.lease_stream import LeaseBoundAsyncIterator
from realtime.status_snapshot import shared_status_snapshot
from core.websocket_io import accept_bounded, close_bounded, send_json_bounded
from realtime.scan_socket_policy import (
    InvalidScanSocketCommand,
    ScanSocketRateLimiter,
    parse_scan_socket_command,
    valid_scan_client_id,
)
from emby_runtime.scan_websocket_manager import get_scan_connection_manager

router = APIRouter()

_require_auth: Optional[Callable[[Any], Any]] = None


def init_realtime_routes(require_auth: Callable[[Any], Any]) -> None:
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
    await run_in_threadpool(_require_auth_dep, request)
    return read_external_changes(after=after, limit=limit)


async def _authorize_websocket(websocket: WebSocket) -> Any | None:
    """Reject realtime sockets that do not originate from an authenticated session."""
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and not _websocket_origin_matches(websocket, origin, host):
        await close_bounded(websocket, code=1008)
        return None

    try:
        return await run_in_threadpool(_require_auth_dep, websocket)
    except HTTPException:
        await close_bounded(websocket, code=1008)
        return None


def _websocket_origin_matches(websocket: WebSocket, origin: str, host: str | None) -> bool:
    actual = _normalized_http_origin(origin)
    if actual is None:
        return False

    configured = str(os.getenv("OCTOHUBS_PUBLIC_ORIGIN") or "").strip()
    if configured:
        return actual == _normalized_http_origin(configured)

    scope = getattr(websocket, "scope", {}) or {}
    websocket_scheme = str(scope.get("scheme") or getattr(getattr(websocket, "url", None), "scheme", "")).lower()
    expected_scheme = {"ws": "http", "wss": "https", "http": "http", "https": "https"}.get(websocket_scheme)
    if expected_scheme:
        return actual == _normalized_http_origin(f"{expected_scheme}://{host or ''}")

    # Compatibility for lightweight ASGI test doubles; real WebSockets always
    # provide a scheme in their scope.
    return urlparse(origin).netloc.lower() == str(host or "").lower()


def _normalized_http_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(str(value or "").strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            return None
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme.lower(), parsed.hostname.lower(), port


async def _revalidate_subject(connection: Any, expected_subject: Any) -> bool:
    """Re-check account epoch/activity or token revocation without cached auth state."""
    from web.session_auth import revalidate_authenticated_subject

    try:
        expected_user_id = int(auth_subject_id(expected_subject))
    except (TypeError, ValueError):
        return False
    return bool(
        await run_in_threadpool(
            revalidate_authenticated_subject,
            connection,
            expected_user_id,
        )
    )


async def _connect_scan_client(
    manager: Any,
    client_id: str,
    websocket: WebSocket,
    lease: Any,
) -> bool:
    """Connect a scan socket while preserving lease ownership on every exit."""
    try:
        connected = await manager.connect(client_id, websocket)
    except BaseException:
        lease.release()
        raise
    if connected:
        return True
    try:
        await close_bounded(websocket, code=1013)
    finally:
        lease.release()
    return False


async def _disconnect_scan_client(manager: Any, client_id: str, lease: Any) -> None:
    """Drain the client and release its quota even under repeated cancellation."""
    try:
        await manager.disconnect(client_id)
    finally:
        lease.release()


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    subject = await _authorize_websocket(websocket)
    if not subject:
        return
    lease = acquire_connection(subject, "events-ws")
    if lease is None:
        await close_bounded(websocket, code=1013)
        return
    subscriber = None
    try:
        await accept_bounded(websocket)
        subscriber = websocket_subscribers.subscribe(maxsize=100)
        await send_json_bounded(websocket, {
            "MessageType": "Connected",
            "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
        })
        while True:
            if not await _revalidate_subject(websocket, subject):
                await close_bounded(websocket, code=1008)
                break
            try:
                event_data = await subscriber.get(timeout=20)
                await send_json_bounded(websocket, event_data)
            except asyncio.TimeoutError:
                await send_json_bounded(websocket, {
                    "MessageType": "KeepAlive",
                    "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
                })
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber is not None:
            websocket_subscribers.unsubscribe(subscriber)
        lease.release()


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
    subject = await _authorize_websocket(websocket)
    if not subject:
        return
    if not valid_scan_client_id(client_id):
        await close_bounded(websocket, code=1008)
        return
    lease = acquire_connection(subject, "scan-ws")
    if lease is None:
        await close_bounded(websocket, code=1013)
        return

    manager = get_scan_connection_manager()
    if not await _connect_scan_client(manager, client_id, websocket, lease):
        return
    rate_limiter = ScanSocketRateLimiter()

    try:
        while True:
            if not await _revalidate_subject(websocket, subject):
                await close_bounded(websocket, code=1008)
                return
            try:
                raw_message = await asyncio.wait_for(websocket.receive_text(), timeout=20)
            except asyncio.TimeoutError:
                continue
            if not rate_limiter.consume():
                await close_bounded(websocket, code=1008)
                return
            try:
                data = parse_scan_socket_command(raw_message)
            except InvalidScanSocketCommand:
                await close_bounded(websocket, code=1008)
                return

            action = data.get("action")
            job_id = data.get("job_id")
            if action == "subscribe" and job_id:
                from app_state import _LIBRARY_SCAN_TRACKER

                if _LIBRARY_SCAN_TRACKER.get_job(job_id) is None:
                    await close_bounded(websocket, code=1008)
                    return
                if not await manager.subscribe_to_job(client_id, job_id):
                    await close_bounded(websocket, code=1008)
                    return
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
    except Exception:
        # Do not reflect parser or transport details to the client.
        pass
    finally:
        # Cleanup: rimuovi client e subscriptions
        await _disconnect_scan_client(manager, client_id, lease)


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
    subject = await _authorize_websocket(websocket)
    if not subject:
        return
    lease = acquire_connection(subject, "search-ws")
    if lease is None:
        await close_bounded(websocket, code=1013)
        return

    authorization_checks = 0

    async def authorized_subject(_websocket):
        nonlocal authorization_checks
        authorization_checks += 1
        if authorization_checks == 1:
            return auth_subject_id(subject)
        if await _revalidate_subject(websocket, subject):
            return auth_subject_id(subject)
        return None

    try:
        await handle_search_websocket(websocket, session_id, authorized_subject)
    finally:
        lease.release()


@router.get("/api/emby/events-stream")
async def emby_events_stream_api(request: Request):
    subject = await run_in_threadpool(_require_auth_dep, request)
    lease = acquire_connection(subject, "events-sse")
    if lease is None:
        raise HTTPException(status_code=429, detail="Troppe connessioni realtime")

    async def event_stream():
        subscriber = None
        try:
            subscriber = sse_subscribers.subscribe(maxsize=50)
            initial_event = {
                "MessageType": "Connected",
                "Data": {"timestamp": datetime.now(timezone.utc).isoformat()},
            }
            yield f"data: {json.dumps(initial_event, cls=DateTimeEncoder)}\n\n"

            while True:
                if not await _revalidate_subject(request, subject):
                    break
                try:
                    event_data = await subscriber.get(timeout=20)
                    msg = f"data: {json.dumps(event_data, cls=DateTimeEncoder)}\n\n"
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if subscriber is not None:
                sse_subscribers.unsubscribe(subscriber)
            lease.release()

    return StreamingResponse(
        LeaseBoundAsyncIterator(event_stream(), lease),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/emby/status-stream")
async def emby_status_stream_api(request: Request):
    subject = await run_in_threadpool(_require_auth_dep, request)
    lease = acquire_connection(subject, "status-sse")
    if lease is None:
        raise HTTPException(status_code=429, detail="Troppe connessioni realtime")

    async def event_stream():
        try:
            while True:
                if not await _revalidate_subject(request, subject):
                    break
                try:
                    payload = await shared_status_snapshot(_build_emby_status_stream_payload)
                    msg = f"data: {json.dumps(payload, cls=DateTimeEncoder)}\n\n"
                    yield msg
                    await asyncio.sleep(2)
                except Exception:
                    await asyncio.sleep(5)
        finally:
            lease.release()

    return StreamingResponse(
        LeaseBoundAsyncIterator(event_stream(), lease),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/emby/status", response_model=EmbyStatusSnapshotResponse)
async def emby_status_snapshot_api(request: Request):
    """Return one complete status snapshot when the SSE feed is unavailable."""
    await run_in_threadpool(_require_auth_dep, request)
    payload = await shared_status_snapshot(_build_emby_status_stream_payload)
    return Response(
        content=json.dumps(payload, cls=DateTimeEncoder),
        media_type="application/json",
    )


@router.get("/api/workflow/events")
async def workflow_events(request: Request):
    subject = await run_in_threadpool(_require_auth_dep, request)
    lease = acquire_connection(subject, "workflow-sse")
    if lease is None:
        raise HTTPException(status_code=429, detail="Troppe connessioni realtime")

    async def generate():
        try:
            status = await asyncio.to_thread(workflow_manager.get_status)
            yield f"data: {json.dumps(status)}\n\n"
            last_status = status
            updates_without_change = 0

            while True:
                await asyncio.sleep(2)
                if not await _revalidate_subject(request, subject):
                    break
                status = await asyncio.to_thread(workflow_manager.get_status)

                # Invia aggiornamento se cambiato o periodicamente per il timer.
                if status != last_status:
                    yield f"data: {json.dumps(status)}\n\n"
                    last_status = status
                    updates_without_change = 0
                else:
                    updates_without_change += 1
                    # Ogni 5 poll invia comunque per aggiornare il timer elapsed.
                    if updates_without_change >= 5:
                        yield f"data: {json.dumps(status)}\n\n"
                        updates_without_change = 0

                if status.get("status") in ("completed", "failed", "idle"):
                    await asyncio.sleep(1)
                    break
        finally:
            lease.release()

    return StreamingResponse(
        LeaseBoundAsyncIterator(generate(), lease),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
