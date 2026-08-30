"""Bounded, owner-aware lifecycle for streaming search sessions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable, Literal
from uuid import uuid4


SEARCH_SESSION_TTL_SECONDS = 30.0
SEARCH_SESSION_ACTIVE_TTL_SECONDS = 5 * 60.0
MAX_PENDING_SEARCH_SESSIONS_PER_USER = 3
MAX_ACTIVE_SEARCH_SESSIONS_PER_USER = 2
MAX_ACTIVE_SEARCH_SESSIONS = 8
MAX_SEARCH_SESSIONS = 128


class SearchSessionError(RuntimeError):
    """Base error for an unavailable or unauthorized search session."""


class SearchSessionLimitError(SearchSessionError):
    """Raised when a user or process-wide session quota is exhausted."""


class SearchSessionUnavailableError(SearchSessionError):
    """Raised for missing, expired, consumed, or foreign sessions."""


@dataclass(slots=True)
class SearchSession:
    owner_id: int
    created_at: float
    status: Literal["pending", "active"] = "pending"
    claimed_at: float | None = None


class SearchSessionRegistry:
    """Keep pending/active sessions bounded and make each UUID one-shot."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        pending_ttl: float = SEARCH_SESSION_TTL_SECONDS,
        active_ttl: float = SEARCH_SESSION_ACTIVE_TTL_SECONDS,
        max_pending_per_user: int = MAX_PENDING_SEARCH_SESSIONS_PER_USER,
        max_active_per_user: int = MAX_ACTIVE_SEARCH_SESSIONS_PER_USER,
        max_active: int = MAX_ACTIVE_SEARCH_SESSIONS,
        max_sessions: int = MAX_SEARCH_SESSIONS,
    ) -> None:
        self._clock = clock
        self._pending_ttl = float(pending_ttl)
        self._active_ttl = float(active_ttl)
        self._max_pending_per_user = int(max_pending_per_user)
        self._max_active_per_user = int(max_active_per_user)
        self._max_active = int(max_active)
        self._max_sessions = int(max_sessions)
        self._sessions: dict[str, SearchSession] = {}
        self._lock = RLock()

    def create(self, owner_id: int) -> str:
        owner_id = _normalize_owner_id(owner_id)
        with self._lock:
            now = self._clock()
            self._prune_expired(now)
            pending_for_owner = sum(
                session.owner_id == owner_id and session.status == "pending"
                for session in self._sessions.values()
            )
            if pending_for_owner >= self._max_pending_per_user:
                raise SearchSessionLimitError("Troppe sessioni di ricerca in attesa")
            if len(self._sessions) >= self._max_sessions:
                raise SearchSessionLimitError("Capacita globale delle ricerche esaurita")

            session_id = str(uuid4())
            self._sessions[session_id] = SearchSession(owner_id=owner_id, created_at=now)
            return session_id

    def claim(self, session_id: str, owner_id: int) -> None:
        owner_id = _normalize_owner_id(owner_id)
        with self._lock:
            now = self._clock()
            self._prune_expired(now)
            session = self._sessions.get(str(session_id or ""))
            if session is None or session.owner_id != owner_id or session.status != "pending":
                raise SearchSessionUnavailableError("Sessione di ricerca non disponibile")

            active_for_owner = sum(
                candidate.owner_id == owner_id and candidate.status == "active"
                for candidate in self._sessions.values()
            )
            if active_for_owner >= self._max_active_per_user:
                raise SearchSessionLimitError("Troppe ricerche simultanee per questo utente")
            active_total = sum(
                candidate.status == "active" for candidate in self._sessions.values()
            )
            if active_total >= self._max_active:
                raise SearchSessionLimitError("Capacita delle ricerche simultanee esaurita")

            session.status = "active"
            session.claimed_at = now

    def finish(self, session_id: str, owner_id: int) -> None:
        owner_id = _normalize_owner_id(owner_id)
        with self._lock:
            session = self._sessions.get(str(session_id or ""))
            if session is not None and session.owner_id == owner_id:
                self._sessions.pop(str(session_id), None)

    def snapshot(self) -> dict[str, SearchSession]:
        """Return a detached snapshot for diagnostics and tests."""
        with self._lock:
            self._prune_expired(self._clock())
            return {
                session_id: SearchSession(
                    owner_id=session.owner_id,
                    created_at=session.created_at,
                    status=session.status,
                    claimed_at=session.claimed_at,
                )
                for session_id, session in self._sessions.items()
            }

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _prune_expired(self, now: float) -> None:
        expired = []
        for session_id, session in self._sessions.items():
            if session.status == "pending":
                is_expired = now - session.created_at >= self._pending_ttl
            else:
                claimed_at = session.claimed_at if session.claimed_at is not None else session.created_at
                is_expired = now - claimed_at >= self._active_ttl
            if is_expired:
                expired.append(session_id)
        for session_id in expired:
            self._sessions.pop(session_id, None)


def _normalize_owner_id(owner_id: int) -> int:
    try:
        normalized = int(owner_id)
    except (TypeError, ValueError) as exc:
        raise SearchSessionUnavailableError("Identita utente non valida") from exc
    if normalized <= 0:
        raise SearchSessionUnavailableError("Identita utente non valida")
    return normalized


search_session_registry = SearchSessionRegistry()


def create_search_session(owner_id: int) -> str:
    return search_session_registry.create(owner_id)


def claim_search_session(session_id: str, owner_id: int) -> None:
    search_session_registry.claim(session_id, owner_id)


def finish_search_session(session_id: str, owner_id: int) -> None:
    search_session_registry.finish(session_id, owner_id)
