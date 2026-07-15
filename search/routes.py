"""FastAPI routes for search, TMDB, and torrent actions."""

import io
import os
import zipfile

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from core.utils import json_error
from search.manager import (
    _download_torrent_file,
    _build_manual_search_snapshot,
    _build_send_torrent_batch_snapshot,
    _build_send_torrent_snapshot,
    _build_tmdb_check_availability_snapshot,
    _build_tmdb_search_snapshot,
    _build_tmdb_tv_details_snapshot,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None


def init_search_routes(
    require_auth: Callable[[Request], Any],
    ensure_db_backend: Callable[[], Any],
) -> None:
    global _require_auth, _ensure_db_backend
    _require_auth = require_auth
    _ensure_db_backend = ensure_db_backend


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Search routes not initialized: require_auth missing")
    return _require_auth(request)


def _ensure_db_backend_dep():
    if _ensure_db_backend is None:
        raise RuntimeError("Search routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _error_response(message: str, status_code: int = 400, **extra) -> JSONResponse:
    data, code = json_error(message, status_code, **extra)
    return JSONResponse(data, status_code=code)


@router.get("/api/tmdb/search")
async def tmdb_search(request: Request):
    _require_auth_dep(request)
    query = request.query_params.get("query")
    page = int(request.query_params.get("page", 1))
    payload, status_code = _build_tmdb_search_snapshot(query, page=page)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/tmdb/tv/{tv_id}")
async def tmdb_tv_details(tv_id: int, request: Request):
    _require_auth_dep(request)
    payload, status_code = _build_tmdb_tv_details_snapshot(tv_id)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/tmdb/check-availability")
async def tmdb_check_availability(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    data, status_code = _build_tmdb_check_availability_snapshot(payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/search/stream")
async def start_search_stream(request: Request):
    """
    Avvia una ricerca streaming via WebSocket.

    Returns:
        {"session_id": "uuid", "websocket_url": "/ws/search/uuid"}
    """
    _require_auth_dep(request)

    import uuid
    session_id = str(uuid.uuid4())

    from search.state import _active_search_sessions
    _active_search_sessions[session_id] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }

    return JSONResponse({
        "success": True,
        "session_id": session_id,
        "websocket_url": f"/ws/search/{session_id}",
    }, status_code=200)


@router.post("/api/search/manual")
async def manual_search(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    form_payload = {}
    try:
        form = await request.form()
    except Exception:
        form = None
    if form:
        def get_str(key: str, default: str = "") -> str:
            val = form.get(key)
            if val is None:
                return default
            if isinstance(val, str):
                return val
            return default

        query_val = get_str("query")
        form_payload["query"] = query_val.strip() if query_val else ""
        form_payload["media_type"] = get_str("media_type") or get_str("tmdb_type")
        form_payload["indexers"] = form.getlist("indexer")
        form_payload["use_jellyseerr_logic"] = bool(get_str("use_jellyseerr_logic") or get_str("use_jellyseerr_directives"))
        form_payload["use_custom_rules"] = bool(get_str("use_custom_rules"))
        form_payload["tmdb_id"] = get_str("tmdb_id")
        seasons = []
        for entry in form.getlist("seasons"):
            try:
                if isinstance(entry, str):
                    seasons.append(int(entry))
            except (TypeError, ValueError):
                continue
        if seasons:
            form_payload["seasons"] = seasons
        if form_payload.get("use_custom_rules"):
            custom_rules = {}
            include_filter_val = get_str("include_filter")
            exclude_filter_val = get_str("exclude_filter")
            include_filter = include_filter_val.strip() if include_filter_val else ""
            exclude_filter = exclude_filter_val.strip() if exclude_filter_val else ""
            if include_filter:
                custom_rules["include_filter"] = include_filter
            if exclude_filter:
                custom_rules["exclude_filter"] = exclude_filter
            min_size = get_str("min_size_gb")
            max_size = get_str("max_size_gb")
            if min_size not in (None, ""):
                try:
                    custom_rules["min_size_gb"] = float(min_size)
                except ValueError:
                    pass
            if max_size not in (None, ""):
                try:
                    custom_rules["max_size_gb"] = float(max_size)
                except ValueError:
                    pass
            quality = get_str("quality")
            audio_language = get_str("audio_language")
            edition = get_str("edition")
            season_value = get_str("season")
            episode_value = get_str("episode")
            if quality:
                custom_rules["quality"] = quality
            if audio_language:
                custom_rules["audio_language"] = audio_language
            if edition:
                custom_rules["edition"] = edition
            if season_value not in (None, ""):
                try:
                    custom_rules["season"] = int(season_value)
                except ValueError:
                    pass
            if episode_value not in (None, ""):
                try:
                    custom_rules["episode"] = int(episode_value)
                except ValueError:
                    pass
            if custom_rules:
                form_payload["custom_rules"] = custom_rules

    data, status_code = _build_manual_search_snapshot(payload, form_payload)
    return JSONResponse(data, status_code=status_code)


@router.post("/api/torrent/zip")
async def torrent_zip_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    links = payload.get("links") if isinstance(payload, dict) else None
    if not isinstance(links, list) or not links:
        return _error_response("Lista link mancante", 400)

    zip_buffer = io.BytesIO()
    added = 0
    errors = []
    used_names = set()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for link in links:
            if not isinstance(link, str) or not link:
                errors.append({"link": link, "error": "Link non valido"})
                continue
            content, filename, error = _download_torrent_file(link)
            if error:
                errors.append({"link": link, "error": error})
                continue
            if not content or not filename:
                errors.append({"link": link, "error": "Download torrent non valido"})
                continue
            base, ext = os.path.splitext(filename)
            candidate = filename
            counter = 1
            while candidate in used_names:
                candidate = f"{base}_{counter}{ext or '.torrent'}"
                counter += 1
            used_names.add(candidate)
            zf.writestr(candidate, content)
            added += 1

    if added == 0:
        message = "Nessun torrent disponibile per il download"
        if errors:
            message = f"{message}. Errori: {errors[0].get('error')}"
        return _error_response(message, 400, errors=errors[:5])

    zip_buffer.seek(0)
    headers = {
        "Content-Disposition": "attachment; filename=\"torrents.zip\"",
    }
    return StreamingResponse(zip_buffer, media_type="application/zip", headers=headers)


@router.get("/api/search/manual/history")
async def get_manual_search_history(request: Request):
    _require_auth_dep(request)
    try:
        backend = _ensure_db_backend_dep()
        searches = backend.load_manual_searches(limit=50)

        return JSONResponse({
            "success": True,
            "searches": searches,
        }, status_code=200)
    except Exception as exc:
        print(f"[API] Errore recupero storico: {exc}")
        return JSONResponse({
            "success": False,
            "message": f"Errore: {str(exc)}",
        }, status_code=500)


@router.delete("/api/search/manual/history/{search_id}")
async def delete_manual_search(request: Request, search_id: int):
    _require_auth_dep(request)

    try:
        backend = _ensure_db_backend_dep()
        backend.delete_manual_search(search_id)

        return JSONResponse({
            "success": True,
            "message": "Ricerca eliminata con successo",
        }, status_code=200)
    except Exception as exc:
        print(f"[API] Errore eliminazione ricerca: {exc}")
        return JSONResponse({
            "success": False,
            "message": f"Errore: {str(exc)}",
        }, status_code=500)


@router.get("/api/torrent/proxy")
async def torrent_proxy_api(request: Request, url: str = ""):
    _require_auth_dep(request)
    content, filename, error = _download_torrent_file(url)
    if error:
        return _error_response(error, 502)
    if not content or not filename:
        return _error_response("Download torrent non valido", 502)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
    }
    return Response(content, media_type="application/x-bittorrent", headers=headers)


@router.post("/api/torrent/proxy")
async def torrent_proxy_post_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    url = str(payload.get("url") or "") if isinstance(payload, dict) else ""
    content, filename, error = _download_torrent_file(url)
    if error:
        return _error_response(error, 502)
    if not content or not filename:
        return _error_response("Download torrent non valido", 502)

    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
    }
    return Response(content, media_type="application/x-bittorrent", headers=headers)


@router.post("/send-torrent")
async def send_torrent(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500,
        )


@router.post("/send-torrent/batch")
async def send_torrent_batch(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent batch: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_batch_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent batch: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500,
        )


@router.post("/api/send-torrent")
async def send_torrent_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500,
        )


@router.post("/api/send-torrent/batch")
async def send_torrent_batch_api(request: Request):
    _require_auth_dep(request)
    try:
        payload = await request.json()
    except Exception as exc:
        print(f"   -> [API] Errore parsing JSON payload send-torrent batch: {exc}")
        payload = {}

    try:
        data, status_code = _build_send_torrent_batch_snapshot(payload)
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        print(f"   -> [API] [ERRORE] Eccezione non gestita in send-torrent batch: {type(exc).__name__} - {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"success": False, "message": f"Errore interno: {str(exc)}"},
            status_code=500,
        )
