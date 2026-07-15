"""Streaming search execution for WebSocket clients."""

from __future__ import annotations



async def search_streaming_parallel(
    query_variants,
    search_types,
    selected_indexers,
    config,
    websocket,
    session_id,
    use_jellyseerr_logic=False,
    use_custom_rules=False,
    tmdb_id=None,
    custom_rules=None,
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

    from core.config import DEFAULT_CONFIG
    from core.scanner import build_search_queries, extract_title_and_year, gather_title_candidates, sanitize_title
    from core.utils import _normalize_media_type, get_nested, validate_jellyseerr_config
    from emby_runtime.api_clients import (
        _extract_tmdb_id,
        fetch_media_info,
        fetch_request_details,
        get_jellyseerr_requests,
        search_jackett,
        search_prowlarr,
    )
    from search.indexers import _jackett_configured, _prowlarr_configured
    from search.library_index import _load_emby_library_title_index
    from search.rules import _compose_request_search_rules, _get_request_rule
    from core.config_manager import _ensure_db_backend
    from search.seasons import extract_request_seasons, get_episode_count_for_season, get_pending_episode_numbers
    from core.scanner import filter_results
    from core.search_normalizer import build_dedupe_key
    from search.utils import merge_duplicate_results, sort_results

    # Helper per inviare messaggi WebSocket solo se ancora connesso
    async def safe_send_json(data):
        """Invia JSON via WebSocket solo se la connessione è ancora aperta."""
        try:
            # Verifica se il WebSocket è ancora aperto
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(data)
                return True
            return False
        except Exception:
            # Connessione chiusa o errore - silenzioso
            return False

    start_time = time.time()
    total_results = 0
    completed_queries = 0
    total_queries = 0
    seen_results = set()  # Deduplica globale
    all_results = []  # Lista di tutti i risultati per salvataggio finale
    query_attempts = []  # Lista delle query provate

    # Se "Usa direttive Jellyseerr" è attivo e c'è tmdb_id, genera query automatiche
    actual_query_variants = query_variants
    effective_config = copy.deepcopy(config)
    effective_rules = copy.deepcopy(config.get("SEARCH_RULES", {}))
    request_rule = None
    request_item = None
    request_details = None
    search_media_type = search_types[0] if search_types else "movie"

    if use_custom_rules and isinstance(custom_rules, dict):
        overrides = {}
        if isinstance(custom_rules.get("SEARCH_RULES"), dict):
            overrides.update(custom_rules.get("SEARCH_RULES") or {})
        if isinstance(custom_rules.get("search_rules"), dict):
            overrides.update(custom_rules.get("search_rules") or {})
        for key, value in custom_rules.items():
            if key in {
                "SEARCH_RULES",
                "search_rules",
                "TARGET_LANGUAGES",
                "target_languages",
                "EXCLUDE_TAGS",
                "exclude_tags",
            }:
                continue
            if key in effective_rules or key in DEFAULT_CONFIG.get("SEARCH_RULES", {}):
                overrides[key] = value
        if overrides:
            effective_rules.update(overrides)
        effective_config["SEARCH_RULES"] = effective_rules

        if "TARGET_LANGUAGES" in custom_rules or "target_languages" in custom_rules:
            target_langs = custom_rules.get("TARGET_LANGUAGES")
            if target_langs is None:
                target_langs = custom_rules.get("target_languages")
            if target_langs is not None:
                effective_config["TARGET_LANGUAGES"] = target_langs
        if "EXCLUDE_TAGS" in custom_rules or "exclude_tags" in custom_rules:
            exclude_tags = custom_rules.get("EXCLUDE_TAGS")
            if exclude_tags is None:
                exclude_tags = custom_rules.get("exclude_tags")
            if exclude_tags is not None:
                effective_config["EXCLUDE_TAGS"] = exclude_tags

    if use_jellyseerr_logic and tmdb_id and search_types:
        try:
            media_type = search_types[0]
            tmdb_id_int = int(tmdb_id) if tmdb_id else None

            if tmdb_id_int:
                print(f"[STREAM] Uso direttive Jellyseerr per tmdb_id={tmdb_id_int}, media_type={media_type}")

                # 1. Cerca request_rule da Jellyseerr se disponibile
                if validate_jellyseerr_config(config):
                    try:
                        requests_data = get_jellyseerr_requests(config, silent=True)
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
                                    fetch_request_details(request_item.get("id"), config, details_cache)
                                    or request_item
                                )
                            else:
                                request_details = request_item
                            print(f"[STREAM] Trovata richiesta Jellyseerr ID {request_item.get('id')}")
                    except Exception as e:
                        print(f"[STREAM] Errore recupero richiesta Jellyseerr: {e}")

                # 2. Componi request_rule se disponibile
                if request_rule:
                    effective_rules = _compose_request_search_rules(effective_rules, request_rule)
                    effective_config["SEARCH_RULES"] = effective_rules

                # 3. Recupera info da TMDB e genera query complete
                cache = {}
                tmdb_payload, resolved_type = fetch_media_info(
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
                            # TODO: Potremmo ricevere seasons da custom_rules
                            if request_details:
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
                            print(
                                f"[STREAM] Generate {len(actual_query_variants)} query da TMDB con direttive Jellyseerr"
                            )
        except Exception as e:
            print(f"[STREAM] Errore generazione query Jellyseerr: {e}")
            import traceback

            traceback.print_exc()
            # Fallback alle query originali

    # Prepara tutte le combinazioni di ricerca
    search_tasks = []
    for query_variant in actual_query_variants:
        normalized_query = (query_variant or "").strip()
        if not normalized_query:
            continue
        for search_type in search_types:
            if "prowlarr" in selected_indexers and _prowlarr_configured(config):
                search_tasks.append(
                    {
                        "indexer": "prowlarr",
                        "query": normalized_query,
                        "media_type": search_type,
                        "func": search_prowlarr,
                    }
                )
            if "jackett" in selected_indexers and _jackett_configured(config):
                search_tasks.append(
                    {
                        "indexer": "jackett",
                        "query": normalized_query,
                        "media_type": search_type,
                        "func": search_jackett,
                    }
                )

    total_queries = len(search_tasks)

    if total_queries == 0:
        await safe_send_json({"type": "error", "message": "Nessuna query da eseguire"})
        return {"total_results": 0, "total_duration": 0}

    # Funzione wrapper per eseguire singola ricerca e inviare risultati via WebSocket
    async def execute_and_stream(task):
        nonlocal total_results, completed_queries, seen_results

        query = task["query"]
        indexer = task["indexer"]
        media_type = task["media_type"]
        search_func = task["func"]

        query_start = time.time()

        # Notifica inizio query
        await safe_send_json(
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
            results = await asyncio.get_event_loop().run_in_executor(None, search_func, query, media_type, config)

            query_duration = time.time() - query_start
            result_count = len(results) if results else 0

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

                library_index = _load_emby_library_title_index()

                # Invia i risultati filtrati via WebSocket
                for result in filtered_results:
                    if not isinstance(result, dict):
                        continue

                    # Aggiungi info sulla libreria Emby
                    normalized_title = result.get("normalized_title") or sanitize_title((result.get("title") or "").lower())
                    result["normalized_title"] = normalized_title
                    result["in_library"] = bool(library_index and normalized_title in library_index)

                    # Deduplica basata su title normalizzato + size
                    result_key = build_dedupe_key(result)

                    if result_key not in seen_results:
                        seen_results.add(result_key)
                        total_results += 1

                        # Aggiungi a lista risultati per salvataggio finale
                        all_results.append(result)

                        # Invia risultato via WebSocket
                        await safe_send_json(
                            {
                                "type": "result",
                                "data": result,
                                "query": query,
                                "indexer": indexer,
                                "media_type": media_type,
                                "timestamp": datetime.now().isoformat(),
                            }
                        )

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
            await safe_send_json(
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

        except Exception as exc:
            query_duration = time.time() - query_start
            completed_queries += 1

            # Traccia query fallita
            query_attempts.append(
                {
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "results_found": 0,
                    "duration": round(query_duration, 2),
                    "error": str(exc),
                }
            )

            print(f"[STREAM] Errore ricerca {indexer} per '{query}': {exc}")
            await safe_send_json(
                {
                    "type": "error",
                    "query": query,
                    "indexer": indexer,
                    "media_type": media_type,
                    "error": str(exc),
                    "duration": round(query_duration, 2),
                    "timestamp": datetime.now().isoformat(),
                }
            )

    # Esegui tutte le ricerche in parallelo con asyncio.gather
    await asyncio.gather(*[execute_and_stream(task) for task in search_tasks])

    # Invia messaggio di completamento finale
    total_duration = time.time() - start_time

    # I risultati sono già stati filtrati da filter_results in execute_and_stream
    # Questo era il vecchio approccio dove si filtrava DOPO aver raccolto tutto
    # Ora filtriamo IMMEDIATAMENTE, esattamente come fa "Ricerche & Riepilogo"
    filters_applied = True  # I filtri sono stati applicati in execute_and_stream

    print(f"[STREAM] Risultati già filtrati durante lo streaming: {len(all_results)} totali")

    # Merge duplicati (raggruppa fonti multiple per stesso torrent)
    all_results = merge_duplicate_results(all_results)
    print(f"[STREAM] Dopo merge duplicati: {len(all_results)} risultati unici")

    # Debug: stampa il primo risultato dopo merge
    if all_results:
        first = all_results[0]
        print("      -> [DEBUG STREAM] Primo risultato DOPO merge_duplicate_results:")
        print(f"         magnet: {first.get('magnet')}")
        print(f"         torrent: {first.get('torrent')}")
        print(f"         web: {first.get('web')}")

    # Aggiorna il conteggio dopo merge
    total_results = len(all_results)

    # Ordina i risultati usando le regole di ordinamento configurate
    # SEMPRE applicato per garantire consistenza con le ricerche automatiche
    search_rules = effective_config.get("SEARCH_RULES", {})
    media_type_for_sort = search_types[0] if search_types else None
    all_results = sort_results(all_results, search_rules, media_type=media_type_for_sort)

    # Salva ricerca nel database (stesso formato delle ricerche automatiche)
    try:
        backend = _ensure_db_backend()

        # Estrai dati dalla prima variante di query
        original_query = query_variants[0] if query_variants else "Ricerca Manuale"
        media_type_str = search_types[0] if search_types else "unknown"

        # Crea payload compatibile con le ricerche automatiche
        search_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
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

        backend.save_manual_search(search_payload)
        print(f"[STREAM] Ricerca salvata nel database: {total_results} risultati")
    except Exception as e:
        print(f"[STREAM] Errore salvataggio ricerca DB: {e}")

    # Se sono stati applicati filtri Jellyseerr, invia i risultati finali filtrati
    final_message = {
        "type": "all_completed",
        "total_results": total_results,
        "total_queries": total_queries,
        "total_duration": round(total_duration, 2),
        "timestamp": datetime.now().isoformat(),
        "filters_applied": filters_applied,
    }

    # Se sono stati applicati filtri, includi i risultati finali filtrati
    if filters_applied:
        final_message["filtered_results"] = all_results

    await safe_send_json(final_message)

    return {
        "total_results": total_results,
        "total_queries": total_queries,
        "total_duration": round(total_duration, 2),
    }
