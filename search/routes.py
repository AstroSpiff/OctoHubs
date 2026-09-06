"""FastAPI routes for search, TMDB, and torrent actions."""

import io
import logging
import os
import zipfile

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from core.storage import StorageError
from core.log_sanitization import format_exception_for_log
from core.utils import json_error
from search.availability import is_request_available, normalize_request_availability
from search.download_references import (
    DownloadReferenceError,
    REFERENCE_PREFIX,
    protect_download_references,
    resolve_download_reference,
)
from search.manager import (
    _download_torrent_file,
    _torrent_content_disposition,
    _build_manual_search_snapshot,
    _build_send_torrent_batch_snapshot,
    _build_send_torrent_snapshot,
    _build_tmdb_check_availability_snapshot,
    _build_tmdb_search_snapshot,
    _build_tmdb_tv_details_snapshot,
)
from services.scan_result_cleanup import clean_scan_results_payload
from web.research_api_models import (
    LinkBatchPayload,
    MagnetReferencesPayload,
    MagnetReferencesResponse,
    ManualSearchHistoryResponse,
    ManualSearchPayload,
    ResearchActionResponse,
    ResearchAvailabilityResponse,
    ResearchManualSearchResponse,
    ResearchStreamResponse,
    ResearchTmdbDetailsResponse,
    ResearchTmdbSearchResponse,
    ScanResultCleanupPayload,
    TmdbAvailabilityPayload,
    TorrentLinkPayload,
    TorrentProxyPayload,
)
from web.openapi_requests import no_request_body

router = APIRouter()

_MAX_TORRENT_ARCHIVE_BYTES = 50 * 1024 * 1024
logger = logging.getLogger(__name__)

