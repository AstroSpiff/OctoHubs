"""Compatibility redirects for retired Emby UI pages."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse

router = APIRouter()

_get_current_user_optional: Optional[Callable[[Request], Optional[Any]]] = None


def init_emby_ui_routes(
    get_current_user_optional: Callable[[Request], Optional[Any]],
) -> None:
    global _get_current_user_optional
    _get_current_user_optional = get_current_user_optional


def _get_current_user_optional_dep(request: Request) -> Optional[Any]:
    if _get_current_user_optional is None:
        raise RuntimeError("Emby UI routes not initialized: get_current_user_optional missing")
    return _get_current_user_optional(request)


@router.get("/emby", include_in_schema=False)
async def view_emby_dashboard(
    request: Request,
    user=Depends(_get_current_user_optional_dep),
):
    if not user:
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/app/emby-live", status_code=303)
