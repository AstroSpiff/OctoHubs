import requests

from core.http_response_limits import close_response_safely, read_bounded_json_response
from core.log_sanitization import sanitize_diagnostic_text
from core.safe_output import safe_print as print
from core.outbound_redirects import response_is_redirect

from core.utils import _normalize_media_type
from emby_runtime.api_client_urls import build_jellyseerr_api_url


def _try_parse_int(value):
    """Parse value to integer if possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_tmdb_id(*sources):
    """Extract TMDB ID from multiple sources."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("tmdbId", "tmdb_id", "tmdbid", "mediaId", "media_id"):
            value = source.get(key)
            parsed = _try_parse_int(value)
            if parsed:
                return parsed
    return None


def _fetch_tmdb_payload(tmdb_id, media_type_candidates, config, cache):
    """Fetch TMDB payload from Jellyseerr API."""
    if not tmdb_id:
        return None, None

    headers = {"X-Api-Key": config["JELLYSEERR_API_KEY"]}
    tried = set()
    candidates = list(media_type_candidates or []) + ["movie", "tv"]

    for candidate in candidates:
        normalized = _normalize_media_type(candidate)
        if not normalized or normalized in tried:
            continue
        tried.add(normalized)
        cache_key = f"tmdb:{normalized}:{tmdb_id}"
        if cache_key in cache:
            return cache[cache_key], normalized
        endpoint = f"/api/v1/{normalized}/{tmdb_id}"
        try:
            response = requests.get(
                build_jellyseerr_api_url(config, endpoint),
                headers=headers,
                allow_redirects=False,
                timeout=15,
                stream=True,
            )
            if response_is_redirect(response):
                close_response_safely(response)
                continue
            if response.status_code == 404:
                close_response_safely(response)
                continue
            data = read_bounded_json_response(response)
            cache[cache_key] = data
            return data, normalized
        except requests.exceptions.RequestException:
            continue

    return None, None


def search_tmdb(api_key: str, query: str, language: str = "it-IT", page: int = 1) -> tuple:
    """
    Search TMDB for movies and TV shows with pagination support.

    Args:
        api_key: TMDB API key
        query: Search query
        language: Language code (e.g., 'it-IT', 'en-US')
        page: Page number (1-indexed)

    Returns:
        Tuple of (results_list, total_pages)
    """
    if not api_key or not query:
        return [], 0

    try:
        # TMDB multi search endpoint
        url = "https://api.themoviedb.org/3/search/multi"
        params = {
            "api_key": api_key,
            "query": query,
            "language": language,
            "include_adult": "false",
            "page": page
        }

        response = requests.get(
            url,
            params=params,
            allow_redirects=False,
            timeout=10,
            stream=True,
        )

        if response_is_redirect(response):
            close_response_safely(response)
            return [], 0

        if response.status_code != 200:
            print(f"   -> TMDB API error: {response.status_code}")
            close_response_safely(response)
            return [], 0

        data = read_bounded_json_response(response)
        results = data.get("results", [])
        total_pages = data.get("total_pages", 0)

        normalized = []
        for item in results:
            media_type = item.get("media_type")

            # Only include movies and TV shows
            if media_type not in ["movie", "tv"]:
                continue

            # Get title (different field for movies vs TV)
            title = item.get("title") if media_type == "movie" else item.get("name")

            # Get year from release_date or first_air_date
            date_field = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
            year = None
            if date_field:
                try:
                    year = int(date_field.split("-")[0])
                except (ValueError, IndexError):
                    pass

            normalized.append({
                "title": title,
                "media_type": media_type,
                "tmdb_id": item.get("id"),
                "year": year,
                "overview": item.get("overview", ""),
                "poster_path": item.get("poster_path"),
                "original_title": item.get("original_title") if media_type == "movie" else item.get("original_name")
            })

        return normalized, total_pages

    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare TMDB: {sanitize_diagnostic_text(exc)}")
        return [], 0


def get_tmdb_tv_details(api_key: str, tv_id: int, language: str = "it-IT") -> dict:
    """
    Get TV show details from TMDB including seasons.

    Args:
        api_key: TMDB API key
        tv_id: TMDB TV show ID
        language: Language code (e.g., 'it-IT', 'en-US')

    Returns:
        Dictionary with TV show details including seasons list
    """
    if not api_key or not tv_id:
        return {}

    try:
        url = f"https://api.themoviedb.org/3/tv/{tv_id}"
        params = {
            "api_key": api_key,
            "language": language
        }

        response = requests.get(
            url,
            params=params,
            allow_redirects=False,
            timeout=10,
            stream=True,
        )

        if response_is_redirect(response):
            close_response_safely(response)
            return {}

        if response.status_code != 200:
            print(f"   -> TMDB API error: {response.status_code}")
            close_response_safely(response)
            return {}

        data = read_bounded_json_response(response)

        # Extract season information
        seasons = []
        for season in data.get("seasons", []):
            season_num = season.get("season_number")
            # Skip season 0 (specials) if desired, or include it
            if season_num is not None:
                seasons.append({
                    "season_number": season_num,
                    "name": season.get("name", f"Season {season_num}"),
                    "episode_count": season.get("episode_count", 0),
                    "air_date": season.get("air_date")
                })

        return {
            "tmdb_id": data.get("id"),
            "name": data.get("name"),
            "seasons": seasons,
            "number_of_seasons": data.get("number_of_seasons", 0),
            "poster_path": data.get("poster_path")
        }

    except requests.exceptions.RequestException as exc:
        print(f"   -> Impossibile contattare TMDB: {sanitize_diagnostic_text(exc)}")
        return {}
