"""
Search and request processing pipeline for OctoHub.
Extracted from the legacy monolith to reduce module size.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.search_normalizer import build_dedupe_key
from core.scanner import build_search_queries, extract_title_and_year, filter_results, gather_title_candidates
from core.utils import _normalize_media_type, get_nested
from emby_runtime.api_clients import (
    fetch_media_info,
    fetch_request_details,
    get_jellyseerr_requests,
    search_jackett,
    search_prowlarr,
)
from search.indexers import _should_use_jackett, _should_use_prowlarr
from search.rules import _compose_request_search_rules, _get_request_rule
from search.seasons import (
    _filter_unreleased_seasons,
    _is_request_unreleased,
    describe_season_statuses,
    extract_request_seasons,
    get_episode_count_for_season,
    get_pending_episode_numbers,
    select_scan_seasons,
)
from search.utils import merge_duplicate_results, sort_results
from services.scan_results import load_results_file, save_results, _merge_scan_summaries


def search_indexers(query, media_type, config):
    """
    Esegue ricerche parallele su Prowlarr e Jackett per ridurre i tempi di risposta.
    """
    import concurrent.futures

    providers_used = False
    aggregated = []
    search_tasks = []

    # Prepara le ricerche da eseguire in parallelo
    if _should_use_prowlarr(config):
        providers_used = True
        search_tasks.append(("prowlarr", search_prowlarr, query, media_type, config))
    if _should_use_jackett(config):
        providers_used = True
        search_tasks.append(("jackett", search_jackett, query, media_type, config))

    if not providers_used:
        print("   -> Nessun indexer disponibile per le ricerche (abilita Prowlarr o Jackett).")
        return aggregated

    # Esegue le ricerche in parallelo
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(search_tasks)) as executor:
        future_to_provider = {
            executor.submit(search_func, q, mt, cfg): provider_name
            for provider_name, search_func, q, mt, cfg in search_tasks
        }

        for future in concurrent.futures.as_completed(future_to_provider):
            provider_name = future_to_provider[future]
            try:
                results = future.result()
                if results:
                    aggregated.extend(results)
            except Exception as exc:
                print(f"   -> ⚠️ Errore ricerca {provider_name}: {exc}")

    return aggregated


def execute_search_with_variants(
    query_variants,
    media_type,
    config,
    canonical_titles=None,
    exclusion_collector=None,
    request_rules=None,
):
    attempts = []
    collected = []
    seen_keys = set()

    def _result_key(item):
        normalized_title, size_gb = build_dedupe_key(item)
        return f"{normalized_title}|{size_gb}"

    for query in query_variants:
        raw_results = search_indexers(query, media_type, config)
        valid_results = filter_results(
            raw_results,
            config,
            canonical_titles=canonical_titles,
            media_type=media_type,
            exclusion_collector=exclusion_collector,
            request_rules=request_rules,
        )
        attempts.append({
            "query": query,
            "results_found": len(valid_results),
        })
        for result in valid_results:
            key = _result_key(result)
            if key in seen_keys:
                continue
            collected.append(result)
            seen_keys.add(key)

    return collected, attempts


def process_requests(config, status_callback=None, stop_event=None, target_map=None):
    print("--- Avvio OctoHub ---")
    requests_list = get_jellyseerr_requests(config)
    rules = config.get("SEARCH_RULES", {})
    previous_summary = load_results_file()
    target_map = target_map or {}

    if target_map:
        target_ids = set(target_map.keys())
        filtered = [req for req in requests_list if isinstance(req, dict) and str(req.get("id")) in target_ids]
        missing = target_ids - {str(req.get("id")) for req in filtered if isinstance(req, dict)}
        requests_list = filtered
        if missing:
            print(f"   -> Attenzione: {len(missing)} richieste selezionate non risultano più pendenti/approvate.")
        print(f"   -> Ricerca mirata su {len(requests_list)} richieste.")

    if not requests_list:
        print("\nNessuna richiesta da elaborare. Interrompo.")
        empty_summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": 0,
            "checked_requests": 0,
            "found": 0,
            "items": [],
        }
        merged_empty = _merge_scan_summaries(previous_summary, empty_summary)
        save_results(merged_empty)
        return merged_empty

    total_requests = len(requests_list)
    non_available_requests = []
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    skipped_available = 0
    skipped_unreleased = 0
    skipped_type = 0
    skipped_disabled = 0
    skipped_season_only = 0

    # Primo passo: filtrare le richieste per media non disponibili
    for req in requests_list:
        if not isinstance(req, dict):
            continue
        media_info = req.get("media", {})
        status = media_info.get("status")
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        force_include = bool(target_spec)
        if skip_available and status == 5 and not force_include:
            skipped_available += 1
            continue
        if skip_unreleased and _is_request_unreleased(req) and not force_include:
            skipped_unreleased += 1
            continue
        media_type = req.get("type") or media_info.get("mediaType")
        normalized_type = _normalize_media_type(media_type)
        request_rule = _get_request_rule(config, req.get("id"))
        if not isinstance(request_rule, dict):
            request_rule = None
        if request_rule and not request_rule.get("enabled", True) and not force_include:
            skipped_disabled += 1
            continue
        non_available_requests.append(req)

    print(
        f"   -> Dopo i filtri rimangono {len(non_available_requests)} richieste "
        f"da analizzare (su {total_requests} totali)."
    )
    if skipped_available:
        print(f"      (Saltate {skipped_available} richieste già disponibili)")
    if skipped_unreleased:
        print(f"      (Saltate {skipped_unreleased} richieste non ancora pubblicate)")
    if skipped_type:
        print(f"      (Saltate {skipped_type} richieste di tipologia esclusa)")
    if skipped_disabled:
        print(f"      (Saltate {skipped_disabled} richieste disattivate manualmente)")
    details_cache: dict[str, Any] = {}
    media_details_cache: dict[str, Any] = {}
    prepared_requests = []
    for req in non_available_requests:
        normalized_type = _normalize_media_type(req.get("type") or get_nested(req, "media", "mediaType"))
        resolved = req
        if normalized_type == "tv" and (skip_available or skip_unreleased):
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                resolved = detailed
        prepared_requests.append(resolved)
    non_available_requests = prepared_requests

    job_queue = []
    skipped_season_only = 0
    for req in non_available_requests:
        media_type_value = req.get("type") or get_nested(req, "media", "mediaType")
        normalized_type = _normalize_media_type(media_type_value)
        req_key = str(req.get("id"))
        target_spec = target_map.get(req_key) if target_map else None
        forced_seasons_spec = target_spec.get("seasons") if target_spec else None
        seasons = []
        season_overview = []
        if normalized_type == "tv":
            season_overview = describe_season_statuses(req)
            if forced_seasons_spec:
                seasons = sorted(forced_seasons_spec)
            else:
                seasons = select_scan_seasons(season_overview, skip_available, skip_unreleased)
                if not seasons and season_overview and not target_spec:
                    skipped_season_only += 1
                    continue
                if not seasons:
                    seasons = extract_request_seasons(req, skip_available=False)
                    if seasons and skip_unreleased and not target_spec:
                        seasons = _filter_unreleased_seasons(req, seasons)
            req["_season_overview"] = season_overview
            if target_spec and forced_seasons_spec is None:
                seasons = seasons if seasons else extract_request_seasons(req, skip_available=False)
        else:
            if forced_seasons_spec:
                seasons = [None]
        job_queue.append((req, seasons if seasons else [None]))

    if skipped_season_only:
        print(f"      (Saltate {skipped_season_only} richieste TV senza episodi/stagioni da cercare)")

    total_iterations = sum(len(entry[1]) for entry in job_queue)
    if status_callback:
        status_callback(0, total_iterations, None, None)

    found_items_count = 0
    processed_iterations = 0
    processed_results = []
    aborted = False

    for i, (req, seasons) in enumerate(job_queue):
        if stop_event and stop_event.is_set():
            aborted = True
            break
        base_data = req
        media_info = base_data.get("media") or {}
        media_type = req.get("type") or media_info.get("mediaType")

        extra_sources = []

        def _extend_extra_sources(*values):
            for value in values:
                if isinstance(value, dict):
                    extra_sources.append(value)

        media_details = None
        title, year = extract_title_and_year(base_data)

        if not title or not media_type:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)

        normalized_media_type = _normalize_media_type(media_type)
        target_spec = target_map.get(str(req.get("id"))) if target_map else None
        force_search = bool(target_spec and target_spec.get("force"))
        need_availability_details = rules.get("skip_available_content", True) and normalized_media_type == "tv"
        if need_availability_details and base_data is req:
            detailed = fetch_request_details(req.get("id"), config, details_cache)
            if detailed:
                base_data = detailed
                media_info = base_data.get("media") or media_info
                media_type = detailed.get("type") or base_data.get("media", {}).get("mediaType") or media_type
                _extend_extra_sources(detailed, detailed.get("media"), detailed.get("mediaInfo"))
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources) or (title, year)

        if not title:
            print(f"   -> Recupero dettagli TMDB aggiuntivi per richiesta {req.get('id')}...")
            media_details, resolved_type = fetch_media_info(media_info, config, media_details_cache, media_type)
            if (not media_details) and base_data.get("mediaInfo"):
                alt_details, alt_type = fetch_media_info(base_data.get("mediaInfo"), config, media_details_cache, media_type)
                if alt_details:
                    media_details = alt_details
                    resolved_type = resolved_type or alt_type
            if media_details:
                _extend_extra_sources(media_details)
                title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
            if resolved_type and not media_type:
                media_type = resolved_type

        if not media_type:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: tipo di media non disponibile.")
            continue

        if not title:
            print(f"   -> Richiesta ID {req.get('id')} ignorata: titolo non trovato nei dati di Jellyseerr.")
            continue

        display_year = year or "----"

        request_rule = _get_request_rule(config, req.get("id"))
        effective_rules = _compose_request_search_rules(config.get("SEARCH_RULES"), request_rule)
        title_candidates = gather_title_candidates(base_data, extra_sources, effective_rules)
        if title not in title_candidates:
            title_candidates.insert(0, title)
        id_sources = [req, base_data, media_info, base_data.get("media"), base_data.get("mediaInfo"), media_details]
        id_sources.extend(extra_sources)

        season_overview_map = {}
        if normalized_media_type == "tv":
            overview = req.get("_season_overview") or describe_season_statuses(base_data)
            season_overview_map = {entry["season"]: entry for entry in overview}
        for season in seasons:
            if stop_event and stop_event.is_set():
                aborted = True
                break

            season_label = f" - Stagione {season:02d}" if season is not None else ""
            print(f"\n2. Elaboro richiesta [{i+1}/{len(non_available_requests)}]{season_label}: {title} ({display_year})")

            episode_count = get_episode_count_for_season([src for src in id_sources if isinstance(src, dict)], season)
            pending_episodes = None
            if rules.get("skip_available_content", True) and normalized_media_type == "tv" and not force_search:
                entry = season_overview_map.get(season)
                if entry:
                    pending_episodes = entry.get("pending")
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(
                                f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria."
                            )
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available",
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
                if pending_episodes is None:
                    pending_episodes = get_pending_episode_numbers(base_data, season)
                    if pending_episodes is not None:
                        pending_episodes = sorted(set(ep for ep in pending_episodes if isinstance(ep, int) and ep > 0))
                        if not pending_episodes:
                            print(
                                f"   -> Stagione {season:02d} già completa su Jellyseerr. Nessuna ricerca necessaria."
                            )
                            processed_results.append({
                                "request_id": req.get("id"),
                                "title": title,
                                "year": year,
                                "media_type": media_type,
                                "season": season,
                                "queries": [],
                                "results_found": 0,
                                "results": [],
                                "excluded": [],
                                "skipped_reason": "season_available",
                            })
                            processed_iterations += 1
                            if status_callback:
                                status_callback(processed_iterations, total_iterations, title, season)
                            continue
            movie_year_variance = request_rule.get("year_variance", 0) if normalized_media_type == "movie" else 0
            query_variants = build_search_queries(
                title_candidates,
                year,
                config,
                media_type=media_type,
                season_code=season,
                episode_count=episode_count,
                request_terms=request_rule,
                pending_episodes=pending_episodes,
                search_rules_override=effective_rules,
                year_variance=movie_year_variance,
            )
            print(f"   -> Varianti provate: {len(query_variants)}")
            exclusion_reasons = []
            valid_results, attempts = execute_search_with_variants(
                query_variants,
                media_type,
                config,
                canonical_titles=title_candidates,
                exclusion_collector=exclusion_reasons,
                request_rules=request_rule,
            )

            if valid_results:
                found_items_count += 1
                sorted_results = sort_results(
                    valid_results,
                    config.get("SEARCH_RULES", {}),
                    media_type=media_type,
                )
                grouped_results = merge_duplicate_results(sorted_results)
                print(f"   => {len(grouped_results)} risultati utili per '{title}'{season_label}:")
                for item in grouped_results[:5]:
                    print(f"     - Titolo: {item['title']}")
                    print(f"       Dim: {item['size_gb']} GB, Seeders: {item['seeders']}, Fonte: {item['indexer']}")
                    print(f"       Link: {item['link']}\n")
            else:
                grouped_results = []
                print(f"   => Nessun risultato valido per '{title}'{season_label}.")

            processed_results.append({
                "request_id": req.get("id"),
                "title": title,
                "year": year,
                "media_type": media_type,
                "season": season,
                "queries": attempts,
                "results_found": len(grouped_results),
                "results": grouped_results,
                "excluded": exclusion_reasons,
            })

            processed_iterations += 1
            if status_callback:
                status_callback(processed_iterations, total_iterations, title, season)

        if aborted:
            break

    print("\n--- Riepilogo ---")
    print(
        f"Ricerca completata. Trovati contenuti per {found_items_count} "
        f"su {len(non_available_requests)} richieste analizzate."
    )

    run_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "checked_requests": len(non_available_requests),
        "found": found_items_count,
        "items": processed_results,
        "aborted": aborted,
        "target_subset": bool(target_map),
    }
    merged_summary = _merge_scan_summaries(previous_summary, run_summary)
    save_results(merged_summary)
    return merged_summary
