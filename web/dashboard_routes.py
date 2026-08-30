"""Compatibility redirects for the retired dashboard URLs."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse


router = APIRouter()

_get_current_user_id: Optional[Callable[[Request], Optional[int]]] = None
_has_users: Optional[Callable[[], bool]] = None


def init_dashboard_routes(
    get_current_user_id: Callable[[Request], Optional[int]],
    has_users: Callable[[], bool],
) -> None:
    """Inject only the authentication helpers required by legacy redirects."""
    global _get_current_user_id, _has_users
    _get_current_user_id = get_current_user_id
    _has_users = has_users


def _get_current_user_id_dep(request: Request) -> Optional[int]:
    if _get_current_user_id is None:
        raise RuntimeError("Dashboard compatibility routes not initialized: current user helper missing")
    return _get_current_user_id(request)


def _has_users_dep() -> bool:
    if _has_users is None:
        raise RuntimeError("Dashboard compatibility routes not initialized: has-users helper missing")
    return _has_users()


def _login_or_setup_redirect(request: Request) -> RedirectResponse:
    if not _has_users_dep():
        return RedirectResponse(url="/setup", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


def _research_redirect(request: Request) -> RedirectResponse:
    query = str(getattr(getattr(request, "url", None), "query", "") or "")
    target = "/app/research"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(url=target, status_code=303)


@router.get("/", include_in_schema=False)
async def dashboard_root(request: Request):
    """Keep the historical root entry point and open the default React workspace."""
    if not _get_current_user_id_dep(request):
        return _login_or_setup_redirect(request)
    return RedirectResponse(url="/app/emby-live", status_code=303)


@router.get("/dashboard", include_in_schema=False)
async def dashboard_alias(request: Request):
    """Redirect historic bookmarks to the single React research experience."""
    if not _get_current_user_id_dep(request):
        return _login_or_setup_redirect(request)
    return _research_redirect(request)
