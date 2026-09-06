"""
Low-level enrichment fetchers for Latest Publications system.
Handles TMDB, OMDb, MDBList, and Trakt API calls with caching.
"""

import unicodedata

import requests

from core.log_sanitization import redact_mapping_for_log, sanitize_diagnostic_text
from core.safe_output import safe_print as print
from emby_latest.runtime_cache import BoundedTTLCache


TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
TMDB_SEARCH_LIMIT = 15

# Max cast members to extract from TMDB credits
_TMDB_CAST_LIMIT = 20

_TMDB_IMAGE_CACHE = BoundedTTLCache[str, dict[str, object]](max_entries=1_024, ttl_seconds=21_600)
_TMDB_FIND_CACHE = BoundedTTLCache[str, str](max_entries=2_048, ttl_seconds=21_600)
_TMDB_PERSON_CACHE = BoundedTTLCache[str, str](max_entries=2_048, ttl_seconds=86_400)
_OMDB_RATINGS_CACHE = BoundedTTLCache[str, dict[str, str]](max_entries=2_048, ttl_seconds=21_600)
_MDBLIST_RATINGS_CACHE = BoundedTTLCache[str, dict[str, str]](max_entries=2_048, ttl_seconds=21_600)
_TRAKT_RATING_CACHE = BoundedTTLCache[str, dict[str, str]](max_entries=2_048, ttl_seconds=21_600)
_TRAKT_ID_CACHE = BoundedTTLCache[str, str](max_entries=2_048, ttl_seconds=86_400)


def clear_enrichment_runtime_caches() -> None:
    for cache in (
        _TMDB_IMAGE_CACHE,
        _TMDB_FIND_CACHE,
        _TMDB_PERSON_CACHE,
        _OMDB_RATINGS_CACHE,
        _MDBLIST_RATINGS_CACHE,
        _TRAKT_RATING_CACHE,
        _TRAKT_ID_CACHE,
    ):
        cache.clear()


def _is_latin_text(text: str) -> bool:
    """Return True if the text consists mostly of Latin-script characters."""
    if not text:
        return True
    letters = [ch for ch in text if unicodedata.category(ch).startswith("L")]
    if not letters:
        return True
    latin_count = sum(1 for ch in letters if unicodedata.name(ch, "").startswith("LATIN"))
    return latin_count / len(letters) >= 0.5


def _fetch_tmdb_person_name(person_id, api_key: str, language: str = "en-US") -> str:
    """Fetch a person's name from TMDB in the specified language."""
    if not person_id or not api_key:
        return ""
    cache_key = f"{person_id}:{language}"
    if cache_key in _TMDB_PERSON_CACHE:
        return _TMDB_PERSON_CACHE[cache_key]
    try:
        url = f"{TMDB_API_BASE}/person/{person_id}"
        response = requests.get(url, params={"api_key": api_key, "language": language}, timeout=8)
        if response.status_code == 200:
            name = str(response.json().get("name") or "")
            _TMDB_PERSON_CACHE[cache_key] = name
            return name
    except requests.RequestException:
        pass
    _TMDB_PERSON_CACHE[cache_key] = ""
    return ""


def _resolve_person_name(name: str, person_id, api_key: str) -> str:
    """Return a Latin-script name, fetching the English translation from TMDB if needed."""
    if not name or _is_latin_text(name):
        return name
    if not person_id or not api_key:
        return name
    translated = _fetch_tmdb_person_name(person_id, api_key, "en-US")
    return translated if (translated and _is_latin_text(translated)) else name

# API Key rotation state
_API_KEY_ROTATION_STATE = {
    "mdblist": {"current_index": 0, "failed_keys": set()},
    "omdb": {"current_index": 0, "failed_keys": set()},
}


