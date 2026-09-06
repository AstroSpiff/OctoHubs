"""Streaming search execution for WebSocket clients."""

from __future__ import annotations

import logging
from typing import Any

from core.log_sanitization import (
    format_exception_for_log,
    sanitize_diagnostic_text,
    sanitize_download_reference_for_log,
    sanitize_url_for_log,
)
from core.safe_output import safe_print as print
from search.query_safety import search_query_for_log


logger = logging.getLogger(__name__)


def stream_result_reference_log_lines(first: dict[str, Any]) -> tuple[str, str, str]:
    """Return useful first-result diagnostics without reusable download secrets."""
    return (
        f"         magnet: {sanitize_download_reference_for_log(first.get('magnet'))}",
        f"         torrent: {sanitize_download_reference_for_log(first.get('torrent'))}",
        f"         web: {sanitize_url_for_log(first.get('web'))}",
    )


def _build_provider_search_tasks(
    query_variants: Any,
    search_types: list[str],
    selected_indexers: Any,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    from emby_runtime.api_clients import search_jackett, search_prowlarr
    from search.indexers import _jackett_configured, _prowlarr_configured
    from search.stream_limits import (
        MAX_SEARCH_QUERY_LENGTH,
        MAX_SEARCH_TASKS,
        SearchWorkloadLimitError,
    )

    tasks: list[dict[str, Any]] = []
    providers = (
        ("prowlarr", search_prowlarr, _prowlarr_configured),
        ("jackett", search_jackett, _jackett_configured),
    )
    for query_variant in query_variants:
        query = str(query_variant or "").strip()
        if not query:
            continue
        if len(query) > MAX_SEARCH_QUERY_LENGTH:
            raise SearchWorkloadLimitError(
                f"Le query non possono superare {MAX_SEARCH_QUERY_LENGTH} caratteri"
            )
        for media_type in search_types:
            for indexer, search_func, is_configured in providers:
                if indexer not in selected_indexers or not is_configured(config):
                    continue
                if len(tasks) >= MAX_SEARCH_TASKS:
                    raise SearchWorkloadLimitError(
                        f"La ricerca supera il limite di {MAX_SEARCH_TASKS} combinazioni"
                    )
                tasks.append(
                    {
                        "indexer": indexer,
                        "query": query,
                        "media_type": media_type,
                        "func": search_func,
                    }
                )
    return tasks


async def search_streaming_parallel(
    query_variants,
    search_types,
    selected_indexers,
    config,
    websocket,
    session_id,
    owner_id,
    use_jellyseerr_logic=False,
    use_custom_rules=False,
    tmdb_id=None,
    custom_rules=None,
    seasons=None,
):
    """
    Esegue ricerche completamente parallelizzate con streaming dei risultati via WebSocket.

    Ogni combinazione (query_variant × search_type × indexer) viene eseguita in parallelo.
    I risultati vengono inviati al client WebSocket appena disponibili.

    Args:
        query_variants: Lista di varianti di query (es. ["Citadel S01", "Citadel 1x", ...])
        search_types: Lista di media types (es. ["tv"] o ["movie", "tv"])
        selected_indexers: Set di indexer attivi (es. {"prowlarr", "jackett"})
        config: Configurazione applicazione
        websocket: Connessione WebSocket per inviare risultati in tempo reale
        session_id: ID univoco della sessione di ricerca
        use_jellyseerr_logic: Se True, applica le logiche Jellyseerr (filtri, regole personalizzate)
        use_custom_rules: Se True, applica le regole custom fornite
        tmdb_id: ID TMDB per recuperare informazioni aggiuntive
        custom_rules: Regole personalizzate da applicare

    Returns:
        dict: Statistiche finali della ricerca
    """
    import time
    import copy
    import asyncio
    from datetime import datetime, timezone
    from starlette.websockets import WebSocketState

    from core.async_lifecycle import cancel_and_drain_tasks
    from core.scanner import build_search_queries, extract_title_and_year, gather_title_candidates, sanitize_title
    from core.utils import _normalize_media_type, get_nested, validate_jellyseerr_config
    from emby_runtime.api_clients import (
        _extract_tmdb_id,
        fetch_media_info,
        fetch_request_details,
        get_jellyseerr_requests,
    )
    from search.library_index import _load_emby_library_title_index
    from search.provider_outcomes import (
        MAX_AGGREGATED_SEARCH_RESULTS,
    provider_results_truncated,
    validate_provider_results,
)
    from search.rules import _compose_request_search_rules, _get_request_rule
    from search.outbound_execution import create_search_semaphore, run_outbound_search
    from search.stream_limits import (
        SearchClientDisconnected,
    )
    from core.config_manager import _ensure_db_backend
    from search.seasons import extract_request_seasons, get_episode_count_for_season, get_pending_episode_numbers
    from core.scanner import filter_results
    from core.search_normalizer import build_dedupe_key
    from search.utils import merge_duplicate_results, sort_results
    from search.download_references import protect_download_references
    from search.customization import (
        apply_custom_search_rules,
        build_independent_query_variants,
        normalize_seasons,
    )

    # Helper per inviare messaggi WebSocket solo se ancora connesso
    async def safe_send_json(data):
        """Invia JSON via WebSocket solo se la connessione è ancora aperta."""
        try:
            # Verifica se il WebSocket è ancora aperto
            if websocket.client_state == WebSocketState.CONNECTED:
                from core.websocket_io import send_json_bounded

                await send_json_bounded(websocket, data)
                return True
            return False
        except Exception:
            # Connessione chiusa o errore - silenzioso
            return False

    async def send_json_or_disconnect(data):
        if not await safe_send_json(data):
            raise SearchClientDisconnected("Client WebSocket disconnesso")

    start_time = time.time()
    total_results = 0
    completed_queries = 0
    total_queries = 0
    seen_results = set()  # Deduplica globale
    all_results = []  # Lista di tutti i risultati per salvataggio finale
    query_attempts = []  # Lista delle query provate
    successful_queries = 0
    failed_queries = 0
    global_truncated = False
    outbound_semaphore = create_search_semaphore()

    def normalize_search_types(raw_types):
        normalized = []
        for raw_type in raw_types or []:
            media_type = _normalize_media_type(raw_type)
            if media_type and media_type not in normalized:
                normalized.append(media_type)
        return normalized or ["movie", "tv"]

    search_types = normalize_search_types(search_types)
    selected_seasons = normalize_seasons(seasons)

    # Se "Usa direttive Jellyseerr" è attivo e c'è tmdb_id, genera query automatiche
    actual_query_variants = query_variants
    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    request_rule = None
    request_item = None
    request_details = None
    search_media_type = search_types[0] if len(search_types) == 1 else None

    if use_custom_rules:
        effective_config, effective_rules = apply_custom_search_rules(effective_config, custom_rules)

    generated_from_tmdb = False
    if use_jellyseerr_logic and tmdb_id and search_types:
        try:
            media_type = search_types[0]
            tmdb_id_int = int(tmdb_id) if tmdb_id else None

            if tmdb_id_int:
                print(f"[STREAM] Uso direttive Jellyseerr per tmdb_id={tmdb_id_int}, media_type={media_type}")

                # 1. Cerca request_rule da Jellyseerr se disponibile
                if validate_jellyseerr_config(config):
                    try:
                        requests_data = await asyncio.to_thread(
                            get_jellyseerr_requests,
                            config,
                            silent=True,
                        )
                        target_type = _normalize_media_type(media_type)
                        for req in requests_data or []:
                            if not isinstance(req, dict):
                                continue
                            req_type = _normalize_media_type(req.get("type") or get_nested(req, "media", "mediaType"))
                            if target_type and req_type and req_type != target_type:
                                continue
                            req_tmdb = _extract_tmdb_id(req, req.get("media"), req.get("mediaInfo"))
                            if req_tmdb and int(req_tmdb) == tmdb_id_int:
                                request_item = req
                                break
                        if isinstance(request_item, dict) and request_item.get("id"):
                            request_rule = _get_request_rule(config, request_item.get("id"))
                            if not isinstance(request_rule, dict) or not request_rule.get("enabled", True):
                                request_rule = None
                            if _normalize_media_type(media_type) == "tv":
                                details_cache = {}
                                request_details = (
                                    await asyncio.to_thread(
                                        fetch_request_details,
                                        request_item.get("id"),
                                        config,
                                        details_cache,
                                    )
                                    or request_item
                                )
                            else:
                                request_details = request_item
                            print(f"[STREAM] Trovata richiesta Jellyseerr ID {request_item.get('id')}")
                    except Exception as exc:
                        logger.error(
                            "[STREAM] Errore recupero richiesta Jellyseerr:\n%s",
                            format_exception_for_log(exc),
                        )

                # 2. Componi request_rule se disponibile
                if request_rule:
                    effective_rules = _compose_request_search_rules(effective_rules, request_rule)
                    effective_config["SEARCH_RULES"] = effective_rules

                # 3. Recupera info da TMDB e genera query complete
                cache = {}
                tmdb_payload, resolved_type = await asyncio.to_thread(
                    fetch_media_info,
                    {"tmdbId": tmdb_id_int, "mediaType": media_type},
                    effective_config,
                    cache,
                    fallback_media_type=media_type,
                )

                if tmdb_payload:
                    search_media_type = resolved_type or media_type
                    title_candidates = gather_title_candidates(tmdb_payload, search_rules=effective_rules)
                    _, year_value = extract_title_and_year(tmdb_payload)

                    if title_candidates:
                        # 4. Gestisci stagioni per TV
                        season_targets = [None]
                        if _normalize_media_type(search_media_type) == "tv":
                            if selected_seasons:
                                season_targets = selected_seasons
                            elif request_details:
                                seasons_list = extract_request_seasons(request_details, skip_available=False)
                                if seasons_list:
                                    season_targets = sorted(set(seasons_list))

                        # 5. Genera query complete usando build_search_queries
                        year_variance = (
                            request_rule.get("year_variance", 0)
                            if request_rule and _normalize_media_type(search_media_type) == "movie"
                            else 0
                        )
                        sources: list[dict] = []
                        if request_details:
                            sources.extend([entry for entry in (request_details, request_details.get("media"), request_details.get("mediaInfo")) if isinstance(entry, dict)])
                        if tmdb_payload:
                            sources.append(tmdb_payload)

                        generated_queries = []
                        for season_code in season_targets:
                            episode_count = (
                                get_episode_count_for_season(sources, season_code) if season_code is not None else None
                            )
                            pending_episodes = (
                                get_pending_episode_numbers(request_details, season_code) if request_details else None
                            )
                            generated_queries.extend(
                                build_search_queries(
                                    title_candidates,
                                    year_value,
                                    effective_config,
                                    media_type=search_media_type,
                                    season_code=season_code,
                                    episode_count=episode_count,
                                    request_terms=request_rule,
                                    pending_episodes=pending_episodes,
                                    search_rules_override=effective_rules,
                                    year_variance=year_variance,
                                )
                            )

                        if generated_queries:
                            actual_query_variants = generated_queries
                            generated_from_tmdb = True
                            print(
                                f"[STREAM] Generate {len(actual_query_variants)} query da TMDB con direttive Jellyseerr"
                            )
        except Exception as exc:
            logger.error(
                "[STREAM] Errore generazione query Jellyseerr:\n%s",
                format_exception_for_log(exc),
            )
            # Fallback alle query originali

    if not generated_from_tmdb and (use_custom_rules or selected_seasons):
        generated_queries = build_independent_query_variants(
            query_variants,
            effective_config,
            media_type=search_media_type,
            seasons=selected_seasons,
            search_rules_override=effective_rules,
        )
        if generated_queries:
            actual_query_variants = generated_queries

    search_tasks = _build_provider_search_tasks(
        actual_query_variants,
        search_types,
        selected_indexers,
        config,
    )

    total_queries = len(search_tasks)

    if total_queries == 0:
        await send_json_or_disconnect({"type": "error", "message": "Nessuna query da eseguire"})
        return {"total_results": 0, "total_duration": 0}

    # Funzione wrapper per eseguire singola ricerca e inviare risultati via WebSocket
    async def execute_and_stream(task):
        nonlocal total_results, completed_queries, seen_results
        nonlocal successful_queries, failed_queries, global_truncated

        query = task["query"]
        indexer = task["indexer"]
        media_type = task["media_type"]
        search_func = task["func"]

        query_start = time.time()

        # Notifica inizio query
        await send_json_or_disconnect(
            {
                "type": "query_started",
                "query": query,
                "indexer": indexer,
                "media_type": media_type,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Esegui ricerca (bloccante, ma in thread separato)
        try:
            results = validate_provider_results(
                await run_outbound_search(
                    outbound_semaphore,
                    search_func,
                    query,
                    media_type,
                    config,
                ),
                provider=indexer,
            )

            query_duration = time.time() - query_start
            result_count = len(results) if results else 0
            global_truncated = global_truncated or provider_results_truncated(results)

            # Usa filter_results ESATTAMENTE come fa "Ricerche & Riepilogo"
            if results:
                # Applica filter_results immediatamente (come in Ricerche & Riepilogo)
                # Usa effective_config e request_rule dallo scope esterno se disponibili
                filter_config = effective_config if "effective_config" in dir() else config
                filter_request_rules = request_rule if "request_rule" in dir() else None

                filtered_results = filter_results(
                    results,
                    filter_config,
                    media_type=media_type,
                    request_rules=filter_request_rules,
                )

                # Collect within the end-to-end budget. Membership is resolved
                # once, authoritatively, after all providers have completed.
                for result in filtered_results:
                    if not isinstance(result, dict):
                        continue

                    normalized_title = result.get("normalized_title") or sanitize_title((result.get("title") or "").lower())
                    result["normalized_title"] = normalized_title

                    result_key = build_dedupe_key(result)
                    if len(all_results) >= MAX_AGGREGATED_SEARCH_RESULTS:
                        global_truncated = True
                        continue
                    all_results.append(result)
                    if result_key not in seen_results:
                        seen_results.add(result_key)
                        total_results += 1

            # Solo una pipeline interamente validata e filtrata conta come successo.
            successful_queries += 1

            # Traccia query attempt
            query_attempts.append(
                {
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "results_found": result_count,
                    "duration": round(query_duration, 2),
                }
            )

            # Notifica completamento query
            completed_queries += 1
            await send_json_or_disconnect(
                {
                    "type": "query_completed",
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "count": result_count,
                    "duration": round(query_duration, 2),
                    "progress": round((completed_queries / total_queries) * 100, 1),
                    "timestamp": datetime.now().isoformat(),
                }
            )

        except SearchClientDisconnected:
            raise
        except Exception as exc:
            query_duration = time.time() - query_start
            completed_queries += 1
            failed_queries += 1
            error_message = (
                "Timeout durante la ricerca sull'indexer"
                if isinstance(exc, TimeoutError)
                else "Errore durante la ricerca sull'indexer"
            )

            # Traccia query fallita
            query_attempts.append(
                {
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "results_found": 0,
                    "duration": round(query_duration, 2),
                    "error": error_message,
                }
            )

            print(
                f"[STREAM] Errore ricerca {sanitize_diagnostic_text(indexer)} "
                f"per '{search_query_for_log(query)}': "
                f"{sanitize_diagnostic_text(exc)}"
            )
            await send_json_or_disconnect(
                {
                    "type": "error",
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "error": error_message,
                    "duration": round(query_duration, 2),
                    "timestamp": datetime.now().isoformat(),
                }
            )

    # Esegui tutte le ricerche in parallelo con asyncio.gather
    running_tasks = [asyncio.create_task(execute_and_stream(task)) for task in search_tasks]
    fanout = asyncio.gather(*running_tasks)
    try:
        # Do not let cancellation of this coordinator propagate through gather.
        # The canonical drain below cancels every child exactly once and shields
        # their cleanup from repeated cancellation of the coordinator.
        await asyncio.shield(fanout)
    except BaseException:
        try:
            await cancel_and_drain_tasks(running_tasks)
        finally:
            # Retrieve the parallel gather outcome after its children have been
            # drained, avoiding an unobserved cancellation exception.
            if fanout.done():
                try:
                    fanout.result()
                except BaseException:
                    pass
        raise

    if successful_queries == 0:
        total_duration = time.time() - start_time
        final_message = {
            "type": "all_completed",
            "status": "error",
            "message": "Nessun indexer ha completato la ricerca",
            "total_results": 0,
            "total_queries": total_queries,
            "failed_queries": failed_queries,
            "total_duration": round(total_duration, 2),
            "timestamp": datetime.now().isoformat(),
            "filters_applied": True,
            "truncated": False,
            "history_saved": False,
        }
        await send_json_or_disconnect(final_message)
        return final_message

    # Invia messaggio di completamento finale
    total_duration = time.time() - start_time

    # I risultati sono già stati filtrati da filter_results in execute_and_stream
    # Questo era il vecchio approccio dove si filtrava DOPO aver raccolto tutto
    # Ora filtriamo IMMEDIATAMENTE, esattamente come fa "Ricerche & Riepilogo"
    filters_applied = True  # I filtri sono stati applicati in execute_and_stream

    print(f"[STREAM] Risultati già filtrati durante lo streaming: {len(all_results)} totali")

    # Ordiniamo prima di raggruppare, così la fonte principale rispetta le
    # stesse regole delle ricerche automatiche e le altre restano disponibili.
    search_rules = effective_config.get("SEARCH_RULES", {})
    media_type_for_sort = search_types[0] if len(search_types) == 1 else None
    def sort_and_merge_results():
        sorted_results = sort_results(
            all_results,
            search_rules,
            media_type=media_type_for_sort,
        )
        return merge_duplicate_results(sorted_results)

    all_results = await asyncio.to_thread(sort_and_merge_results)
    all_results = all_results[:MAX_AGGREGATED_SEARCH_RESULTS]
    print(f"[STREAM] Dopo merge duplicati: {len(all_results)} risultati unici")

    # Debug: stampa il primo risultato dopo merge
    if all_results:
        first = all_results[0]
        print("      -> [DEBUG STREAM] Primo risultato DOPO merge_duplicate_results:")
        for diagnostic in stream_result_reference_log_lines(first):
            print(diagnostic)

    # Aggiorna il conteggio dopo merge
    total_results = len(all_results)

    normalized_titles = {
        str(result.get("normalized_title") or "")
        for result in all_results
        if isinstance(result, dict) and result.get("normalized_title")
    }
    try:
        library_index = await asyncio.to_thread(
            _load_emby_library_title_index,
            normalized_titles,
        )
    except Exception as exc:
        logger.error(
            "[STREAM] Verifica libreria non disponibile:\n%s",
            format_exception_for_log(exc),
        )
        total_duration = time.time() - start_time
        final_message = {
            "type": "all_completed",
            "status": "error",
            "message": "Impossibile verificare la presenza nella libreria Emby",
            "total_results": 0,
            "total_queries": total_queries,
            "failed_queries": failed_queries,
            "total_duration": round(total_duration, 2),
            "timestamp": datetime.now().isoformat(),
            "filters_applied": True,
            "truncated": global_truncated,
            "history_saved": False,
        }
        await send_json_or_disconnect(final_message)
        return final_message

    for result in all_results:
        normalized_title = str(result.get("normalized_title") or "")
        result["in_library"] = normalized_title in library_index
        await send_json_or_disconnect(
            {
                "type": "result",
                "data": protect_download_references(result, int(owner_id)),
                "timestamp": datetime.now().isoformat(),
            }
        )

    # Salva ricerca nel database (stesso formato delle ricerche automatiche)
    history_saved = True
    try:
        # Estrai dati dalla prima variante di query
        original_query = query_variants[0] if query_variants else "Ricerca Manuale"
        media_type_str = search_types[0] if len(search_types) == 1 else "mixed"
        search_context = {
            "query": str(original_query),
            "media_type": "unknown" if media_type_str == "mixed" else media_type_str,
            "indexers": sorted(str(indexer) for indexer in selected_indexers),
            "seasons": selected_seasons,
        }
        if tmdb_id not in (None, ""):
            search_context["tmdb_id"] = tmdb_id
        if use_custom_rules and isinstance(custom_rules, dict):
            search_context["custom_rules"] = custom_rules

        # Crea payload compatibile con le ricerche automatiche
        search_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "search_context": search_context,
            "total_requests": 1,
            "checked_requests": 1,
            "found": 1 if total_results > 0 else 0,
            "items": [
                {
                    "request_id": session_id,
                    "title": original_query,
                    "year": None,
                    "media_type": media_type_str,
                    "season": None,
                    "queries": query_attempts,
                    "results_found": total_results,
                    "results": all_results,
                    "excluded": [],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

        def save_search() -> None:
            backend = _ensure_db_backend()
            backend.save_manual_search(search_payload)

        await asyncio.to_thread(save_search)
        print(f"[STREAM] Ricerca salvata nel database: {total_results} risultati")
    except Exception as exc:
        history_saved = False
        print(
            "[STREAM] Errore salvataggio ricerca DB: "
            f"{sanitize_diagnostic_text(exc)}"
        )

    # Se sono stati applicati filtri Jellyseerr, invia i risultati finali filtrati
    final_message = {
        "type": "all_completed",
        "status": (
            "partial"
            if failed_queries or global_truncated or not history_saved
            else "success"
        ),
        "total_results": total_results,
        "total_queries": total_queries,
        "failed_queries": failed_queries,
        "total_duration": round(total_duration, 2),
        "timestamp": datetime.now().isoformat(),
        "filters_applied": filters_applied,
        "truncated": global_truncated,
        "history_saved": history_saved,
    }
    if final_message["status"] == "partial":
        final_message["message"] = (
            "Ricerca completata parzialmente; verifica indexer, limiti e storico"
        )
    # Preserve the established terminal contract; hard caps make this
    # compatibility copy deterministic and bounded.
    final_message["filtered_results"] = protect_download_references(
        all_results,
        int(owner_id),
    )

    await send_json_or_disconnect(final_message)

    return {
        "total_results": total_results,
        "total_queries": total_queries,
        "total_duration": round(total_duration, 2),
        "status": final_message["status"],
        "failed_queries": failed_queries,
        "truncated": global_truncated,
        "history_saved": history_saved,
    }
