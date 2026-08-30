"""Routes that host the React frontend and expose its session contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse


router = APIRouter()

_get_current_user_optional: Optional[Callable[[Request], Optional[Any]]] = None
_get_csrf_token: Optional[Callable[[Request], str]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None

_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def init_frontend_routes(
    get_current_user_optional: Callable[[Request], Optional[Any]],
    get_csrf_token: Callable[[Request], str],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    """Inject the session helpers owned by the FastAPI application factory."""
    global _get_current_user_optional, _get_csrf_token, _validate_csrf
    _get_current_user_optional = get_current_user_optional
    _get_csrf_token = get_csrf_token
    _validate_csrf = validate_csrf


def _current_user(request: Request) -> Optional[Any]:
    if _get_current_user_optional is None:
        raise RuntimeError("Frontend routes not initialized: current user helper missing")
    return _get_current_user_optional(request)


def _csrf_token(request: Request) -> str:
    if _get_csrf_token is None:
        raise RuntimeError("Frontend routes not initialized: CSRF helper missing")
    return _get_csrf_token(request)


def _csrf_is_valid(request: Request) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Frontend routes not initialized: CSRF validator missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    return _validate_csrf(request, token)


def _personal_tab_order(user_id: int, page: str) -> list[str] | None:
    from core.auth import get_user_interface_order

    return get_user_interface_order(user_id, page)


def _tab_order_response(order: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "success": True,
            "order": [
                {"tab_key": tab_key, "position": position}
                for position, tab_key in enumerate(order)
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


def _parse_tab_order(payload: Any) -> tuple[str, list[str]]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Ordine interfaccia non valido")
    page = str(payload.get("page") or "").strip()
    raw_order = payload.get("order")
    if not page or len(page) > 80 or not isinstance(raw_order, list):
        raise HTTPException(status_code=400, detail="Ordine interfaccia non valido")
    order: list[str] = []
    seen: set[str] = set()
    for entry in raw_order[:64]:
        if not isinstance(entry, dict):
            continue
        tab_key = str(entry.get("tab_key") or "").strip()
        if not tab_key or len(tab_key) > 100 or tab_key in seen:
            continue
        seen.add(tab_key)
        order.append(tab_key)
    return page, order


def _frontend_file(path: str) -> Path | None:
    """Resolve an emitted frontend asset without allowing path traversal."""
    root = _FRONTEND_DIST.resolve()
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _frontend_index_response() -> FileResponse | HTMLResponse:
    index_file = _FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return HTMLResponse(
        "<h1>Frontend OctoHubs non compilato</h1><p>Esegui la build del frontend prima di aprire /app.</p>",
        status_code=503,
    )


@router.get("/api/ui/session")
async def frontend_session_route(request: Request):
    """Return the authenticated session data required by the SPA."""
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")

    from core.auth import get_user_interface_preferences

    role = user.get_role() if callable(getattr(user, "get_role", None)) else getattr(user, "role", "user")
    return JSONResponse(
        {
            "ok": True,
            "user": {
                "id": getattr(user, "id", None),
                "username": str(getattr(user, "username", "")),
                "email": str(getattr(user, "email", "") or ""),
                "role": str(role or "user"),
            },
            "preferences": get_user_interface_preferences(int(getattr(user, "id", 0) or 0)),
            "csrf_token": _csrf_token(request),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.put("/api/ui/preferences")
async def frontend_preferences_route(request: Request):
    """Save personal workspace presentation choices without requiring write access to data."""
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    if not _csrf_is_valid(request):
        raise HTTPException(status_code=403, detail="CSRF token non valido")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Preferenze interfaccia non valide") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Preferenze interfaccia non valide")

    from core.auth import (
        PRIMARY_NAVIGATION_MODES,
        SECONDARY_NAVIGATION_MODES,
        get_user_interface_preferences,
        save_user_interface_preferences,
    )

    current = get_user_interface_preferences(int(getattr(user, "id", 0) or 0))
    primary = payload.get("primary_navigation", current["primary_navigation"])
    secondary = payload.get("secondary_navigation", current["secondary_navigation"])
    if primary not in PRIMARY_NAVIGATION_MODES or secondary not in SECONDARY_NAVIGATION_MODES:
        raise HTTPException(status_code=422, detail="Modalita di navigazione non supportata")
    preferences = save_user_interface_preferences(
        int(getattr(user, "id", 0) or 0),
        {"primary_navigation": primary, "secondary_navigation": secondary},
    )
    if preferences is None:
        raise HTTPException(status_code=500, detail="Impossibile salvare le preferenze interfaccia")
    return JSONResponse({"success": True, "preferences": preferences}, headers={"Cache-Control": "no-store"})


@router.get("/api/ui/tab-order")
async def frontend_tab_order_get_route(request: Request):
    """Return the account-specific UI order used by the React workspace."""
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    page = str(request.query_params.get("page") or "").strip()
    if not page or len(page) > 80:
        raise HTTPException(status_code=400, detail="Pagina interfaccia mancante")
    user_id = int(getattr(user, "id", 0) or 0)
    order = _personal_tab_order(user_id, page)
    return _tab_order_response(order or [])


@router.post("/api/ui/tab-order")
async def frontend_tab_order_post_route(request: Request):
    """Save a UI-only order for the signed-in account, including read-only accounts."""
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    if not _csrf_is_valid(request):
        raise HTTPException(status_code=403, detail="CSRF token non valido")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Ordine interfaccia non valido") from exc
    page, order = _parse_tab_order(payload)
    from core.auth import save_user_interface_order

    saved = save_user_interface_order(int(getattr(user, "id", 0) or 0), page, order)
    if saved is None:
        raise HTTPException(status_code=500, detail="Impossibile salvare l'ordine interfaccia")
    return _tab_order_response(saved)


@router.get("/app", include_in_schema=False)
@router.get("/app/{path:path}", include_in_schema=False)
async def frontend_application_route(request: Request, path: str = ""):
    """Serve compiled assets and fall back to the SPA entry point for client routes."""
    if _current_user(request) is None:
        target_path = request.url.path
        if request.url.query:
            target_path = f"{target_path}?{request.url.query}"
        target = quote(target_path, safe="")
        return RedirectResponse(url=f"/login?next={target}", status_code=303)

    requested_asset = _frontend_file(path)
    if requested_asset is not None:
        cache_control = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(requested_asset, headers={"Cache-Control": cache_control})
    if Path(path).suffix:
        raise HTTPException(status_code=404, detail="Risorsa frontend non trovata")
    return _frontend_index_response()
