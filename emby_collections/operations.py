"""Operation-center integration for collection source list refreshes."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from services.background_jobs import BackgroundJobContext, start_tracked_background_job


def start_source_list_operation(
    *,
    source_key: str,
    title: str,
    fetcher: Callable[[], List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Refresh a collection source list in the background."""

    def _work(context: BackgroundJobContext) -> Dict[str, Any]:
        context.update(message=f"Caricamento {title}", progress=20, current=0, total=1)
        lists = fetcher()
        count = len(lists) if isinstance(lists, list) else 0
        context.update(
            message=f"{title}: {count} liste caricate",
            progress=90,
            current=1,
            total=1,
            details={"count": count},
        )
        return {"lists": lists or [], "count": count}

    return start_tracked_background_job(
        kind=f"collections_{source_key}_lists",
        title=f"Aggiornamento {title}",
        summary="Collezioni",
        details={"source": title, "current_step_label": "Caricamento liste"},
        total=1,
        work=_work,
        success_message=f"{title} aggiornate",
    )


def start_collection_sync_operation(
    *,
    collection_id: str,
    runner: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """Synchronize one collection to Emby in the background."""

    def _work(context: BackgroundJobContext) -> Dict[str, Any]:
        context.update(
            message="Sincronizzazione collezione verso Emby",
            progress=15,
            current=0,
            total=1,
            details={"collection_id": collection_id, "current_step_label": "Sync Emby"},
        )
        result = runner(collection_id) or {}
        collection = result.get("collection") if isinstance(result, dict) else {}
        details = result.get("details") if isinstance(result, dict) else {}
        message = (
            (collection or {}).get("last_sync_message")
            or "Sincronizzazione collezione completata"
        )
        context.update(
            message=message,
            progress=95,
            current=1,
            total=1,
            details={
                "collection_id": collection_id,
                "current_step_label": "Completamento",
                "matched": (details or {}).get("matched"),
                "candidates": (details or {}).get("candidates"),
            },
        )
        return {
            "success": True,
            "collection": collection,
            "details": details or {},
        }

    return start_tracked_background_job(
        kind="collection_sync",
        title="Sincronizzazione collezione",
        summary=collection_id,
        details={"collection_id": collection_id, "current_step_label": "Avvio"},
        total=1,
        work=_work,
        success_message="Sincronizzazione collezione completata",
    )


def start_collection_sync_all_operation(
    *,
    runner: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    """Synchronize all collections to Emby in the background."""

    def _work(context: BackgroundJobContext) -> Dict[str, Any]:
        context.update(
            message="Sincronizzazione globale collezioni verso Emby",
            progress=10,
            current=0,
            total=1,
            details={"current_step_label": "Sync Emby"},
        )
        result = runner() or {}
        summary = result.get("summary", {}) if isinstance(result, dict) else {}
        synced = int(summary.get("synced") or 0) if isinstance(summary, dict) else 0
        errors = summary.get("errors") if isinstance(summary, dict) else []
        error_count = len(errors) if isinstance(errors, list) else 0
        message = f"Sync globale completato: {synced} sincronizzate"
        if error_count:
            message += f", {error_count} errori"
        context.update(
            message=message,
            progress=95,
            current=1,
            total=1,
            details={
                "current_step_label": "Completamento",
                "synced": synced,
                "errors": error_count,
            },
        )
        return {
            "success": True,
            "summary": summary if isinstance(summary, dict) else {},
        }

    return start_tracked_background_job(
        kind="collections_sync_all",
        title="Sincronizzazione collezioni",
        summary="Collezioni",
        details={"current_step_label": "Avvio"},
        total=1,
        work=_work,
        success_message="Sincronizzazione globale collezioni completata",
    )