_require_auth: Optional[Callable[[Request], Any]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None


def init_search_routes(
    require_auth: Callable[[Request], Any],
    ensure_db_backend: Callable[[], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
) -> None:
    global _require_auth, _ensure_db_backend, _validate_csrf
    _require_auth = require_auth
    _ensure_db_backend = ensure_db_backend
    _validate_csrf = validate_csrf


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Search routes not initialized: require_auth missing")
    return _require_auth(request)


def _ensure_db_backend_dep():
    if _ensure_db_backend is None:
        raise RuntimeError("Search routes not initialized: ensure_db_backend missing")
    return _ensure_db_backend()


def _validate_csrf_dep(request: Request) -> None:
    if _validate_csrf is None:
        raise RuntimeError("Search routes not initialized: validate_csrf missing")
    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not _validate_csrf(request, token):
        raise HTTPException(status_code=403, detail="CSRF token non valido")


def _error_response(message: str, status_code: int = 400, **extra) -> JSONResponse:
    data, code = json_error(message, status_code, **extra)
    return JSONResponse(data, status_code=code)


def _resolved_download(owner_id: int, value: str, *, expected_kind: str | None = None) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith(REFERENCE_PREFIX):
        return resolve_download_reference(owner_id, normalized, expected_kind=expected_kind)
    return normalized


def _available_request_ids_from_overview(backend: Any) -> set[str]:
    try:
        overview, _updated_at = backend.load_request_overview()
    except Exception:
        return set()
    rows = overview if isinstance(overview, list) else []
    normalized = normalize_request_availability(rows)
    return {
        str(row.get("request_id") or row.get("id"))
        for row in normalized
        if is_request_available(row)
    }


def _build_torrent_archive(
    downloads: list[tuple[Any, bytes | None, str | None, str | None]],
) -> tuple[bytes, int, list[dict[str, Any]]]:
    """Compress validated downloads away from the ASGI event loop."""
    zip_buffer = io.BytesIO()
    added = 0
    total_bytes = 0
    errors: list[dict[str, Any]] = []
    used_names: set[str] = set()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for link, content, filename, error in downloads:
            if error:
                errors.append({"link": link, "error": "Download torrent non riuscito"})
                continue
            if not content or not filename:
                errors.append({"link": link, "error": "Download torrent non valido"})
                continue
            if total_bytes + len(content) > _MAX_TORRENT_ARCHIVE_BYTES:
                errors.append({"link": link, "error": "Archivio torrent troppo grande"})
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
            total_bytes += len(content)
    return zip_buffer.getvalue(), added, errors


@router.get("/api/research/tmdb/search", response_model=ResearchTmdbSearchResponse)
async def tmdb_search(request: Request, query: str = "", page: int = 1):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_build_tmdb_search_snapshot, query, page=page)
    return JSONResponse(payload, status_code=status_code)


@router.get("/api/research/tmdb/tv/{tv_id}", response_model=ResearchTmdbDetailsResponse)
async def tmdb_tv_details(tv_id: int, request: Request):
    await run_in_threadpool(_require_auth_dep, request)
    payload, status_code = await run_in_threadpool(_build_tmdb_tv_details_snapshot, tv_id)
    return JSONResponse(payload, status_code=status_code)


@router.post("/api/research/tmdb/check-availability", response_model=ResearchAvailabilityResponse)
async def tmdb_check_availability(request: Request, payload: TmdbAvailabilityPayload):
    await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    data, status_code = await run_in_threadpool(
        _build_tmdb_check_availability_snapshot,
        payload.model_dump(),
    )
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/research/stream",
    response_model=ResearchStreamResponse,
    openapi_extra=no_request_body(),
)
async def start_search_stream(request: Request):
    """
    Avvia una ricerca streaming via WebSocket.

    Returns:
        {"session_id": "uuid", "websocket_url": "/ws/search/uuid"}
    """
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)

    from search.state import SearchSessionLimitError, create_search_session

    try:
        session_id = await run_in_threadpool(create_search_session, int(owner_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Authentication required") from None
    except SearchSessionLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    return JSONResponse({
        "success": True,
        "session_id": session_id,
        "websocket_url": f"/ws/search/{session_id}",
    }, status_code=200)


@router.post("/api/research/manual", response_model=ResearchManualSearchResponse)
async def manual_search(request: Request, payload: ManualSearchPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    data, status_code = await run_in_threadpool(
        _build_manual_search_snapshot,
        payload.model_dump(exclude_none=True),
    )
    if status_code == 200:
        data = await run_in_threadpool(protect_download_references, data, int(owner_id))
    return JSONResponse(data, status_code=status_code)


@router.post(
    "/api/research/torrents/archive",
    response_class=Response,
    responses={
        200: {
            "description": "Archivio ZIP dei torrent disponibili.",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def torrent_zip_api(request: Request, payload: LinkBatchPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    links = payload.links
    if not isinstance(links, list) or not links:
        return _error_response("Lista link mancante", 400)

    downloads: list[tuple[Any, bytes | None, str | None, str | None]] = []
    retained_bytes = 0
    for link in links:
        if not isinstance(link, str) or not link:
            downloads.append((link, None, None, "Link non valido"))
            continue
        try:
            resolved_link = await run_in_threadpool(
                _resolved_download,
                int(owner_id),
                link,
                expected_kind="torrent",
            )
        except DownloadReferenceError:
            downloads.append((link, None, None, "Riferimento non disponibile"))
            continue
        remaining_bytes = _MAX_TORRENT_ARCHIVE_BYTES - retained_bytes
        if remaining_bytes <= 0:
            downloads.append((link, None, None, "Archivio torrent troppo grande"))
            continue
        content, filename, error = await run_in_threadpool(
            _download_torrent_file,
            resolved_link,
            remaining_bytes,
        )
        if content:
            retained_bytes += len(content)
        downloads.append((link, content, filename, error))
    archive, added, errors = await run_in_threadpool(_build_torrent_archive, downloads)

    if added == 0:
        message = "Nessun torrent disponibile per il download"
        if errors:
            message = f"{message}. Errori: {errors[0].get('error')}"
        return _error_response(message, 400, errors=errors[:5])

    headers = {
        "Content-Disposition": "attachment; filename=\"torrents.zip\"",
    }
    return Response(archive, media_type="application/zip", headers=headers)


@router.get("/api/research/manual/history", response_model=ManualSearchHistoryResponse)
async def get_manual_search_history(request: Request):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    try:
        backend = await run_in_threadpool(_ensure_db_backend_dep)
        searches = await run_in_threadpool(backend.load_manual_searches, limit=50)
        searches = await run_in_threadpool(
            protect_download_references,
            searches,
            int(owner_id),
        )

        return JSONResponse({
            "success": True,
            "searches": searches,
        }, status_code=200)
    except StorageError as exc:
        logger.error("Storico ricerche non disponibile:\n%s", format_exception_for_log(exc))
        return JSONResponse({
            "success": True,
            "searches": [],
            "warning": "Storico ricerche temporaneamente non disponibile",
        }, status_code=200)
    except Exception as exc:
        logger.error("Errore recupero storico:\n%s", format_exception_for_log(exc))
        return JSONResponse({
            "success": False,
            "message": "Impossibile recuperare lo storico ricerche",
        }, status_code=500)


@router.delete("/api/research/manual/history/{search_id}", response_model=ResearchActionResponse)
async def delete_manual_search(request: Request, search_id: int):
    await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)

    try:
        backend = await run_in_threadpool(_ensure_db_backend_dep)
        await run_in_threadpool(backend.delete_manual_search, search_id)

        return JSONResponse({
            "success": True,
            "message": "Ricerca eliminata con successo",
        }, status_code=200)
    except Exception as exc:
        logger.error("Errore eliminazione ricerca:\n%s", format_exception_for_log(exc))
        return JSONResponse({
            "success": False,
            "message": "Impossibile eliminare la ricerca",
        }, status_code=500)


@router.post("/api/research/results/cleanup", response_model=ResearchActionResponse)
async def cleanup_search_results(request: Request, payload: ScanResultCleanupPayload):
    await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    data = payload.model_dump()
    mode = payload.mode

    try:
        backend = await run_in_threadpool(_ensure_db_backend_dep)
        if mode == "all" and hasattr(backend, "delete_scan_results"):
            removed = await run_in_threadpool(backend.delete_scan_results, keep_last=0)
            return JSONResponse({
                "success": True,
                "message": "Risultati azzerati",
                "removed": int(removed or 0),
                "remaining": 0,
            }, status_code=200)

        available_ids = (
            await run_in_threadpool(_available_request_ids_from_overview, backend)
            if mode == "resolved"
            else None
        )

        def transform(current):
            result = clean_scan_results_payload(
                current,
                mode=mode,
                request_id=data.get("request_id"),
                season=data.get("season"),
                available_ids=available_ids,
            )
            successor = result["payload"] if result["removed"] > 0 else None
            return successor, result

        result = await run_in_threadpool(backend.mutate_last_scan_result, transform)
        if result is None:
            return JSONResponse({
                "success": True,
                "message": "Nessun riepilogo da pulire",
                "removed": 0,
                "remaining": 0,
            }, status_code=200)

        messages = {
            "single": "Risultato rimosso",
            "resolved": "Risultati evasi rimossi",
            "all": "Risultati azzerati",
        }
        return JSONResponse({
            "success": True,
            "message": messages.get(mode, "Riepilogo aggiornato"),
            "removed": result["removed"],
            "remaining": result["remaining"],
        }, status_code=200)
    except ValueError as exc:
        return _error_response(str(exc), 400)
    except Exception as exc:
        logger.error("Errore pulizia risultati:\n%s", format_exception_for_log(exc))
        return JSONResponse({
            "success": False,
            "message": "Impossibile pulire i risultati",
        }, status_code=500)


@router.get(
    "/api/research/torrents/proxy",
    response_class=Response,
    responses={
        200: {
            "description": "File torrent scaricato dalla fonte autorizzata.",
            "content": {"application/x-bittorrent": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def torrent_proxy_api(request: Request, ref: str = ""):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    try:
        url = await run_in_threadpool(
            resolve_download_reference,
            int(owner_id),
            ref,
            expected_kind="torrent",
        )
    except DownloadReferenceError:
        return _error_response("Riferimento torrent non disponibile", 404)
    content, filename, error = await run_in_threadpool(_download_torrent_file, url)
    if error:
        return _error_response("Download torrent non riuscito", 502)
    if not content or not filename:
        return _error_response("Download torrent non valido", 502)

    headers = {
        "Content-Disposition": _torrent_content_disposition(filename),
    }
    return Response(content, media_type="application/x-bittorrent", headers=headers)


@router.post(
    "/api/research/torrents/proxy",
    response_class=Response,
    responses={
        200: {
            "description": "File torrent scaricato dalla fonte autorizzata.",
            "content": {"application/x-bittorrent": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def torrent_proxy_post_api(request: Request, payload: TorrentProxyPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    try:
        url = await run_in_threadpool(
            _resolved_download,
            int(owner_id),
            payload.reference or payload.url,
            expected_kind="torrent",
        )
    except DownloadReferenceError:
        return _error_response("Riferimento torrent non disponibile", 404)
    content, filename, error = await run_in_threadpool(_download_torrent_file, url)
    if error:
        return _error_response("Download torrent non riuscito", 502)
    if not content or not filename:
        return _error_response("Download torrent non valido", 502)

    headers = {
        "Content-Disposition": _torrent_content_disposition(filename),
    }
    return Response(content, media_type="application/x-bittorrent", headers=headers)


@router.post(
    "/api/research/torrents/magnets",
    response_model=MagnetReferencesResponse,
)
async def resolve_magnet_references_api(request: Request, payload: MagnetReferencesPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    try:
        magnets = [
            await run_in_threadpool(
                resolve_download_reference,
                int(owner_id),
                reference,
                expected_kind="magnet",
            )
            for reference in payload.references
        ]
    except DownloadReferenceError:
        return _error_response("Riferimento magnet non disponibile", 404)
    return JSONResponse({"success": True, "magnets": magnets})


@router.post("/api/research/torrents/send", response_model=ResearchActionResponse)
async def send_torrent_api(request: Request, payload: TorrentLinkPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    try:
        submitted = payload.model_dump()
        submitted["link"] = await run_in_threadpool(
            _resolved_download,
            int(owner_id),
            payload.link,
        )
        data, status_code = await run_in_threadpool(
            _build_send_torrent_snapshot,
            submitted,
        )
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        logger.error("Errore send-torrent:\n%s", format_exception_for_log(exc))
        return JSONResponse(
            {"success": False, "message": "Invio torrent non riuscito"},
            status_code=500,
        )


@router.post("/api/research/torrents/send-batch", response_model=ResearchActionResponse)
async def send_torrent_batch_api(request: Request, payload: LinkBatchPayload):
    owner_id = await run_in_threadpool(_require_auth_dep, request)
    await run_in_threadpool(_validate_csrf_dep, request)
    try:
        submitted = payload.model_dump()
        submitted["links"] = [
            await run_in_threadpool(_resolved_download, int(owner_id), link)
            for link in payload.links
        ]
        data, status_code = await run_in_threadpool(
            _build_send_torrent_batch_snapshot,
            submitted,
        )
        return JSONResponse(data, status_code=status_code)
    except Exception as exc:
        logger.error("Errore send-torrent batch:\n%s", format_exception_for_log(exc))
        return JSONResponse(
            {"success": False, "message": "Invio torrent batch non riuscito"},
            status_code=500,
        )
