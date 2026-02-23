# core/scanner.py
"""Pure business logic for scanning, searching, and filtering media requests."""

import re
import unicodedata
from typing import Optional, Tuple

from core.utils import _sanitize_terms_list, _resolution_label_from_dims
from emby_runtime.api_clients import _try_parse_int
from core.config import _merge_resolution_settings


# --- CONSTANTS ---

MAX_PRIMARY_QUERY_VARIANTS = 80
_TAG_REGEX_CACHE = {}
_DIMENSION_REGEX = re.compile(r"(?P<w>\d{3,4})\s*[x×]\s*(?P<h>\d{3,4})", re.IGNORECASE)
_RESOLUTION_RANK = {
    "2160p": 6,
    "1440p": 5,
    "1080p": 4,
    "720p": 3,
    "576p": 2,
    "480p": 1
}


# --- METADATA EXTRACTION ---

def _collect_metadata_sources(source):
    """Collects metadata sources from a request item."""
    collected = []
    if not isinstance(source, dict) or not source:
        return collected
    collected.append(source)
    media_info = source.get("mediaInfo") if isinstance(source.get("mediaInfo"), dict) else None
    media = source.get("media") if isinstance(source.get("media"), dict) else None
    if media_info:
        collected.append(media_info)
    if media:
        collected.append(media)
    return collected


