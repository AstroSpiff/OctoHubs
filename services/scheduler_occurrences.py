"""PostgreSQL-backed single-consumer claims for automatic task occurrences."""

from __future__ import annotations

import uuid
import threading
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core.thread_lifecycle import (
    join_owned_thread,
    log_lifecycle_exception_safely,
    start_owned_thread,
    thread_has_started,
)


logger = logging.getLogger(__name__)


_CLAIM_TTL_SECONDS = 120
_RENEW_INTERVAL_SECONDS = 30.0
_KEY_PREFIX = "auto_scheduler_occurrence:v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SchedulerOccurrenceClaim:
    kind: str
    token: str
    owner_id: str
    scheduled_for: str


class SchedulerOccurrenceCoordinator:
    """Serialize one logical schedule occurrence without holding DB during I/O."""

    def __init__(
        self,
        storage_getter: Callable[[], Any],
        *,
        owner_id: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._storage_getter = storage_getter
        self._owner_id = str(owner_id or uuid.uuid4().hex)
        self._now = now or _utc_now

    def claim(
        self,
        kind: str,
        settings: dict[str, Any],
        scheduled_for: datetime,
    ) -> SchedulerOccurrenceClaim | None:
        claim, _status = self.claim_with_status(kind, settings, scheduled_for)
        return claim

    def claim_with_status(
        self,
        kind: str,
        settings: dict[str, Any],
        scheduled_for: datetime,
    ) -> tuple[SchedulerOccurrenceClaim | None, str]:
        """Claim an occurrence and describe why an existing claim rejected it."""
        normalized_kind = str(kind or "task")
        scheduled = _aware(scheduled_for)
        token = self._token(settings, scheduled)
        now = _aware(self._now())
        claim = SchedulerOccurrenceClaim(
            kind=normalized_kind,
            token=token,
            owner_id=self._owner_id,
            scheduled_for=scheduled.isoformat(),
        )
        accepted: list[bool] = []
        rejection: list[str] = []

        def update(current: Any) -> dict[str, Any]:
            state = dict(current) if isinstance(current, dict) else {}
            current_token = str(state.get("token") or "")
            current_status = str(state.get("status") or "")
            expires_at = _parse_timestamp(state.get("expires_at"))
            current_scheduled = _parse_timestamp(state.get("scheduled_for"))
            is_current_or_newer = bool(current_scheduled and current_scheduled >= scheduled)
            duplicate = current_token == token or is_current_or_newer
            active = current_status == "claimed" and expires_at is not None and expires_at > now
            if duplicate and (current_status == "completed" or active):
                accepted.append(False)
                rejection.append("completed" if current_status == "completed" else "active")
                return state
            accepted.append(True)
            return {
                "version": 1,
                "kind": normalized_kind,
                "token": token,
                "owner_id": self._owner_id,
                "status": "claimed",
                "scheduled_for": scheduled.isoformat(),
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=_CLAIM_TTL_SECONDS)).isoformat(),
            }

        self._storage_getter().update_key_value(self._key(normalized_kind), update)
        if accepted and accepted[0]:
            return claim, "claimed"
        return None, rejection[0] if rejection else "unavailable"

    def complete(self, claim: SchedulerOccurrenceClaim) -> bool:
        now = _aware(self._now())
        completed: list[bool] = []

        def update(current: Any) -> Any:
            state = dict(current) if isinstance(current, dict) else {}
            owns = self._owns(state, claim)
            completed.append(owns)
            if not owns:
                return state
            state.update({"status": "completed", "completed_at": now.isoformat(), "expires_at": None})
            return state

        self._storage_getter().update_key_value(self._key(claim.kind), update)
        return bool(completed and completed[0])

    def renew(self, claim: SchedulerOccurrenceClaim) -> bool:
        """Extend a live claim only while this owner still holds it."""
        now = _aware(self._now())
        renewed: list[bool] = []

        def update(current: Any) -> Any:
            state = dict(current) if isinstance(current, dict) else {}
            owns = self._owns(state, claim)
            renewed.append(owns)
            if owns:
                state["expires_at"] = (
                    now + timedelta(seconds=_CLAIM_TTL_SECONDS)
                ).isoformat()
            return state

        self._storage_getter().update_key_value(self._key(claim.kind), update)
        return bool(renewed and renewed[0])

    def release(self, claim: SchedulerOccurrenceClaim) -> bool:
        now = _aware(self._now())
        released: list[bool] = []

        def update(current: Any) -> Any:
            state = dict(current) if isinstance(current, dict) else {}
            owns = self._owns(state, claim)
            released.append(owns)
            if not owns:
                return state
            state.update({"status": "released", "released_at": now.isoformat(), "expires_at": None})
            return state

        self._storage_getter().update_key_value(self._key(claim.kind), update)
        return bool(released and released[0])

    @staticmethod
    def _key(kind: str) -> str:
        return f"{_KEY_PREFIX}:{kind}"

    @staticmethod
    def _owns(state: dict[str, Any], claim: SchedulerOccurrenceClaim) -> bool:
        return (
            state.get("token") == claim.token
            and state.get("owner_id") == claim.owner_id
            and state.get("status") == "claimed"
        )

    @staticmethod
    def _token(settings: dict[str, Any], scheduled_for: datetime) -> str:
        mode = str(settings.get("mode") or "interval")
        if mode == "fixed":
            return f"fixed:{scheduled_for.replace(second=0, microsecond=0).isoformat()}"
        try:
            interval_minutes = max(1, int(settings.get("interval_minutes") or 60))
        except (TypeError, ValueError):
            interval_minutes = 60
        interval_seconds = interval_minutes * 60
        bucket = int(scheduled_for.timestamp()) // interval_seconds
        return f"interval:{interval_minutes}:{bucket}"


