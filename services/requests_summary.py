# services/requests_summary.py
from datetime import datetime, timezone

from core.config import DEFAULT_CONFIG
from core.integrations import (
    _active_justwatch_settings,
    _get_justwatch_manager,
    _justwatch_enabled,
    _log_justwatch_status,
)
from core.justwatch_manager import JustWatchError
from core.scanner import extract_title_and_year, gather_title_candidates
from core.utils import _normalize_media_type, _parse_date_value, _sanitize_terms_list, get_nested
from emby_runtime.api_clients import fetch_media_info, fetch_request_details, get_jellyseerr_requests
from search.availability import is_request_available
from search.rules import _get_request_rule
from search.seasons import describe_season_statuses, select_scan_seasons, _request_release_date

TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w154"


def _iter_metadata_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        yield source
        for key in ("media", "mediaInfo"):
            nested = source.get(key)
            if isinstance(nested, dict):
                yield nested
                nested_media_info = nested.get("mediaInfo")
                if isinstance(nested_media_info, dict):
                    yield nested_media_info


def _first_metadata_value(sources, keys):
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
        external_ids = source.get("external_ids") or source.get("externalIds")
        if isinstance(external_ids, dict):
            for key in keys:
                value = external_ids.get(key)
                if value not in (None, ""):
                    return value
    return None


def _normalize_tmdb_media_type(media_type):
    normalized = _normalize_media_type(media_type)
    if normalized == "tv":
        return "tv"
    if normalized == "movie":
        return "movie"
    return ""


def _build_tmdb_poster_url(value):
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if not text.startswith("/"):
        text = f"/{text}"
    return f"{TMDB_IMAGE_BASE_URL}{text}"


def _build_jellyseerr_url(config, media_type, tmdb_id):
    base_url = str((config or {}).get("JELLYSEERR_URL") or "").rstrip("/")
    media_token = _normalize_tmdb_media_type(media_type)
    if not base_url or not tmdb_id or media_token not in {"movie", "tv"}:
        return ""
    return f"{base_url}/{media_token}/{tmdb_id}"


def _trakt_media_type(media_token):
    if media_token == "tv":
        return "show"
    if media_token == "movie":
        return "movie"
    return ""


def _build_request_external_links(config, base_req, media_type, *fallback_sources):
    sources = list(_iter_metadata_sources(base_req, *fallback_sources))
    tmdb_id = _first_metadata_value(sources, ("tmdbId", "tmdb_id", "tmdbid", "mediaId", "media_id"))
    imdb_id = _first_metadata_value(sources, ("imdbId", "imdb_id", "imdbID", "imdb"))
    poster = _first_metadata_value(sources, ("posterPath", "poster_path", "posterUrl", "poster_url", "poster"))
    media_token = _normalize_tmdb_media_type(media_type)
    tmdb_id = str(tmdb_id).strip() if tmdb_id else ""
    tmdb_url = f"https://www.themoviedb.org/{media_token}/{tmdb_id}" if media_token and tmdb_id else ""
    imdb_id = str(imdb_id).strip() if imdb_id else ""
    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id.startswith("tt") else ""
    trakt_type = _trakt_media_type(media_token)
    trakt_url = ""
    if tmdb_id and trakt_type:
        trakt_url = f"https://trakt.tv/search/tmdb/{tmdb_id}?type={trakt_type}"
    elif imdb_url and trakt_type:
        trakt_url = f"https://trakt.tv/search/imdb/{imdb_id}?type={trakt_type}"
    return {
        "poster_url": _build_tmdb_poster_url(poster),
        "jellyseerr_url": _build_jellyseerr_url(config, media_token, tmdb_id),
        "tmdb_url": tmdb_url,
        "imdb_url": imdb_url,
        "trakt_url": trakt_url,
    }


