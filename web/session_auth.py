"""Session-based authentication helpers for FastAPI routes."""

from __future__ import annotations

from typing import Optional, Any

from fastapi import HTTPException, Request


def get_current_user_id(request: Request) -> Optional[int]:
    """
    Get current authenticated user ID from Starlette session.
    Returns user_id if authenticated, None otherwise.
    """
    return request.session.get("user_id")


def set_current_user(request: Request, user_id: int) -> None:
    """Set current user ID in Starlette session."""
    request.session["user_id"] = user_id


def clear_current_user(request: Request) -> None:
    """Clear current user from Starlette session (logout)."""
    request.session.pop("user_id", None)


def get_current_user(request: Request) -> Optional[Any]:
    """
    Get current authenticated User object from session.
    Returns User object if authenticated, None otherwise.
    """
    from core.auth import get_user_by_id

    user_id = get_current_user_id(request)
    if not user_id:
        return None

    return get_user_by_id(user_id)


def require_auth(request: Request) -> int:
    """
    FastAPI dependency to require authentication.
    Raises 401 if not authenticated.
    Returns user_id if authenticated.
    """
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def get_current_user_optional(request: Request) -> Optional[Any]:
    """Dependency: Get current user or None."""
    return get_current_user(request)


def require_user(request: Request) -> Any:
    """Dependency: Require authenticated user."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