def _fetch_tmdb_images(tmdb_id, media_type, api_key, language):
    if not tmdb_id or not api_key:
        return {}
    key = f"{media_type}:{tmdb_id}:{language}"
    if key in _TMDB_IMAGE_CACHE:
        return _TMDB_IMAGE_CACHE[key]
    try:
        is_tv = str(media_type).lower() == "tv"
        credits_key = "aggregate_credits" if is_tv else "credits"
        params = {
            "api_key": api_key,
            "language": language or "it-IT",
            "append_to_response": f"images,external_ids,{credits_key}",
        }
        url = f"{TMDB_API_BASE}/{media_type}/{tmdb_id}"
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {}
        payload = response.json()
    except requests.RequestException:
        return {}

    is_tv = str(media_type).lower() == "tv"
    poster_path = payload.get("poster_path") or ""
    backdrop_path = payload.get("backdrop_path") or ""
    images = payload.get("images") if isinstance(payload.get("images"), dict) else {}
    logos = images.get("logos") if isinstance(images.get("logos"), list) else []
    logo_path = ""
    if logos:
        logo_path = logos[0].get("file_path") or ""
    vote_average = payload.get("vote_average")
    vote_count = payload.get("vote_count")
    rating_text = ""
    try:
        if vote_average is not None:
            rating_text = f"{float(vote_average):.1f}"
    except (TypeError, ValueError):
        rating_text = str(vote_average or "")
    output: dict[str, object] = {
        "tmdb_poster_url": f"{TMDB_IMAGE_BASE_URL}/w780{poster_path}" if poster_path else "",
        "tmdb_backdrop_url": f"{TMDB_IMAGE_BASE_URL}/w1280{backdrop_path}" if backdrop_path else "",
        "tmdb_logo_url": f"{TMDB_IMAGE_BASE_URL}/w500{logo_path}" if logo_path else "",
        "tmdb_rating": rating_text,
        "tmdb_votes": str(vote_count or ""),
    }
    output["tmdb_banner_url"] = output["tmdb_backdrop_url"]
    output["tmdb_thumb_url"] = output["tmdb_backdrop_url"]
    external_ids = payload.get("external_ids") if isinstance(payload.get("external_ids"), dict) else {}
    imdb_id = external_ids.get("imdb_id") or ""
    tvdb_id = external_ids.get("tvdb_id") or ""
    if imdb_id:
        output["imdb_id"] = str(imdb_id)
    if tvdb_id:
        output["tvdb_id"] = str(tvdb_id)

    if is_tv:
        # Creators from created_by — translate non-Latin names via /person/{id}?language=en-US
        creators_raw = payload.get("created_by")
        creators = []
        if isinstance(creators_raw, list):
            for entry in creators_raw:
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if name:
                        creators.append(_resolve_person_name(str(name), entry.get("id"), api_key))
        if creators:
            output["creators"] = creators

        # Cast from aggregate_credits
        _agg_raw = payload.get("aggregate_credits")
        agg: dict = _agg_raw if isinstance(_agg_raw, dict) else {}
        _cast_raw = agg.get("cast")
        cast_raw: list = _cast_raw if isinstance(_cast_raw, list) else []
        cast = []
        for person in cast_raw[:_TMDB_CAST_LIMIT]:
            if not isinstance(person, dict):
                continue
            name = str(person.get("name") or "")
            if name:
                cast.append(_resolve_person_name(name, person.get("id"), api_key))
        if cast:
            output["cast"] = cast

        # Directors from aggregate_credits crew
        _crew_raw = agg.get("crew")
        crew_raw: list = _crew_raw if isinstance(_crew_raw, list) else []
        directors = []
        for person in crew_raw:
            if not isinstance(person, dict):
                continue
            jobs = [j.get("job") for j in person.get("jobs", []) if isinstance(j, dict)]
            if "Director" in jobs:
                name = str(person.get("name") or "")
                if name:
                    directors.append(_resolve_person_name(name, person.get("id"), api_key))
        if directors:
            output["directors"] = directors

    else:
        # Cast from credits
        _credits_raw = payload.get("credits")
        credits: dict = _credits_raw if isinstance(_credits_raw, dict) else {}
        _cast_raw2 = credits.get("cast")
        cast_raw2: list = _cast_raw2 if isinstance(_cast_raw2, list) else []
        cast = []
        for person in cast_raw2[:_TMDB_CAST_LIMIT]:
            if not isinstance(person, dict):
                continue
            name = str(person.get("name") or "")
            if name:
                cast.append(_resolve_person_name(name, person.get("id"), api_key))
        if cast:
            output["cast"] = cast

        # Directors from credits crew
        _crew_raw2 = credits.get("crew")
        crew_raw2: list = _crew_raw2 if isinstance(_crew_raw2, list) else []
        directors = []
        for person in crew_raw2:
            if not isinstance(person, dict):
                continue
            if person.get("job") == "Director":
                name = str(person.get("name") or "")
                if name:
                    directors.append(_resolve_person_name(name, person.get("id"), api_key))
        if directors:
            output["directors"] = directors

    _TMDB_IMAGE_CACHE[key] = output
    return output