def _estimate_variant_summary(rules):
    if not rules:
        rules = DEFAULT_CONFIG["SEARCH_RULES"]
    season_templates = rules.get("season_templates") or DEFAULT_CONFIG["SEARCH_RULES"]["season_templates"]
    season_variants = max(1, len([tpl for tpl in season_templates if tpl]))
    query_terms_count = len(_sanitize_terms_list(rules.get("query_terms")))
    title_forms = 1
    if rules.get("use_original_title"):
        title_forms += 1
    if rules.get("use_alt_titles_original"):
        title_forms += 1
    if rules.get("use_alt_titles_language") and (rules.get("alt_titles_language") not in ("", "disabled")):
        title_forms += 1
    if rules.get("sanitize_titles"):
        title_forms += 1
    base_variants = title_forms * season_variants * (query_terms_count if query_terms_count > 0 else 1)
    episode_variants = 0
    if rules.get("search_episode_variants"):
        episode_variants = base_variants * 10
    return {
        "title_forms": title_forms,
        "season_variants": season_variants,
        "query_terms": query_terms_count,
        "base": base_variants,
        "episodes": episode_variants,
    }


def _resolve_request_metadata_for_summary(req, config, details_cache, media_cache, force_details=False):
    base_data = req
    media_info = base_data.get("media") or {}
    media_type = req.get("type") or media_info.get("mediaType")
    extra_sources = []
    for key in ("media", "mediaInfo"):
        val = base_data.get(key)
        if isinstance(val, dict):
            extra_sources.append(val)
            nested = val.get("mediaInfo")
            if isinstance(nested, dict):
                extra_sources.append(nested)
    title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if force_details or not title or not media_type:
        detailed = fetch_request_details(req.get("id"), config, details_cache)
        if detailed:
            base_data = detailed
            media_info = base_data.get("media") or media_info
            media_type = detailed.get("type") or get_nested(base_data, "media", "mediaType") or media_type
            extra_sources.extend([detailed, detailed.get("media"), detailed.get("mediaInfo")])
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources)
    if not title:
        media_details, resolved_type = fetch_media_info(media_info, config, media_cache, media_type)
        if media_details:
            extra_sources.append(media_details)
            title, year = extract_title_and_year(base_data, extra_sources=extra_sources + [media_details])
            if resolved_type and not media_type:
                media_type = resolved_type
    if not title:
        candidates = gather_title_candidates(base_data, extra_sources=extra_sources, search_rules=config.get("SEARCH_RULES"))
        if candidates:
            title = candidates[0]
    if not title:
        fallback_sources = [base_data, base_data.get("media"), base_data.get("mediaInfo")]
        fallback_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
        for source in fallback_sources:
            if not isinstance(source, dict):
                continue
            for key in fallback_keys:
                candidate = source.get(key)
                if candidate:
                    title = candidate
                    break
            if title:
                break
    return base_data, title, year, media_type


