"""FastAPI routes for the deployment-managed initial setup."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_has_users: Optional[Callable[[], bool]] = None
_templates: Optional[Jinja2Templates] = None


def init_setup_routes(
    has_users: Callable[[], bool],
    templates: Jinja2Templates,
) -> None:
    global _has_users, _templates
    _has_users = has_users
    _templates = templates


def _has_users_dep() -> bool:
    if _has_users is None:
        raise RuntimeError("Setup routes not initialized: has_users missing")
    return _has_users()


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Setup routes not initialized: templates missing")
    return _templates


async def _users_exist() -> bool:
    from core.auth import AuthStorageError

    try:
        return await run_in_threadpool(_has_users_dep)
    except AuthStorageError as exc:
        raise HTTPException(status_code=503, detail="Database account non disponibile") from exc


@router.get("/setup")
async def setup_index_route(request: Request):
    """Show bootstrap instructions only until the first user exists."""
    if not await _users_exist():
        return RedirectResponse(url="/setup/user", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/setup/user")
async def setup_user_get_route(request: Request):
    """Explain how to bootstrap the first administrator outside the UI."""
    if await _users_exist():
        return RedirectResponse(url="/login", status_code=303)

    return _templates_dep().TemplateResponse(request, "setup.html", {"request": request, "step": "user"})


@router.post("/setup/user")
async def setup_user_post_route(request: Request):
    """Reject browser-based administrator creation."""
    raise HTTPException(
        status_code=403,
        detail=(
            "La creazione dell'amministratore dal browser è disabilitata. "
            "Configura ADMIN_USERNAME e ADMIN_PASSWORD_FILE nel deploy Docker."
        ),
    )


@router.get("/setup/db")
async def setup_db_get_route(request: Request):
    """Retain the legacy URL without exposing database controls."""
    if not await _users_exist():
        return RedirectResponse(url="/setup/user", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.post("/setup/db")
async def setup_db_post_route(request: Request):
    """Reject the retired browser-based database bootstrap endpoint."""
    raise HTTPException(
        status_code=410,
        detail="Il database si configura nel deployment tramite OCTOHUBS_DB_*.",
    )