def _fetch_tmdb_id_from_external(external_id, media_type, api_key, language, external_source):
    if not external_id or not api_key:
        return ""
    key = f"find:{external_source}:{external_id}:{media_type}:{language or ''}"
    cached = _TMDB_FIND_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        params = {
            "api_key": api_key,
            "external_source": external_source,
            "language": language or "it-IT",
        }
        url = f"{TMDB_API_BASE}/find/{external_id}"
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            _TMDB_FIND_CACHE[key] = ""
            return ""
        payload = response.json()
    except requests.RequestException:
        _TMDB_FIND_CACHE[key] = ""
        return ""

    results_key = "tv_results" if str(media_type).lower() == "tv" else "movie_results"
    results = payload.get(results_key) if isinstance(payload, dict) else None
    tmdb_id = ""
    if isinstance(results, list) and results:
        tmdb_id = str(results[0].get("id") or "")
    _TMDB_FIND_CACHE[key] = tmdb_id
    return tmdb_id


def _parse_omdb_payload(payload):
    if not isinstance(payload, dict) or payload.get("Response") != "True":
        return {}
    imdb_rating = str(payload.get("imdbRating") or "")
    meta_score = str(payload.get("Metascore") or "")
    if imdb_rating.upper() == "N/A":
        imdb_rating = ""
    if meta_score.upper() == "N/A":
        meta_score = ""
    tomato_score = ""
    ratings = payload.get("Ratings")
    if isinstance(ratings, list):
        for entry in ratings:
            if not isinstance(entry, dict):
                continue
            source = entry.get("Source") or ""
            value = entry.get("Value") or ""
            if source.lower().strip() == "rotten tomatoes":
                tomato_score = str(value)
    return {
        "imdb_rating": imdb_rating,
        "metacritic_rating": meta_score,
        "rt_tomatometer": tomato_score,
        "rt_audience": "",
        "letterboxd_rating": "",
        "imdb_votes": str(payload.get("imdbVotes") or ""),
    }


def _get_next_api_key(service_name, api_keys):
    """Get next API key with rotation support."""
    if not api_keys:
        return None
    if len(api_keys) == 1:
        return api_keys[0]

    state = _API_KEY_ROTATION_STATE.get(service_name, {"current_index": 0, "failed_keys": set()})

    # Filter out failed keys
    available_keys = [k for k in api_keys if k not in state["failed_keys"]]
    if not available_keys:
        # All keys failed, reset and try again
        state["failed_keys"] = set()
        available_keys = api_keys

    # Get current key
    current_index = state["current_index"] % len(available_keys)
    key = available_keys[current_index]

    # Rotate to next key for next call
    state["current_index"] = (current_index + 1) % len(available_keys)
    _API_KEY_ROTATION_STATE[service_name] = state

    return key


def _mark_api_key_failed(service_name, api_key):
    """Mark an API key as failed for rotation."""
    if not api_key:
        return
    state = _API_KEY_ROTATION_STATE.get(service_name, {"current_index": 0, "failed_keys": set()})
    state["failed_keys"].add(api_key)
    _API_KEY_ROTATION_STATE[service_name] = state


