"""Scan concurrency locks (per-server)."""

from __future__ import annotations

import asyncio

_scan_locks: dict[str, asyncio.Lock] = {}
_scan_locks_lock = asyncio.Lock()


async def acquire_scan_lock(server_id: str) -> bool:
    """
    Acquisisce lock per scansione su server specifico.
    Previene scansioni concorrenti sullo stesso server.

    Returns:
        True se lock acquisito, False se già in uso
    """
    async with _scan_locks_lock:
        if server_id not in _scan_locks:
            _scan_locks[server_id] = asyncio.Lock()

    lock = _scan_locks[server_id]

    # Try acquire non-blocking
    if lock.locked():
        return False  # Scan già in corso

    await lock.acquire()
    return True


async def release_scan_lock(server_id: str) -> None:
    """Rilascia lock scansione."""
    lock = _scan_locks.get(server_id)
    if lock and lock.locked():
        lock.release()
