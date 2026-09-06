"""
WebSocket Connection Manager for Library Scan Progress

Gestisce connessioni WebSocket client per aggiornamenti real-time
del progresso delle scansioni librerie Emby.

Sostituisce il sistema di polling inefficiente con push events.
"""

import asyncio
import logging
import threading
from typing import Dict, Set, Optional
from fastapi import WebSocket

from core.log_sanitization import format_exception_for_log
from core.websocket_io import accept_bounded
logger = logging.getLogger(__name__)

MAX_SCAN_CONNECTIONS = 200
MAX_SCAN_SUBSCRIPTIONS_PER_CLIENT = 50
MAX_SCAN_OUTBOUND_MESSAGES_PER_CLIENT = 32
SCAN_SEND_TIMEOUT_SECONDS = 5.0
SCAN_CLOSE_TIMEOUT_SECONDS = 1.0


class ScanConnectionManager:
    """
    Gestisce connessioni WebSocket per scan progress updates.

    Pattern:
    - Client si connette a /ws/scan/{client_id}
    - Client sottoscrive job specifici con {"action": "subscribe", "job_id": "..."}
    - Server invia aggiornamenti progress via broadcast_to_job()
    """

    def __init__(self):
        # Connessioni attive: client_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

        # Subscriptions: job_id -> Set[client_id]
        # Permette broadcast a tutti client interessati a un job
        self.job_subscriptions: Dict[str, Set[str]] = {}
        self._outbound_queues: Dict[str, asyncio.Queue[dict]] = {}
        self._writer_tasks: Dict[str, asyncio.Task] = {}
        self._broadcast_tasks: set[asyncio.Task] = set()
        self._scheduled_broadcasts: Dict[str, dict] = {}
        self._scheduled_jobs: set[str] = set()
        self._schedule_lock = threading.Lock()
        self._accept_scheduled_broadcasts = True

        # Lock per thread-safety async
        self._lock = asyncio.Lock()

        logger.info("[ScanConnectionManager] Initialized")

    async def connect(self, client_id: str, websocket: WebSocket) -> bool:
        """
        Accetta connessione WebSocket e registra client.

        Args:
            client_id: ID univoco client (generato dal frontend)
            websocket: Istanza WebSocket FastAPI
        """
        async with self._lock:
            if client_id in self.active_connections:
                return False
            if len(self.active_connections) >= MAX_SCAN_CONNECTIONS:
                return False
            self.active_connections[client_id] = websocket
            self._outbound_queues[client_id] = asyncio.Queue(
                maxsize=MAX_SCAN_OUTBOUND_MESSAGES_PER_CLIENT
            )

        try:
            await accept_bounded(websocket)
        except BaseException:
            async with self._lock:
                self.active_connections.pop(client_id, None)
                self._outbound_queues.pop(client_id, None)
            raise

        logger.info(f"[ScanConnectionManager] Client {client_id} connected (total: {len(self.active_connections)})")
        return True

    async def disconnect(self, client_id: str):
        """
        Rimuove client e cleanup subscriptions.

        Args:
            client_id: ID client da rimuovere
        """
        task = await self._detach_client(client_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        logger.info(f"[ScanConnectionManager] Client {client_id} disconnected (total: {len(self.active_connections)})")

    async def subscribe_to_job(self, client_id: str, job_id: str) -> bool:
        """
        Sottoscrivi client a job specifico per ricevere aggiornamenti.

        Args:
            client_id: ID client
            job_id: ID job scansione
        """
        async with self._lock:
            if client_id not in self.active_connections:
                return False
            current_subscriptions = sum(
                client_id in clients for clients in self.job_subscriptions.values()
            )
            already_subscribed = client_id in self.job_subscriptions.get(job_id, set())
            if not already_subscribed and current_subscriptions >= MAX_SCAN_SUBSCRIPTIONS_PER_CLIENT:
                return False
            if job_id not in self.job_subscriptions:
                self.job_subscriptions[job_id] = set()

            self.job_subscriptions[job_id].add(client_id)

        logger.info(f"[ScanConnectionManager] ✓ Client {client_id} SUBSCRIBED to job {job_id} (total clients for this job: {len(self.job_subscriptions[job_id])})")
        return True

    async def unsubscribe_from_job(self, client_id: str, job_id: str):
        """
        Rimuovi subscription client da job.

        Args:
            client_id: ID client
            job_id: ID job
        """
        async with self._lock:
            if job_id in self.job_subscriptions:
                self.job_subscriptions[job_id].discard(client_id)

                # Cleanup se nessun client sottoscritto
                if not self.job_subscriptions[job_id]:
                    del self.job_subscriptions[job_id]

        logger.info(f"[ScanConnectionManager] Client {client_id} UNSUBSCRIBED from job {job_id}")

    async def _detach_client(
        self,
        client_id: str,
        *,
        websocket: WebSocket | None = None,
    ) -> asyncio.Task | None:
        async with self._lock:
            current = self.active_connections.get(client_id)
            if websocket is not None and current is not websocket:
                return None
            self.active_connections.pop(client_id, None)
            self._outbound_queues.pop(client_id, None)
            writer = self._writer_tasks.pop(client_id, None)
            for clients in self.job_subscriptions.values():
                clients.discard(client_id)
            empty_jobs = [
                job_id for job_id, clients in self.job_subscriptions.items() if not clients
            ]
            for job_id in empty_jobs:
                del self.job_subscriptions[job_id]
            return writer

    async def _close_slow_client(self, client_id: str, websocket: WebSocket) -> None:
        writer = await self._detach_client(client_id, websocket=websocket)
        if writer is not None and writer is not asyncio.current_task():
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        try:
            await asyncio.wait_for(
                websocket.close(code=1013),
                timeout=SCAN_CLOSE_TIMEOUT_SECONDS,
            )
        except Exception:
            pass

    async def _writer_loop(
        self,
        client_id: str,
        websocket: WebSocket,
        queue: asyncio.Queue[dict],
    ) -> None:
        try:
            while True:
                message = await queue.get()
                await asyncio.wait_for(
                    websocket.send_json(message),
                    timeout=SCAN_SEND_TIMEOUT_SECONDS,
                )
                logger.debug(
                    "[ScanConnectionManager] Sent to %s: %s",
                    client_id,
                    message.get("type", "unknown"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[ScanConnectionManager] Closing slow client %s:\n%s",
                client_id,
                format_exception_for_log(exc),
            )
            await self._close_slow_client(client_id, websocket)
        finally:
            async with self._lock:
                if self._writer_tasks.get(client_id) is asyncio.current_task():
                    self._writer_tasks.pop(client_id, None)

    async def send_personal_message(self, client_id: str, message: dict) -> bool:
        """
        Invia messaggio JSON a client specifico.

        Args:
            client_id: ID client destinatario
            message: Dati da inviare (serializzati come JSON)
        """
        slow_websocket = None
        async with self._lock:
            websocket = self.active_connections.get(client_id)
            queue = self._outbound_queues.get(client_id)
            if websocket is None or queue is None:
                logger.warning(
                    "[ScanConnectionManager] Cannot send to %s: not connected",
                    client_id,
                )
                return False
            try:
                queue.put_nowait(dict(message))
            except asyncio.QueueFull:
                slow_websocket = websocket
            else:
                writer = self._writer_tasks.get(client_id)
                if writer is None or writer.done():
                    self._writer_tasks[client_id] = asyncio.create_task(
                        self._writer_loop(client_id, websocket, queue)
                    )
                return True

        if slow_websocket is not None:
            logger.warning(
                "[ScanConnectionManager] Outbound queue full for %s; disconnecting",
                client_id,
            )
            await self._close_slow_client(client_id, slow_websocket)
        return False

    async def broadcast_to_job(self, job_id: str, message: dict):
        """
        Broadcast messaggio a tutti client sottoscritti a job.

        Args:
            job_id: ID job
            message: Dati da broadcast
        """
        # Copia set client per evitare modifiche durante iterazione
        async with self._lock:
            clients = self.job_subscriptions.get(job_id, set()).copy()
            total_subs = len(self.job_subscriptions)
            total_connections = len(self.active_connections)

        if not clients:
            logger.warning(f"[ScanConnectionManager] ✗ No clients subscribed to job {job_id} (total jobs: {total_subs}, total connections: {total_connections})")
            return

        logger.info(f"[ScanConnectionManager] ✓ Broadcasting to {len(clients)} clients for job {job_id}: {message.get('type', 'unknown')}")

        results = await asyncio.gather(
            *(self.send_personal_message(client_id, message) for client_id in clients),
            return_exceptions=True,
        )
        failures = sum(result is False or isinstance(result, Exception) for result in results)
        if failures:
            logger.warning(
                "[ScanConnectionManager] %d clients did not accept broadcast for job %s",
                failures,
                job_id,
            )

    def schedule_broadcast(
        self,
        loop: asyncio.AbstractEventLoop,
        job_id: str,
        message: dict,
    ) -> bool:
        """Coalesce thread-originated progress into one cancellable drain per job."""
        if not loop.is_running():
            return False
        should_schedule = False
        with self._schedule_lock:
            if not self._accept_scheduled_broadcasts:
                return False
            current = self._scheduled_broadcasts.get(job_id)
            current_terminal = (current or {}).get("type") in {"completed", "error"}
            incoming_terminal = message.get("type") in {"completed", "error"}
            if not current_terminal or incoming_terminal:
                self._scheduled_broadcasts[job_id] = dict(message)
            if job_id not in self._scheduled_jobs:
                self._scheduled_jobs.add(job_id)
                should_schedule = True
        if should_schedule:
            try:
                loop.call_soon_threadsafe(self._start_broadcast_drain, job_id)
            except RuntimeError:
                with self._schedule_lock:
                    self._scheduled_jobs.discard(job_id)
                    self._scheduled_broadcasts.pop(job_id, None)
                return False
        return True

    def _start_broadcast_drain(self, job_id: str) -> None:
        with self._schedule_lock:
            if (
                not self._accept_scheduled_broadcasts
                or job_id not in self._scheduled_jobs
            ):
                return
        task = asyncio.create_task(self._drain_scheduled_broadcasts(job_id))
        self._broadcast_tasks.add(task)
        task.add_done_callback(self._broadcast_tasks.discard)

    async def _drain_scheduled_broadcasts(self, job_id: str) -> None:
        try:
            while True:
                with self._schedule_lock:
                    message = self._scheduled_broadcasts.pop(job_id, None)
                    if message is None:
                        self._scheduled_jobs.discard(job_id)
                        return
                await self.broadcast_to_job(job_id, message)
        finally:
            with self._schedule_lock:
                self._scheduled_jobs.discard(job_id)
                self._scheduled_broadcasts.pop(job_id, None)

    async def get_stats(self) -> dict:
        """
        Restituisce statistiche connessioni per monitoring.

        Returns:
            Dict con statistiche
        """
        async with self._lock:
            return {
                "total_connections": len(self.active_connections),
                "total_subscriptions": len(self.job_subscriptions),
                "clients": list(self.active_connections.keys()),
                "jobs": {
                    job_id: len(clients)
                    for job_id, clients in self.job_subscriptions.items()
                }
            }

    async def shutdown(self) -> None:
        """Drain process-local clients and writers before the event loop closes."""
        with self._schedule_lock:
            self._accept_scheduled_broadcasts = False
            self._scheduled_broadcasts.clear()
            self._scheduled_jobs.clear()
        async with self._lock:
            sockets = list(self.active_connections.values())
            tasks = list(self._writer_tasks.values()) + list(self._broadcast_tasks)
            self.active_connections.clear()
            self.job_subscriptions.clear()
            self._outbound_queues.clear()
            self._writer_tasks.clear()
            self._broadcast_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if sockets:
            await asyncio.gather(
                *(
                    asyncio.wait_for(
                        websocket.close(code=1001),
                        timeout=SCAN_CLOSE_TIMEOUT_SECONDS,
                    )
                    for websocket in sockets
                ),
                return_exceptions=True,
            )


# Singleton globale
_scan_connection_manager: Optional[ScanConnectionManager] = None


def initialize_scan_connection_manager() -> ScanConnectionManager:
    """Create the manager owned by the current application lifespan."""
    global _scan_connection_manager
    previous = _scan_connection_manager
    if previous is not None and (
        previous.active_connections
        or any(not task.done() for task in previous._writer_tasks.values())
    ):
        raise RuntimeError("Scan WebSocket manager ancora attivo durante la riapertura")
    _scan_connection_manager = ScanConnectionManager()
    return _scan_connection_manager


def get_scan_connection_manager() -> ScanConnectionManager:
    """
    Ottieni istanza singleton del ConnectionManager.

    Returns:
        Istanza globale ScanConnectionManager
    """
    global _scan_connection_manager

    if _scan_connection_manager is None:
        _scan_connection_manager = ScanConnectionManager()

    return _scan_connection_manager