def _parse_mdblist_payload(payload, media_type="movie"):
    """Parse MDBList API response and extract ratings."""
    if not isinstance(payload, dict):
        return {}

    # Extract ratings from MDBList response
    # Handle ratings as dict or list
    ratings = payload.get("ratings", {})

    # Convert ratings list to dict by source
    ratings_dict = {}
    if isinstance(ratings, list):
        for rating in ratings:
            if isinstance(rating, dict) and "source" in rating:
                source = rating["source"]
                ratings_dict[source] = rating.get("value")
    elif isinstance(ratings, dict):
        ratings_dict = ratings

    # Extract values from either top-level payload or ratings dict
    imdb_rating = str(payload.get("imdbrating") or ratings_dict.get("imdb") or "")
    metacritic = str(payload.get("metacritic") or ratings_dict.get("metacritic") or "")
    rt_tomatometer = str(payload.get("tomatometer") or ratings_dict.get("tomatoes") or "")
    rt_audience = str(payload.get("tomato_audience") or ratings_dict.get("tomatoesaudience") or "")
    letterboxd = str(payload.get("letterboxd") or ratings_dict.get("letterboxd") or "")

    # Get IMDb votes from ratings array or top-level
    imdb_votes = str(payload.get("imdbvotes") or "")
    if not imdb_votes and isinstance(ratings, list):
        for rating in ratings:
            if isinstance(rating, dict) and rating.get("source") == "imdb":
                imdb_votes = str(rating.get("votes") or "")
                break

    # Clean up values
    if imdb_rating and imdb_rating.upper() == "N/A":
        imdb_rating = ""
    if metacritic and metacritic.upper() == "N/A":
        metacritic = ""

    return {
        "imdb_rating": imdb_rating,
        "metacritic_rating": metacritic,
        "rt_tomatometer": rt_tomatometer,
        "rt_audience": rt_audience,
        "letterboxd_rating": letterboxd,
        "imdb_votes": imdb_votes,
    }


def _fetch_mdblist_ratings_by_imdb(imdb_id, api_keys, expected_type=None, force_refresh=False):
    """Fetch ratings from MDBList API by IMDb ID with key rotation."""
    if not imdb_id or not api_keys:
        print(
            f"[MDBLIST DEBUG] Empty imdb_id or api_keys - imdb_id={imdb_id}, "
            f"keys={len(api_keys) if api_keys else 0}"
        )
        return {}

    cache_key = f"{imdb_id}:{expected_type or ''}"
    if not force_refresh and cache_key in _MDBLIST_RATINGS_CACHE:
        print(f"[MDBLIST DEBUG] Cache hit for {cache_key}")
        return _MDBLIST_RATINGS_CACHE[cache_key]

    max_attempts = min(len(api_keys), 3)  # Try up to 3 different keys
    print(
        f"[MDBLIST DEBUG] Starting fetch for {imdb_id}, "
        f"type={expected_type}, max_attempts={max_attempts}"
    )

    for attempt in range(max_attempts):
        api_key = _get_next_api_key("mdblist", api_keys)
        if not api_key:
            print(f"[MDBLIST DEBUG] No API key available at attempt {attempt}")
            break

        try:
            url = "https://mdblist.com/api/"
            params = {"apikey": api_key, "i": imdb_id}
            print(
                f"[MDBLIST DEBUG] Attempt {attempt + 1}: GET {url} "
                f"with params {{'apikey': '***', 'i': '{imdb_id}'}}"
            )

            response = requests.get(url, params=params, timeout=10)
            print(f"[MDBLIST DEBUG] Response status: {response.status_code}")
            print(
                "[MDBLIST DEBUG] Response headers: "
                f"{redact_mapping_for_log(dict(response.headers))}"
            )

            response.raise_for_status()

            raw_text = response.text
            print(
                "[MDBLIST DEBUG] Raw response (first 500 chars): "
                f"{sanitize_diagnostic_text(raw_text[:500], max_length=500)}"
            )

            payload = response.json()
            print(
                "[MDBLIST DEBUG] Parsed JSON payload: "
                f"{redact_mapping_for_log(payload)}"
            )

            if not isinstance(payload, dict):
                print(
                    "[MDBLIST DEBUG] Invalid payload type "
                    f"({type(payload).__name__}) - falling back"
                )
                return {}

            # Check if the response is valid
            if not payload.get("error"):
                print("[MDBLIST DEBUG] Valid payload received, no error field")

                # Verify media type if expected
                if expected_type:
                    actual_type = str(payload.get("type") or "").lower()
                    expected = "show" if expected_type in ("tv", "series") else "movie"
                    print(f"[MDBLIST DEBUG] Type check: actual={actual_type}, expected={expected}")
                    if actual_type and actual_type != expected:
                        print("[MDBLIST DEBUG] Type mismatch - returning empty")
                        return {}

                output = _parse_mdblist_payload(payload, expected_type or "movie")
                print(f"[MDBLIST DEBUG] Parsed output: {output}")
                _MDBLIST_RATINGS_CACHE[cache_key] = output
                return output

            # Check for rate limit errors
            if payload.get("error"):
                print(
                    "[MDBLIST DEBUG] Error in payload: "
                    f"{sanitize_diagnostic_text(payload.get('error'))}"
                )
                if "limit" in str(payload.get("error")).lower():
                    print("[MDBLIST DEBUG] Rate limit detected, marking key as failed")
                    _mark_api_key_failed("mdblist", api_key)
                    continue

            print("[MDBLIST DEBUG] Payload has error or is invalid, returning empty")
            return {}
        except (requests.RequestException, ValueError) as e:
            print(
                f"[MDBLIST DEBUG] Request exception at attempt {attempt + 1}: "
                f"{type(e).__name__}: {sanitize_diagnostic_text(e)}"
            )
            continue

    return {}