class SchedulerOccurrenceLease:
    """Keep one occurrence claim alive until its real worker outcome is known."""

    def __init__(
        self,
        coordinator: SchedulerOccurrenceCoordinator,
        claim: SchedulerOccurrenceClaim,
        *,
        on_lost: Callable[[], None],
        interval_seconds: float = _RENEW_INTERVAL_SECONDS,
    ) -> None:
        self._coordinator = coordinator
        self._claim = claim
        self._on_lost = on_lost
        self._interval_seconds = max(0.01, float(interval_seconds))
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._finished = False
        self._lost = False
        self._started = False
        self._thread = threading.Thread(
            target=self._renew_until_stopped,
            name=f"scheduler-occurrence-{claim.kind}",
            daemon=True,
        )

    def start(self) -> None:
        try:
            start_owned_thread(self._thread, context="scheduler occurrence renewal")
        except BaseException:
            # Preserve join/stop ownership if an asynchronous signal arrived
            # after the native renewal thread had already been created.
            self._started = thread_has_started(self._thread)
            raise
        else:
            self._started = True

    def finish(self, succeeded: bool) -> bool:
        """Stop renewal and persist the terminal outcome exactly once."""
        with self._lock:
            if self._finished:
                return False
            self._finished = True
            lost = self._lost
        self._stop.set()
        if self._thread is not threading.current_thread() and not self.wait(1.0):
            raise RuntimeError("Rinnovo occurrence ancora attivo")
        if lost:
            return False
        if succeeded:
            return self._coordinator.complete(self._claim)
        return self._coordinator.release(self._claim)

    def stop_renewing(self, timeout_seconds: float | None = 1.0) -> bool:
        """Stop the heartbeat without making a still-running worker retryable."""
        self._stop.set()
        return self.wait(timeout_seconds)

    def wait(self, timeout_seconds: float | None = None) -> bool:
        if not self._started:
            return True
        return join_owned_thread(self._thread, timeout_seconds)

    def _renew_until_stopped(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                renewed = self._coordinator.renew(self._claim)
            except BaseException:
                renewed = False
            if renewed:
                continue
            with self._lock:
                if self._finished:
                    return
                self._lost = True
            try:
                self._on_lost()
            except BaseException as exc:
                log_lifecycle_exception_safely(
                    logger, "Fencing occurrence scheduler non riuscito: %s", exc
                )
            return


__all__ = [
    "SchedulerOccurrenceClaim",
    "SchedulerOccurrenceCoordinator",
    "SchedulerOccurrenceLease",
]