def _first_available_field(data, keys):
    """Returns the first non-empty value from data for the given keys."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _format_year(value):
    """Formats a year value to a 4-digit string."""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if len(cleaned) >= 4 and cleaned[:4].isdigit():
            return cleaned[:4]
        if cleaned.isdigit():
            return cleaned
    return None


def _first_title_from_list(values):
    """Extracts the first suitable title from a list of title entries."""
    if not isinstance(values, list):
        return None
    preferred_languages = ["it", "ita", "it-IT", "en", None]
    for preferred in preferred_languages:
        for entry in values:
            lang = entry.get("iso_639_1") or entry.get("language")
            title = entry.get("title") or entry.get("name")
            if not title:
                continue
            if preferred is None or (lang and lang.lower() == preferred.lower()):
                return title
    for entry in values:
        title = entry.get("title") or entry.get("name")
        if title:
            return title
    return None


def _detect_original_language(metadata_sources):
    """Detects the original language from metadata sources."""
    for source in metadata_sources:
        if not isinstance(source, dict):
            continue
        for key in ("originalLanguage", "original_language", "language"):
            value = source.get(key)
            if value:
                return str(value).lower()
    return None


def extract_title_and_year(request_item, extra_sources=None):
    """Extracts title and year from various sections of a request item."""
    metadata_candidates = _collect_metadata_sources(request_item)
    if extra_sources:
        for source in extra_sources:
            metadata_candidates.extend(_collect_metadata_sources(source))
    title_keys = ["title", "name", "originalTitle", "originalName", "displayName"]
    date_keys = [
        "releaseDate",
        "release_date",
        "firstAirDate",
        "first_air_date",
        "airDate",
        "startDate",
        "year",
        "releaseYear"
    ]

    for source in metadata_candidates:
        title = _first_available_field(source, title_keys)
        if not title:
            title = _first_title_from_list(source.get("titles"))
        if not title:
            title = _first_title_from_list(source.get("alternativeTitles"))
        if not title:
            continue
        year_value = _first_available_field(source, date_keys)
        formatted_year = _format_year(year_value)
        return title, formatted_year
    return None, None


# --- TITLE CANDIDATE GATHERING ---

def gather_title_candidates(primary_source, extra_sources=None, search_rules=None):
    """Gathers all possible title variations for searching."""
    # Default search rules fallback
    default_search_rules = {
        "use_original_title": True,
        "use_alt_titles_original": True,
        "use_alt_titles_language": False,
        "alt_titles_language": ""
    }
    search_rules = search_rules or default_search_rules

    metadata_sources = _collect_metadata_sources(primary_source)
    if extra_sources:
        for src in extra_sources:
            metadata_sources.extend(_collect_metadata_sources(src))

    seen = []
    original_language = _detect_original_language(metadata_sources)
    alt_lang_enabled = search_rules.get("use_alt_titles_language", False)
    alt_lang_value = (search_rules.get("alt_titles_language") or "").lower()

    def _append_candidate(value):
        if not value:
            return
        value = value.strip()
        if value and value not in seen:
            seen.append(value)

    for source in metadata_sources:
        for key in ["title", "name", "displayName"]:
            _append_candidate(source.get(key))
        if search_rules.get("use_original_title", True):
            for key in ["originalTitle", "originalName"]:
                _append_candidate(source.get(key))
        include_alt_original = search_rules.get("use_alt_titles_original", True)
        for list_key in ("titles", "alternativeTitles"):
            entries = source.get(list_key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                candidate = None
                entry_lang = None
                entry_type = None
                if isinstance(entry, dict):
                    candidate = entry.get("title") or entry.get("name")
                    entry_lang = entry.get("iso_639_1") or entry.get("iso_3166_1") or entry.get("language")
                    entry_type = (entry.get("type") or "").lower()
                    entry_lang = entry_lang.lower() if isinstance(entry_lang, str) else entry_lang
                elif isinstance(entry, str):
                    candidate = entry
                if not candidate:
                    continue

                allowed = False
                if include_alt_original:
                    if entry_type == "original":
                        allowed = True
                    elif original_language and entry_lang and entry_lang.startswith(original_language):
                        allowed = True
                if not allowed and alt_lang_enabled:
                    if alt_lang_value == "all":
                        allowed = True
                    elif alt_lang_value and entry_lang:
                        allowed = entry_lang.startswith(alt_lang_value)
                if not allowed and include_alt_original and not original_language and not entry_lang:
                    allowed = True

                if allowed:
                    _append_candidate(candidate)
    return seen


# --- TITLE SANITIZATION ---

def sanitize_title(value):
    """Sanitizes a title by removing accents and special characters."""
    normalized = unicodedata.normalize('NFKD', value)
    ascii_chars = []
    for char in normalized:
        if unicodedata.category(char) == 'Mn':
            continue
        if char in {"'", "'", "'", "`"}:
            ascii_chars.append(" ")
            continue
        if char.isalnum() or char.isspace():
            ascii_chars.append(char)
    sanitized = ''.join(ascii_chars)
    return ' '.join(sanitized.split())


# --- SEARCH QUERY BUILDING ---

def build_search_queries(
    title_candidates,
    year,
    config,
    media_type=None,
    season_code: Optional[int] = None,
    episode_count: Optional[int] = None,
    request_terms=None,
    pending_episodes=None,
    search_rules_override=None,
    year_variance: int = 0
):
    """Builds search queries from title candidates and search parameters."""
    # Default search rules and config fallbacks
    default_search_rules = {
        "query_terms": [],
        "include_target_lang_base": False,
        "ignore_year_for_tv": False,
        "season_templates": ["S{season02}", "Season {season}", "Stagione {season}"],
        "search_episode_variants": True,
        "skip_season_queries_when_episode_search": False,
        "sanitize_titles": True
    }

    rules = search_rules_override or config.get("SEARCH_RULES", default_search_rules)
    primary_candidates = []
    episode_candidates = []
    query_terms = []
    for term in _sanitize_terms_list(rules.get("query_terms")):
        if term not in query_terms:
            query_terms.append(term)
    if request_terms:
        for term in _sanitize_terms_list(request_terms.get("query_terms")):
            if term not in query_terms:
                query_terms.append(term)
    has_primary_terms = len(query_terms) > 0
    if "query_languages" in rules:
        lang_terms = _sanitize_terms_list(rules.get("query_languages"))
    else:
        lang_terms = _sanitize_terms_list(config.get("TARGET_LANGUAGES"))
    include_language_variants = rules.get("include_target_lang_base", False)
    force_language_only = bool(lang_terms) and not include_language_variants
    if force_language_only:
        for lang in lang_terms:
            if lang not in query_terms:
                query_terms.append(lang)
    lang_variant_terms = lang_terms if include_language_variants else []
    use_only_term_queries = has_primary_terms or force_language_only

    def _compose_query(title_value, additional_term=None, season_token=None, year_value=None):
        components = [title_value]
        if season_token:
            components.append(season_token)
        if additional_term:
            components.append(additional_term)
        if year_value:
            components.append(str(year_value))
        return " ".join(part for part in components if part)

    skip_year = media_type == "tv" and rules.get("ignore_year_for_tv")
    if skip_year or not year:
        year_values = [None]
    else:
        base_years = {int(year)}
        variance = max(0, int(year_variance or 0))
        if variance > 0:
            for delta in range(-variance, variance + 1):
                candidate = int(year) + delta
                if candidate > 0:
                    base_years.add(candidate)
        year_values = sorted(base_years)
    parsed_season = _try_parse_int(season_code) if season_code is not None else None
    season_tokens = []
    season_templates = rules.get("season_templates") or default_search_rules["season_templates"]
    if parsed_season is not None:
        season_str = str(parsed_season)
        season02 = f"{parsed_season:02d}"
        for template in season_templates:
            tpl = template.strip()
            if not tpl:
                continue
            token = tpl.replace("{season02}", season02).replace("{season}", season_str)
            if token and token not in season_tokens:
                season_tokens.append(token)
    token_variants = season_tokens or [None]
    include_episode_variants = bool(rules.get("search_episode_variants", True))
    if parsed_season is not None and rules.get("skip_season_queries_when_episode_search"):
        include_episode_variants = True
    skip_season_queries = bool(
        parsed_season is not None
        and rules.get("skip_season_queries_when_episode_search", False)
    )
    if skip_season_queries:
        primary_season_tokens = []
    else:
        primary_season_tokens = token_variants
    episode_limit = episode_count if episode_count and episode_count > 0 else 20

    for title in title_candidates:
        if not title:
            continue
        candidate_forms = [title]
        if rules.get("sanitize_titles"):
            sanitized = sanitize_title(title)
            if sanitized and sanitized != title:
                candidate_forms.append(sanitized)
        if primary_season_tokens:
            if use_only_term_queries:
                for term in query_terms:
                    for form in candidate_forms:
                        for token in token_variants:
                            for yr in year_values:
                                primary_candidates.append(_compose_query(form, additional_term=term, season_token=token, year_value=yr))
            else:
                for form in candidate_forms:
                    for token in primary_season_tokens:
                        for yr in year_values:
                            primary_candidates.append(_compose_query(form, season_token=token, year_value=yr))
                for term in query_terms:
                    for form in candidate_forms:
                        for token in primary_season_tokens:
                            for yr in year_values:
                                primary_candidates.append(_compose_query(form, additional_term=term, season_token=token, year_value=yr))
        if lang_variant_terms:
            if skip_season_queries:
                target_tokens = []
            else:
                target_tokens = primary_season_tokens or token_variants or [None]
            for lang_term in lang_variant_terms:
                for form in candidate_forms:
                    for token in target_tokens:
                        for yr in year_values:
                            primary_candidates.append(_compose_query(form, additional_term=lang_term, season_token=token, year_value=yr))
        if include_episode_variants and parsed_season is not None:
            if pending_episodes is not None:
                episodes_iter = [ep for ep in pending_episodes if isinstance(ep, int) and ep > 0]
                if not episodes_iter:
                    episodes_iter = list(range(1, episode_limit + 1))
            else:
                episodes_iter = list(range(1, episode_limit + 1))
            if episodes_iter:
                for episode in episodes_iter:
                    season_token = f"S{parsed_season:02d}E{episode:02d}"
                    alt_token = f"{parsed_season}x{episode:02d}"
                    def _emit_episode(term=None):
                        for form in candidate_forms:
                            for yr in year_values:
                                episode_candidates.append(_compose_query(form, additional_term=term, season_token=season_token, year_value=yr))
                                episode_candidates.append(_compose_query(form, additional_term=term, season_token=alt_token, year_value=yr))
                    if use_only_term_queries:
                        for term in query_terms:
                            _emit_episode(term)
                    else:
                        _emit_episode(None)
                        for term in query_terms:
                            _emit_episode(term)
                    if lang_variant_terms:
                        for lang_term in lang_variant_terms:
                            _emit_episode(lang_term)
    deduped = []
    seen = set()
    for query in primary_candidates:
        normalized = query.strip()
        if not normalized or normalized.lower() in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized.lower())
        if len(deduped) >= MAX_PRIMARY_QUERY_VARIANTS:
            break
    for query in episode_candidates:
        normalized = query.strip()
        if not normalized or normalized.lower() in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized.lower())
    return deduped or ([title_candidates[0]] if title_candidates else [])


# --- LANGUAGE AND TAG DETECTION ---

def _contains_language_token(title_lower, lang):
    """Checks if a language token is present in the title."""
    token = lang.lower()
    return token in title_lower


def _has_audio_language(title_lower, lang):
    """Checks if audio language is present (excluding subtitles)."""
    token = lang.lower()
    idx = title_lower.find(token)
    while idx != -1:
        prefix = title_lower[max(0, idx - 5):idx]
        if "sub" not in prefix:
            return True
        idx = title_lower.find(token, idx + len(token))
    return False


def _contains_isolated_tag(text: str, tag: str) -> bool:
    """Verifies if 'tag' appears as an isolated word separated by spaces/punctuation."""
    if not text or not tag:
        return False
    tag_lower = tag.lower()
    cached = _TAG_REGEX_CACHE.get(tag_lower)
    if cached is None:
        separators = r"\s\.\-_\[\]\(\)\{\}"
        pattern = re.compile(rf"(^|[{separators}]){re.escape(tag_lower)}(?=$|[{separators}])")
        _TAG_REGEX_CACHE[tag_lower] = pattern
        cached = pattern
    return cached.search(text) is not None


# --- EPISODE AND RESOLUTION DETECTION ---

def _extract_episode_from_title(title) -> Tuple[Optional[int], Optional[int], Optional[str], Optional[int]]:
    """Extracts season and episode numbers from a torrent title."""
    if not title:
        return None, None, None, None
    patterns = [
        re.compile(r'[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})'),
        re.compile(r'(\d{1,2})x(\d{1,3})'),
        re.compile(r'stagione\s*(\d{1,2}).{0,6}?episodio\s*(\d{1,3})', re.IGNORECASE)
    ]
    for pattern in patterns:
        match = pattern.search(title)
        if match:
            season = _try_parse_int(match.group(1))
            episode = _try_parse_int(match.group(2))
            if season is not None and episode is not None:
                code = f"S{season:02d}E{episode:02d}"
                return season, episode, code, season * 1000 + episode
    return None, None, None, None


def _detect_resolution_bucket(title_lower, resolution_rules=None):
    """Detects the resolution category from a torrent title."""
    if not title_lower:
        return "other"
    rules = _merge_resolution_settings(resolution_rules)
    text = title_lower.lower()
    if "2160" in text or "4k" in text or "uhd" in text:
        return "2160p"
    if "1440p" in text:
        return "1440p"
    if "1080" in text:
        return "1080p"
    if "720" in text:
        return "720p"
    if "576p" in text:
        return "576p"
    if "480p" in text:
        return "480p"

    best_label = ""
    best_rank = 0
    for match in _DIMENSION_REGEX.finditer(text):
        width = match.group("w")
        height = match.group("h")
        label = _resolution_label_from_dims(width, height, rules)
        rank = _RESOLUTION_RANK.get(label, 0)
        if rank > best_rank:
            best_rank = rank
            best_label = label
    if best_label:
        return best_label
    return "other"


# --- RESULT FILTERING ---

def filter_results(
    results,
    config,
    canonical_titles=None,
    *,
    media_type=None,
    exclusion_collector=None,
    request_rules=None
):
    """Filters Prowlarr results based on language, tags, seeders, and additional rules."""
    filtered_list = []
    if not results:
        return filtered_list

    rules = config.get("SEARCH_RULES", {})
    target_languages = _sanitize_terms_list(config.get("TARGET_LANGUAGES"))
    global_exclude_tags = [tag.lower() for tag in _sanitize_terms_list(config.get("EXCLUDE_TAGS"))]
    min_seeders = int(rules.get("min_seeders", 0))
    global_filter_terms = [term.lower() for term in _sanitize_terms_list(rules.get("filter_terms"))]
    require_audio_language = rules.get("require_audio_language", False)
    request_rules = request_rules or {}
    request_filter_terms = [term.lower() for term in _sanitize_terms_list(request_rules.get("filter_terms"))]
    request_excluded_terms = [term.lower() for term in _sanitize_terms_list(request_rules.get("exclude_terms"))]
    required_terms = global_filter_terms + request_filter_terms
    resolution_rules = config.get("RESOLUTION_RULES") if isinstance(config, dict) else None

    def _record_exclusion(result, reason):
        if exclusion_collector is not None:
            exclusion_collector.append({
                "title": result.get("title"),
                "indexer": result.get("indexer"),
                "reason": reason
            })

    for result in results:
        title_lower = result.get("title", "").lower()
        if required_terms and not any(term in title_lower for term in required_terms):
            _record_exclusion(result, "Non contiene i termini filtrati richiesti")
            continue
        if request_excluded_terms and any(term in title_lower for term in request_excluded_terms):
            _record_exclusion(result, "Contiene termini esclusi (regola richiesta)")
            continue
        lang_found_generic = any(_contains_language_token(title_lower, lang) for lang in target_languages)
        lang_found_audio = any(_has_audio_language(title_lower, lang) for lang in target_languages)
        if not target_languages:
            lang_found = True
        else:
            lang_found = lang_found_audio if require_audio_language else lang_found_generic
        exclude_found = False
        for tag in global_exclude_tags:
            if _contains_isolated_tag(title_lower, tag):
                exclude_found = True
                break
        seeders = result.get("seeders", 0) or 0
        if seeders < min_seeders:
            _record_exclusion(result, f"Seeders {seeders} < min {min_seeders}")
            continue

        if lang_found and not exclude_found:
            # Non usare guid come fallback per magnet perché potrebbe contenere il download link
            magnet_link = result.get("magnet")
            torrent_link = result.get("torrent") or result.get("downloadUrl")
            if isinstance(torrent_link, str) and torrent_link.startswith("magnet:"):
                if not magnet_link:
                    magnet_link = torrent_link
                torrent_link = None
            web_link = result.get("web") or result.get("infoUrl") or result.get("indexerUrl") or result.get("details")
            direct_link = result.get("link") or magnet_link or torrent_link or web_link
            size_gb = result.get("size_gb")
            if size_gb is None:
                size_bytes = result.get("size", 0) or 0
                size_gb = round(size_bytes / (1024**3), 2) if size_bytes else 0
            season_num, episode_num, episode_code, episode_sort = _extract_episode_from_title(result.get("title", ""))
            resolution_bucket = _detect_resolution_bucket(title_lower, resolution_rules)
            clean_result = {
                "title": result.get("title"),
                "size_gb": size_gb,
                "link": direct_link,
                "seeders": seeders,
                "indexer": result.get("indexer", "N/A"),
                "magnet": magnet_link,
                "torrent": torrent_link,
                "web": web_link,
                "resolution_bucket": resolution_bucket,
                "episode_code": episode_code,
                "episode_sort": episode_sort,
                "season_number": season_num,
                "episode_number": episode_num,
                "normalized_title": sanitize_title(result.get("title", "").lower())
            }
            filtered_list.append(clean_result)
        else:
            reason = "Lingua non trovata" if not lang_found else "Tag escluso"
            _record_exclusion(result, reason)

    return filtered_list
