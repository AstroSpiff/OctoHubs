"""Private, CSP-compatible API documentation routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from web.session_auth import bearer_credentials_present


router = APIRouter(include_in_schema=False)

_get_current_user_optional: Optional[Callable[[Request], Optional[Any]]] = None
_SWAGGER_HTML = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "swagger.html"
_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def init_api_docs_routes(
    get_current_user_optional: Callable[[Request], Optional[Any]],
) -> None:
    """Inject the existing session-authentication owner."""
    global _get_current_user_optional
    _get_current_user_optional = get_current_user_optional


def _current_session_user(request: Request) -> Optional[Any]:
    if _get_current_user_optional is None:
        raise RuntimeError("API documentation routes not initialized")
    if bearer_credentials_present(request):
        raise HTTPException(
            status_code=403,
            detail="La documentazione interna richiede una sessione amministratore",
        )
    return _get_current_user_optional(request)


def _is_admin(user: Any) -> bool:
    get_role = getattr(user, "get_role", None)
    role = get_role() if callable(get_role) else getattr(user, "role", "user")
    return str(role or "").strip().lower() == "admin"


async def _session_user(request: Request) -> Optional[Any]:
    return await run_in_threadpool(_current_session_user, request)


def _require_admin(user: Optional[Any]) -> Any:
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="La documentazione interna richiede un account amministratore",
        )
    return user


def _login_redirect(request: Request) -> RedirectResponse:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(target, safe='')}",
        status_code=303,
        headers=_PRIVATE_HEADERS,
    )


@router.get("/docs")
async def api_docs_route(request: Request):
    """Serve the locally built Swagger UI to administrator sessions."""
    user = await _session_user(request)
    if user is None:
        return _login_redirect(request)
    _require_admin(user)
    if not _SWAGGER_HTML.is_file():
        raise HTTPException(
            status_code=503,
            detail="Documentazione API non compilata",
        )
    return FileResponse(_SWAGGER_HTML, headers=_PRIVATE_HEADERS)


@router.get("/redoc")
async def redoc_compatibility_route(request: Request):
    """Keep the historical documentation bookmark on the supported UI."""
    user = await _session_user(request)
    if user is None:
        return _login_redirect(request)
    _require_admin(user)
    return RedirectResponse(url="/docs", status_code=307, headers=_PRIVATE_HEADERS)


@router.get("/openapi.json")
async def private_openapi_route(request: Request):
    """Return the complete internal schema only to administrator sessions."""
    _require_admin(await _session_user(request))
    return JSONResponse(request.app.openapi(), headers=_PRIVATE_HEADERS)