def _fetch_mdblist_tv_series_with_seasons(imdb_id, api_keys, force_refresh=False):
    """
    Fetch TV series ratings from MDBList including season-level Metacritic scores.
    Returns ratings with averaged Metacritic score across all seasons.
    """
    if not imdb_id or not api_keys:
        print("[MDBLIST TV DEBUG] Empty imdb_id or api_keys")
        return {}

    print(f"[MDBLIST TV DEBUG] Fetching TV series {imdb_id}")

    # First get the main series data
    series_ratings = _fetch_mdblist_ratings_by_imdb(
        imdb_id,
        api_keys,
        expected_type="tv",
        force_refresh=force_refresh,
    )
    print(f"[MDBLIST TV DEBUG] Initial series ratings: {series_ratings}")

    # Try to fetch season data to calculate average Metacritic
    api_key = _get_next_api_key("mdblist", api_keys)
    if not api_key:
        print("[MDBLIST TV DEBUG] No API key available for season fetch")
        return series_ratings

    try:
        # MDBList provides season data in the main response
        print(f"[MDBLIST TV DEBUG] Fetching season data for {imdb_id}")
        response = requests.get(
            "https://mdblist.com/api/",
            params={"apikey": api_key, "i": imdb_id},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        print(
            "[MDBLIST TV DEBUG] Season payload type: "
            f"{type(payload)}, has error: {payload.get('error') if isinstance(payload, dict) else 'N/A'}"
        )

        if not isinstance(payload, dict) or payload.get("error"):
            print("[MDBLIST TV DEBUG] Invalid payload or error, returning series_ratings")
            return series_ratings

        # Check for season ratings
        seasons = payload.get("seasons") or []
        print(f"[MDBLIST TV DEBUG] Found {len(seasons) if isinstance(seasons, list) else 0} seasons")

        if isinstance(seasons, list) and seasons:
            metacritic_scores = []
            for idx, season in enumerate(seasons):
                if not isinstance(season, dict):
                    continue

                # Check both direct metacritic field and ratings array
                season_meta = season.get("metacritic")
                if not season_meta and "ratings" in season:
                    ratings = season.get("ratings")
                    if isinstance(ratings, list):
                        for rating in ratings:
                            if isinstance(rating, dict) and rating.get("source") == "metacritic":
                                season_meta = rating.get("value")
                                break
                    elif isinstance(ratings, dict):
                        season_meta = ratings.get("metacritic")

                print(f"[MDBLIST TV DEBUG] Season {idx + 1} metacritic: {season_meta}")

                if season_meta:
                    try:
                        score = float(season_meta)
                        if score > 0:
                            metacritic_scores.append(score)
                    except (TypeError, ValueError):
                        continue

            # Calculate average if we have season scores
            if metacritic_scores:
                avg_metacritic = sum(metacritic_scores) / len(metacritic_scores)
                series_ratings["metacritic_rating"] = str(int(round(avg_metacritic)))
                print(
                    "[MDBLIST TV DEBUG] Calculated average Metacritic: "
                    f"{series_ratings['metacritic_rating']} from {len(metacritic_scores)} seasons"
                )
            else:
                print("[MDBLIST TV DEBUG] No valid Metacritic scores found in seasons")
    except requests.RequestException as e:
        print(
            f"[MDBLIST TV DEBUG] Request exception: {type(e).__name__}: "
            f"{sanitize_diagnostic_text(e)}"
        )
        pass

    print(f"[MDBLIST TV DEBUG] Final TV series ratings: {series_ratings}")
    return series_ratings


def _fetch_omdb_series_by_title(title, year, api_keys, force_refresh=False):
    """Fetch OMDb series by title with API key rotation support."""
    if not title:
        return {}

    # Support both single key (string) and multiple keys (list) for backward compatibility
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not api_keys:
        return {}

    key = f"series:{title}:{year or ''}"
    if not force_refresh and key in _OMDB_RATINGS_CACHE:
        return _OMDB_RATINGS_CACHE[key]

    max_attempts = min(len(api_keys), 3)
    for attempt in range(max_attempts):
        api_key = _get_next_api_key("omdb", api_keys)
        if not api_key:
            break

        try:
            params = {"t": title, "type": "series", "apikey": api_key}
            if year:
                params["y"] = year
            response = requests.get("https://www.omdbapi.com/", params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                continue

            if payload.get("Response") != "True":
                # Check for rate limit
                error = str(payload.get("Error") or "").lower()
                if "limit" in error:
                    _mark_api_key_failed("omdb", api_key)
                    continue
                return {}

            if str(payload.get("Type") or "").lower() != "series":
                return {}

            output = _parse_omdb_payload(payload)
            imdb_id = str(payload.get("imdbID") or "")
            if imdb_id:
                output["imdb_id"] = imdb_id
            _OMDB_RATINGS_CACHE[key] = output
            return output
        except (requests.RequestException, ValueError):
            continue

    return {}


def _fetch_omdb_ratings(imdb_id, api_keys, expected_type=None, force_refresh=False):
    """
    Recupera rating da OMDb API with key rotation support.

    NOTA LIMITAZIONI OMDB PER SERIE TV:
    - Metacritic: Spesso assente per serie TV (dipende da OMDb database)
    - RT Tomatometer: Raramente disponibile per serie TV
    - IMDb rating/votes: Generalmente disponibili

    Per film, tutti i rating sono generalmente disponibili.
    """
    # Support both single key (string) and multiple keys (list) for backward compatibility
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not imdb_id or not api_keys:
        return {}

    cache_key = f"{imdb_id}:{expected_type or ''}"
    if not force_refresh and cache_key in _OMDB_RATINGS_CACHE:
        return _OMDB_RATINGS_CACHE[cache_key]

    max_attempts = min(len(api_keys), 3)
    for attempt in range(max_attempts):
        api_key = _get_next_api_key("omdb", api_keys)
        if not api_key:
            break

        def _request_omdb(identifier):
            try:
                response = requests.get(
                    "https://www.omdbapi.com/",
                    params={"i": identifier, "apikey": api_key},
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                return None
            if not isinstance(payload, dict):
                return None
            if payload.get("Response") != "True":
                # Check for rate limit
                error = str(payload.get("Error") or "").lower()
                if "limit" in error:
                    _mark_api_key_failed("omdb", api_key)
                return None
            return payload

        payload = _request_omdb(imdb_id)
        if payload is None:
            continue

        resolved_imdb_id = str(imdb_id)
        if expected_type:
            expected = "series" if expected_type in ("tv", "series") else "movie"
            actual = str(payload.get("Type") or "").lower()
            if expected == "series" and actual == "episode":
                series_id = payload.get("seriesID") or payload.get("seriesId") or payload.get("series_id") or ""
                if series_id:
                    series_payload = _request_omdb(series_id)
                    if series_payload:
                        payload = series_payload
                        resolved_imdb_id = str(series_id)
                        actual = str(payload.get("Type") or "").lower()
                if actual != "series":
                    return {}
            elif actual and actual != expected:
                return {}

        output = _parse_omdb_payload(payload)
        if expected_type in ("tv", "series") and resolved_imdb_id:
            output["imdb_id"] = resolved_imdb_id
        _OMDB_RATINGS_CACHE[cache_key] = output
        return output

    return {}


def _resolve_trakt_identifier(trakt_id, media_type, client_id, access_token=None, tmdb_id=None, imdb_id=None):
    if trakt_id:
        return str(trakt_id).strip()
    if not client_id:
        return ""
    cache_key = f"{media_type}:{tmdb_id or ''}:{imdb_id or ''}"
    cached = _TRAKT_ID_CACHE.get(cache_key)
    if cached:
        return cached
    search_type = "show" if media_type == "tv" else "movie"
    headers = {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "OctoHubs/1.0 (+https://github.com/AstroSpiff/OctoHubs)",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    url = ""
    params = {"type": search_type}
    if imdb_id:
        url = f"https://api.trakt.tv/search/imdb/{imdb_id}"
    elif tmdb_id:
        url = f"https://api.trakt.tv/search/tmdb/{tmdb_id}"
    if not url:
        return ""
    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ""
    identifier = ""
    if isinstance(payload, list):
        for entry in payload:
            media = entry.get(search_type) if isinstance(entry, dict) else None
            ids = media.get("ids") if isinstance(media, dict) else None
            if not ids:
                continue
            identifier = ids.get("slug") or ids.get("trakt") or ids.get("imdb") or ids.get("tmdb") or ""
            if identifier:
                break
    if identifier:
        _TRAKT_ID_CACHE[cache_key] = str(identifier)
    return str(identifier or "")


def _fetch_trakt_rating(trakt_id, media_type, client_id, access_token=None, tmdb_id=None, imdb_id=None):
    if not client_id:
        return {}
    trakt_id = _resolve_trakt_identifier(
        trakt_id,
        media_type,
        client_id,
        access_token=access_token,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
    )
    if not trakt_id:
        return {}
    key = f"{media_type}:{trakt_id}"
    if key in _TRAKT_RATING_CACHE:
        return _TRAKT_RATING_CACHE[key]
    trakt_type = "shows" if media_type == "tv" else "movies"
    url = f"https://api.trakt.tv/{trakt_type}/{trakt_id}"
    headers = {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "OctoHubs/1.0 (+https://github.com/AstroSpiff/OctoHubs)",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        response = requests.get(
            url,
            headers=headers,
            params={"extended": "full"},
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}
    rating = payload.get("rating")
    rating_text = ""
    try:
        if rating is not None:
            rating_text = f"{float(rating):.1f}"
    except (TypeError, ValueError):
        rating_text = str(rating or "")
    output = {
        "trakt_rating": rating_text,
        "trakt_votes": str(payload.get("votes") or ""),
    }
    if trakt_id:
        output["trakt_id"] = str(trakt_id)
    _TRAKT_RATING_CACHE[key] = output
    return output
