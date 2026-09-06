"""Request-aware routing for the synchronous SQLAlchemy authentication session."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import threading
from typing import Any

from sqlalchemy.orm import scoped_session


@dataclass(eq=False)
class AuthRequestScope:
    """Mutable marker so inherited child contexts stop using a completed request."""

    active: bool = True


_current_scope: ContextVar[AuthRequestScope | None] = ContextVar(
    "octohubs_auth_request_scope",
    default=None,
)


def begin_auth_request_scope() -> tuple[AuthRequestScope, Token]:
    scope = AuthRequestScope()
    return scope, _current_scope.set(scope)


def end_auth_request_scope(scope: AuthRequestScope, token: Token) -> None:
    scope.active = False
    _current_scope.reset(token)


def current_auth_request_scope() -> AuthRequestScope | None:
    scope = _current_scope.get()
    return scope if scope is not None and scope.active else None


class RequestAwareSessionRegistry:
    """Use one Session per ASGI request and thread-local Sessions elsewhere."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory
        self._thread_sessions = scoped_session(session_factory)
        self._request_sessions: dict[AuthRequestScope, Any] = {}
        self._request_sessions_lock = threading.Lock()

    def __call__(self, **kwargs: Any) -> Any:
        scope = current_auth_request_scope()
        if scope is None:
            return self._thread_sessions(**kwargs)

        with self._request_sessions_lock:
            session = self._request_sessions.get(scope)
            if session is not None:
                if kwargs:
                    raise TypeError("Session already present; no new arguments may be specified")
                return session
            session = self.session_factory(**kwargs)
            self._request_sessions[scope] = session
            return session

    def remove(self) -> None:
        scope = current_auth_request_scope()
        if scope is None:
            self._thread_sessions.remove()
            return

        with self._request_sessions_lock:
            session = self._request_sessions.pop(scope, None)
        if session is None:
            return
        session.close()

    def close_all(self) -> None:
        """Close thread-local and request-bound sessions at process shutdown."""
        self._thread_sessions.remove()
        with self._request_sessions_lock:
            sessions = tuple(self._request_sessions.values())
            self._request_sessions.clear()
        for session in sessions:
            session.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self(), name)
