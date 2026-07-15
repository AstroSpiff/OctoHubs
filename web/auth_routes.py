"""FastAPI routes for authentication (login/logout)."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_templates: Optional[Jinja2Templates] = None
_flash: Optional[Callable[..., None]] = None
_get_flash_messages: Optional[Callable[[Request], list]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_get_current_user_id: Optional[Callable[[Request], Optional[int]]] = None
_set_current_user: Optional[Callable[[Request, int], None]] = None
_get_current_user: Optional[Callable[[Request], Optional[Any]]] = None


def init_auth_routes(
    templates: Jinja2Templates,
    flash: Callable[..., None],
    get_flash_messages: Callable[[Request], list],
    get_csrf_token: Callable[[Request], str],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    get_current_user_id: Callable[[Request], Optional[int]],
    set_current_user: Callable[[Request, int], None],
    get_current_user: Callable[[Request], Optional[Any]],
) -> None:
    global _templates, _flash, _get_flash_messages, _get_csrf_token, _validate_csrf
    global _get_current_user_id, _set_current_user, _get_current_user
    _templates = templates
    _flash = flash
    _get_flash_messages = get_flash_messages
    _get_csrf_token = get_csrf_token
    _validate_csrf = validate_csrf
    _get_current_user_id = get_current_user_id
    _set_current_user = set_current_user
    _get_current_user = get_current_user


def _templates_dep() -> Jinja2Templates:
    if _templates is None:
        raise RuntimeError("Auth routes not initialized: templates missing")
    return _templates


def _flash_dep(*args, **kwargs) -> None:
    if _flash is None:
        raise RuntimeError("Auth routes not initialized: flash missing")
    _flash(*args, **kwargs)


def _get_flash_messages_dep(request: Request) -> list:
    if _get_flash_messages is None:
        raise RuntimeError("Auth routes not initialized: get_flash_messages missing")
    return _get_flash_messages(request)


def _get_csrf_token_dep(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Auth routes not initialized: get_csrf_token missing")
    return _get_csrf_token(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Auth routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _get_current_user_id_dep(request: Request) -> Optional[int]:
    if _get_current_user_id is None:
        raise RuntimeError("Auth routes not initialized: get_current_user_id missing")
    return _get_current_user_id(request)


def _set_current_user_dep(request: Request, user_id: int) -> None:
    if _set_current_user is None:
        raise RuntimeError("Auth routes not initialized: set_current_user missing")
    _set_current_user(request, user_id)


def _get_current_user_dep(request: Request) -> Optional[Any]:
    if _get_current_user is None:
        raise RuntimeError("Auth routes not initialized: get_current_user missing")
    return _get_current_user(request)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page - redirect to emby page if already authenticated."""
    user_id = _get_current_user_id_dep(request)
    if user_id:
        return RedirectResponse(url="/emby", status_code=303)

    messages = _get_flash_messages_dep(request)

    def _get_flashed_messages_local(with_categories: bool = False):
        if with_categories:
            return messages
        return [msg for _category, msg in messages]

    def _csrf_token_value():
        return _get_csrf_token_dep(request)

    return _templates_dep().TemplateResponse(
        "login.html",
        {
            "request": request,
            "get_flashed_messages": _get_flashed_messages_local,
            "csrf_token": _csrf_token_value,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Login form submission handler."""
    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/login", status_code=303)

    username = username.strip()

    if not username or not password:
        _flash_dep(request, "Username e password sono obbligatori.", "error")
        return RedirectResponse(url="/login", status_code=303)

    from core.auth import get_user_by_username, log_audit_event

    user = get_user_by_username(username)

    if user is not None and bool(user.is_active) and user.check_password(password):
        request.session["permanent"] = True
        user_id: int = user.id  # type: ignore - SQLAlchemy Column[int] is int at runtime
        _set_current_user_dep(request, user_id)
        user.update_last_login()
        log_audit_event(user, "login", "success", request)
        _flash_dep(request, f"Benvenuto, {user.username}!", "success")

        next_page = request.query_params.get("next")
        if next_page and next_page.startswith("/"):
            return RedirectResponse(url=next_page, status_code=303)
        return RedirectResponse(url="/", status_code=303)

    _flash_dep(request, "Username o password non validi.", "error")
    if user:
        log_audit_event(user, "login", "failed", request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Logout handler."""
    from core.auth import log_audit_event

    user = _get_current_user_dep(request)
    if user:
        log_audit_event(user, "logout", "success", request)

    request.session.clear()
    _flash_dep(request, "Disconnessione effettuata.", "success")
    return RedirectResponse(url="/login", status_code=303)