def _summarize_requests_for_dashboard(config, requests_data=None):
    if not config:
        return []
    try:
        if requests_data is None:
            requests_data = get_jellyseerr_requests(config, silent=True)
            print(f"   -> Dashboard: Jellyseerr ha restituito {len(requests_data)} richieste (pending+approved)")
            _log_justwatch_status()
        else:
            print(f"   -> Dashboard: Jellyseerr richieste fornite: {len(requests_data)}")
            _log_justwatch_status()
    except Exception as exc:
        print(f"   -> [ERRORE] Errore durante il recupero richieste Jellyseerr per dashboard: {exc}")
        import traceback
        traceback.print_exc()
        return []
    summary = []
    details_cache = {}
    media_cache = {}
    now = datetime.now(timezone.utc)
    rules = config.get("SEARCH_RULES", {})
    skip_available = rules.get("skip_available_content", True)
    skip_unreleased = rules.get("skip_unreleased_content", False)
    enriched_requests = []

    # Contatori per il logging
    tv_count = 0
    tv_detailed_success = 0
    tv_detailed_failed = 0

    for req in requests_data:
        if not isinstance(req, dict):
            continue
        media_type = _normalize_media_type(req.get("type") or get_nested(req, "media", "mediaType"))
        if media_type == "tv":
            tv_count += 1
            if is_request_available(req):
                enriched_requests.append(req)
                continue
            req_id = req.get("id")
            detailed = fetch_request_details(req_id, config, details_cache)
            if detailed:
                detailed["_summary_source_request"] = req
                tv_detailed_success += 1
                enriched_requests.append(detailed)
                continue
            else:
                tv_detailed_failed += 1
                print(f"   -> [WARNING] Impossibile recuperare dettagli per richiesta TV ID {req_id}, uso dati base")
        enriched_requests.append(req)

    # Log riepilogo arricchimento
    if tv_count > 0:
        print(f"   -> Dashboard: Richieste TV trovate: {tv_count}")
        print(f"   -> Dashboard: Dettagli recuperati con successo: {tv_detailed_success}")
        if tv_detailed_failed > 0:
            print(f"   -> Dashboard: [WARNING] Dettagli NON recuperati: {tv_detailed_failed}")

    requests_data = enriched_requests
    for req in requests_data:
        req_id = req.get("id")
        if not req_id:
            continue
        type_hint = _normalize_media_type(req.get("type") or get_nested(req, "media", "mediaType"))
        force_details = bool(type_hint == "tv" and not is_request_available(req))
        base_req, title, year, media_type = _resolve_request_metadata_for_summary(
            req,
            config,
            details_cache,
            media_cache,
            force_details=force_details,
        )
        normalized_type = _normalize_media_type(media_type)
        season_status = describe_season_statuses(base_req) if normalized_type == "tv" else []
        seasons = [entry["season"] for entry in season_status]
        release_dt = _request_release_date(base_req)
        release_label = release_dt.strftime("%Y-%m-%d") if release_dt else None
        status_code = get_nested(base_req, "media", "status") or get_nested(req, "media", "status")
        is_available = is_request_available(base_req, season_status)
        request_rule = _get_request_rule(config, req_id)
        will_skip = False
        if skip_available and is_available:
            will_skip = True
        if skip_unreleased and release_dt and release_dt > now:
            will_skip = True
        if normalized_type == "tv" and season_status:
            scan_candidates = select_scan_seasons(season_status, skip_available, skip_unreleased)
            if not scan_candidates:
                will_skip = True
        created_at = _parse_date_value(
            req.get("createdAt") or req.get("created_at") or req.get("addedAt") or req.get("added_at")
        )
        age_label = None
        if created_at:
            diff = now - created_at
            days = diff.days
            seconds = diff.seconds
            if days > 0:
                age_label = f"{days}g fa"
            elif seconds >= 3600:
                age_label = f"{seconds // 3600}h fa"
            elif seconds >= 60:
                age_label = f"{seconds // 60}m fa"
            else:
                age_label = "Pochi secondi fa"
        justwatch_checked = False
        justwatch_available = False
        justwatch_providers = []
        source_request = req.get("_summary_source_request") if isinstance(req, dict) else None
        external_links = _build_request_external_links(config, base_req, normalized_type, source_request or req)
        if normalized_type != "tv" and not (is_available or (release_dt and release_dt > now)):
            settings = _active_justwatch_settings()
            if _justwatch_enabled(settings):
                manager = _get_justwatch_manager(settings)
                if manager and title:
                    year_int = None
                    if isinstance(year, int):
                        year_int = year
                    elif isinstance(year, str):
                        try:
                            year_int = int(year)
                        except ValueError:
                            year_int = None
                    try:
                        justwatch_available, justwatch_providers = manager.check_movie_availability_details(
                            title,
                            year=year_int,
                        )
                        justwatch_checked = bool(justwatch_available)
                    except JustWatchError as exc:
                        print(f"   -> JustWatch: errore verifica movie {title}: {exc}")
        summary.append(
            {
                "id": req_id,
                "title": title or "N/D",
                "year": year,
                "media_type": media_type,
                "seasons": seasons,
                "status": status_code,
                "release_date": release_label,
                "is_available": is_available,
                "is_unreleased": bool(release_dt and release_dt > now),
                "will_skip": will_skip,
                "age": age_label,
                "season_status": season_status,
                "justwatch_checked": justwatch_checked,
                "justwatch_available": justwatch_available,
                "justwatch_providers": justwatch_providers,
                **external_links,
                "rules": {
                    "query_terms": ",".join(request_rule.get("query_terms", [])),
                    "filter_terms": ",".join(request_rule.get("filter_terms", [])),
                    "exclude_terms": ",".join(request_rule.get("exclude_terms", [])),
                    "enabled": request_rule.get("enabled", True),
                },
            }
        )
    print(f"   -> Dashboard: Elaborazione completata, {len(summary)} richieste nel summary finale")
    return summary
