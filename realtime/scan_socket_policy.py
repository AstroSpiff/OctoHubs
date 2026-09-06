"""Validation and abuse limits for the library-scan WebSocket."""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


MAX_SCAN_SOCKET_MESSAGE_BYTES = 2_048
MAX_SCAN_SOCKET_COMMANDS = 30
SCAN_SOCKET_RATE_WINDOW_SECONDS = 10.0

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_JOB_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class InvalidScanSocketCommand(ValueError):
    """Raised when a client message violates the scan socket contract."""


def valid_scan_client_id(client_id: str) -> bool:
    return bool(_CLIENT_ID_RE.fullmatch(str(client_id or "")))


def valid_scan_job_id(job_id: str) -> bool:
    return bool(_JOB_ID_RE.fullmatch(str(job_id or "")))


def parse_scan_socket_command(raw_message: str) -> dict[str, Any]:
    if len(raw_message.encode("utf-8")) > MAX_SCAN_SOCKET_MESSAGE_BYTES:
        raise InvalidScanSocketCommand("message_too_large")
    try:
        payload = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidScanSocketCommand("invalid_json") from exc
    if not isinstance(payload, dict):
        raise InvalidScanSocketCommand("invalid_payload")

    action = payload.get("action")
    if action == "ping":
        return {"action": "ping"}
    if action not in {"subscribe", "unsubscribe"}:
        raise InvalidScanSocketCommand("invalid_action")

    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not valid_scan_job_id(job_id):
        raise InvalidScanSocketCommand("invalid_job_id")
    return {"action": action, "job_id": job_id}


@dataclass
class ScanSocketRateLimiter:
    """Small per-connection sliding-window limiter."""

    timestamps: deque[float] = field(default_factory=deque)

    def consume(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - SCAN_SOCKET_RATE_WINDOW_SECONDS
        while self.timestamps and self.timestamps[0] <= cutoff:
            self.timestamps.popleft()
        if len(self.timestamps) >= MAX_SCAN_SOCKET_COMMANDS:
            return False
        self.timestamps.append(current)
        return True
