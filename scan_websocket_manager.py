"""
WebSocket Connection Manager for Library Scan Progress

Gestisce connessioni WebSocket client per aggiornamenti real-time
del progresso delle scansioni librerie Emby.

Sostituisce il sistema di polling inefficiente con push events.
"""

import asyncio
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


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

        # Lock per thread-safety async
        self._lock = asyncio.Lock()

        logger.info("[ScanConnectionManager] Initialized")

    async def connect(self, client_id: str, websocket: WebSocket):
        """
        Accetta connessione WebSocket e registra client.

        Args:
            client_id: ID univoco client (generato dal frontend)
            websocket: Istanza WebSocket FastAPI
        """
        await websocket.accept()

        async with self._lock:
            self.active_connections[client_id] = websocket

        logger.info(f"[ScanConnectionManager] Client {client_id} connected (total: {len(self.active_connections)})")

    async def disconnect(self, client_id: str):
        """
        Rimuove client e cleanup subscriptions.

        Args:
            client_id: ID client da rimuovere
        """
        async with self._lock:
            # Rimuovi connessione
            self.active_connections.pop(client_id, None)

            # Rimuovi da tutte le subscriptions
            for job_id, clients in self.job_subscriptions.items():
                clients.discard(client_id)

            # Cleanup job subscriptions vuote
            empty_jobs = [job_id for job_id, clients in self.job_subscriptions.items() if not clients]
            for job_id in empty_jobs:
                del self.job_subscriptions[job_id]

        logger.info(f"[ScanConnectionManager] Client {client_id} disconnected (total: {len(self.active_connections)})")

    async def subscribe_to_job(self, client_id: str, job_id: str):
        """
        Sottoscrivi client a job specifico per ricevere aggiornamenti.

        Args:
            client_id: ID client
            job_id: ID job scansione
        """
        async with self._lock:
            if job_id not in self.job_subscriptions:
                self.job_subscriptions[job_id] = set()

            self.job_subscriptions[job_id].add(client_id)

        logger.debug(f"[ScanConnectionManager] Client {client_id} subscribed to job {job_id}")

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

        logger.debug(f"[ScanConnectionManager] Client {client_id} unsubscribed from job {job_id}")

    async def send_personal_message(self, client_id: str, message: dict):
        """
        Invia messaggio JSON a client specifico.

        Args:
            client_id: ID client destinatario
            message: Dati da inviare (serializzati come JSON)
        """
        websocket = self.active_connections.get(client_id)

        if not websocket:
            logger.warning(f"[ScanConnectionManager] Cannot send to {client_id}: not connected")
            return

        try:
            await websocket.send_json(message)
            logger.debug(f"[ScanConnectionManager] Sent to {client_id}: {message.get('type', 'unknown')}")
        except Exception as e:
            logger.error(f"[ScanConnectionManager] Error sending to {client_id}: {e}")
            # Auto-disconnect su errore
            await self.disconnect(client_id)

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

        if not clients:
            logger.debug(f"[ScanConnectionManager] No clients subscribed to job {job_id}")
            return

        logger.debug(f"[ScanConnectionManager] Broadcasting to {len(clients)} clients for job {job_id}")

        # Invia a tutti in parallelo
        tasks = [
            self.send_personal_message(client_id, message)
            for client_id in clients
        ]

        # gather con return_exceptions per non bloccare su errori singoli
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log errori
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            logger.warning(f"[ScanConnectionManager] {len(errors)} errors broadcasting to job {job_id}")

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


# Singleton globale
_scan_connection_manager: Optional[ScanConnectionManager] = None


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
