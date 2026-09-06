"""
Message building for Latest Publications notifications.

This module handles message template resolution and rendering.
Migrated from legacy monolith message functions.
"""

import html
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from core.utils import _parse_date_value
from emby_latest.templates import (
    render_template,
    strip_image_tokens,
    extract_image_url,
    apply_template
)

# NOTE: _sort_versions_by_quality imported lazily inside functions to avoid circular import


def format_date(value: Any) -> str:
    """
    Format date value to DD.MM.'YY format.

    Args:
        value: Date value (ISO string or datetime)

    Returns:
        Formatted date string
    """
    parsed = _parse_date_value(value)
    if not parsed:
        return ""
    local = parsed.astimezone()
    return f"{local.day:02d}.{local.month:02d}.'{local.year % 100:02d}"


def format_runtime(minutes: Optional[int]) -> str:
    """
    Format runtime in minutes to "Xh Ym" format.

    Args:
        minutes: Runtime in minutes

    Returns:
        Formatted runtime string
    """
    if minutes is None:
        return ""
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours = total // 60
    mins = total % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def format_size(value: Optional[int]) -> str:
    """
    Format file size in bytes to "X.XX GB" or "X MB" format.

    Args:
        value: Size in bytes

    Returns:
        Formatted size string
    """
    if value is None:
        return ""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    gb = size / (1024 * 1024 * 1024)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = size / (1024 * 1024)
    return f"{mb:.0f} MB"


def _format_episode_ranges(episode_codes: list) -> str:
    """Format episode codes into compact range notation.

    Groups by season, finds consecutive ranges within each season.
    Examples:
      ["S01E01", "S01E02", "S01E05"]  -> "S01E01-02 | S01E05"
      ["S01E01", "S01E02", "S01E03"]  -> "S01E01-03"
      ["S01E01", "S02E01", "S02E02"]  -> "S01E01 | S02E01-02"
    """
    import re
    from itertools import groupby

    parsed = []
    for code in episode_codes:
        m = re.match(r"S(\d+)E(\d+)", code)
        if m:
            parsed.append((int(m.group(1)), int(m.group(2))))
        else:
            return ", ".join(episode_codes)

    if not parsed:
        return ""

    parsed.sort()
    result_parts = []
    for season, group in groupby(parsed, key=lambda x: x[0]):
        ep_list = sorted(set(e for _, e in group))
        start = end = ep_list[0]
        for ep in ep_list[1:]:
            if ep == end + 1:
                end = ep
            else:
                if start == end:
                    result_parts.append(f"S{season:02d} E{start:02d}")
                else:
                    result_parts.append(f"S{season:02d} E{start:02d}-{end:02d}")
                start = end = ep
        if start == end:
            result_parts.append(f"S{season:02d} E{start:02d}")
        else:
            result_parts.append(f"S{season:02d} E{start:02d}-{end:02d}")

    return " | ".join(result_parts)


def build_message(
    item: Dict[str, Any],
    template: str,
    return_error: bool = False,
    allow_fallback: bool = True
) -> Tuple[str, str] | Tuple[str, str, Optional[str]]:
    """
    Build notification message for an item using a template.

    Args:
        item: Item dict (movie or series) with metadata and changes
        template: Message template string
        return_error: If True, return error message on failure
        allow_fallback: If True, use fallback template on error

    Returns:
        Tuple of (rendered_message, image_url) or (rendered_message, image_url, error) if return_error=True
    """
    # Lazy import to avoid circular dependency
    from emby_latest.batch_processor import _sort_versions_by_quality

    # Extract changes and version information
    raw_changes = item.get("changes")
    changes = [entry for entry in raw_changes if isinstance(entry, dict)] if isinstance(raw_changes, list) else []
    change = changes[0] if changes else {}
    change_entries = list(changes)
    versions_sorted = _sort_versions_by_quality(change_entries)
    best_version = versions_sorted[0] if versions_sorted else {}

    # Count seasons and episodes
    season_numbers = {entry.get("season_number") for entry in changes if entry.get("season_number") is not None}
    episode_numbers = [entry.get("episode_number") for entry in changes if entry.get("episode_number") is not None]
    season_count = len(season_numbers) if season_numbers else ""
    episode_count = len(episode_numbers) if episode_numbers else ""

    # Determine media type
    raw_type = item.get("item_type") or ""
    type_token = str(raw_type).lower()
    if type_token == "movie":
        type_token = "movie"
    elif type_token == "series":
        type_token = "series"
    elif type_token == "episode":
        type_token = "episode"

    # Extract series/episode info
    series_name = item.get("series_name") or ""
    if not series_name and str(raw_type).lower() == "series":
        series_name = item.get("title") or ""

    season_number = change.get("season_number") or item.get("season_number") or ""
    season_name = item.get("season_name") or ""
    episode_number = change.get("episode_number") or item.get("episode_number") or ""
    episode_title = change.get("episode_title") or item.get("episode_title") or ""

    # Format studios
    studios = item.get("studios") or []
    if isinstance(studios, list):
        studios_text = " · ".join([str(entry) for entry in studios if entry])
    else:
        studios_text = str(studios or "")

    # Format cast, directors and creators
    cast_raw = list(item.get("cast") or []) if isinstance(item.get("cast"), list) else []
    director_raw = list(item.get("directors") or []) if isinstance(item.get("directors"), list) else []
    creator_raw = list(item.get("creators") or []) if isinstance(item.get("creators"), list) else []

    cast_list = []
    for entry in cast_raw:
        if entry and str(entry) not in cast_list:
            cast_list.append(str(entry))

    director_list = []
    for entry in director_raw:
        if entry and str(entry) not in director_list:
            director_list.append(str(entry))

    creator_list = []
    for entry in creator_raw:
        if entry and str(entry) not in creator_list:
            creator_list.append(str(entry))
    creators_text = " · ".join(creator_list)

    cast_default_limit = 5
    cast_text = " · ".join(cast_list[:cast_default_limit])
    cast_full_text = " · ".join(cast_list)
    director_text = director_list[0] if director_list else ""
    directors_text = " · ".join(director_list)

    # Build episode codes and titles
    episode_codes = []
    episode_titles = []
    seen_episodes = set()

    for entry in changes:
        season_number_entry = entry.get("season_number")
        episode_number_entry = entry.get("episode_number")
        if season_number_entry is None and episode_number_entry is None:
            continue

        try:
            season_int = int(season_number_entry) if season_number_entry is not None else None
        except (TypeError, ValueError):
            season_int = None

        try:
            episode_int = int(episode_number_entry) if episode_number_entry is not None else None
        except (TypeError, ValueError):
            episode_int = None

        code = ""
        if season_int is not None:
            code += f"S{season_int:02d}"
        if episode_int is not None:
            code += f"E{episode_int:02d}"

        if not code:
            continue

        key = (season_int, episode_int)
        if key in seen_episodes:
            continue
        seen_episodes.add(key)

        episode_codes.append(code)
        title_entry = entry.get("episode_title") or ""
        if title_entry:
            episode_titles.append(f"{code} - {title_entry}")
        else:
            episode_titles.append(code)

    # Build external URLs
    tmdb_id = str(item.get("tmdb_id") or "")
    imdb_id = str(item.get("imdb_id") or "")
    tvdb_id = str(item.get("tvdb_id") or "")
    trakt_id = str(item.get("trakt_id") or "")

    tmdb_url = f"https://www.themoviedb.org/{'tv' if type_token == 'series' else 'movie'}/{tmdb_id}" if tmdb_id else ""
    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else ""
    tvdb_url = f"https://thetvdb.com/?id={tvdb_id}" if tvdb_id else ""

    trakt_url = ""
    if trakt_id:
        trakt_url = f"https://trakt.tv/{'shows' if type_token == 'series' else 'movies'}/{trakt_id}"
    elif imdb_id:
        trakt_url = f"https://trakt.tv/search/imdb/{imdb_id}"
    elif tmdb_id:
        trakt_url = f"https://trakt.tv/search/tmdb/{tmdb_id}"

    # Build complete context
    context_raw = {
        "title": str(item.get("title") or ""),
        "original_title": str(item.get("original_title") or ""),
        "year": str(item.get("year") or ""),
        "type": type_token,
        "server": str(item.get("server_name") or ""),
        "update_label": str(item.get("update_label") or ""),
        "update_type": str(item.get("update_type") or ""),
        "added_at": format_date(change.get("added_at") or item.get("added_at")),
        "genres": " · ".join(item.get("genres") or []) if isinstance(item.get("genres"), list) else "",
        "overview": str(item.get("overview") or ""),
        "rating": str(item.get("community_rating") or ""),
        "critic_rating": str(item.get("critic_rating") or ""),
        "official_rating": str(item.get("official_rating") or ""),
        "runtime": format_runtime(item.get("runtime_minutes")),
        "quality": str(change.get("quality") or ""),
        "resolution": str(change.get("resolution") or ""),
        "video_codec": str(change.get("video_codec") or ""),
        "audio_codec": str(change.get("audio_codec") or ""),
        "audio_channels": str(change.get("audio_channels") or ""),
        "container": str(change.get("container") or ""),
        "bitrate": str(change.get("bitrate") or ""),
        "versions": versions_sorted,
        "version_count": str(len(versions_sorted)),
        "best_version": best_version,
        "best_quality": str(best_version.get("quality") or ""),
        "best_resolution": str(best_version.get("resolution") or ""),
        "best_video_codec": str(best_version.get("video_codec") or ""),
        "best_audio_codec": str(best_version.get("audio_codec") or ""),
        "best_audio_channels": str(best_version.get("audio_channels") or ""),
        "best_container": str(best_version.get("container") or ""),
        "best_bitrate": str(best_version.get("bitrate") or ""),
        "best_source_name": str(best_version.get("source_name") or ""),
        "best_path": str(best_version.get("path") or ""),
        "best_size": str(best_version.get("size") or ""),
        "best_video_details": str(best_version.get("video_details") or ""),
        "best_audio_details": str(best_version.get("audio_details") or ""),
        "best_audio_langs": str(best_version.get("audio_langs") or ""),
        "best_subtitle_langs": str(best_version.get("subtitle_langs") or ""),
        "best_season_number": str(best_version.get("season_number") or ""),
        "best_episode_number": str(best_version.get("episode_number") or ""),
        "best_episode_title": str(best_version.get("episode_title") or ""),
        "series_name": str(series_name),
        "season_number": str(season_number),
        "season_name": str(season_name),
        "episode_number": str(episode_number),
        "episode_title": str(episode_title),
        "season": str(season_number),
        "episode": str(episode_number),
        "season_count": str(season_count),
        "episode_count": str(episode_count or item.get("child_count") or ""),
        "size": format_size(change.get("size")),
        "path": str(change.get("path") or ""),
        "source_name": str(change.get("source_name") or ""),
        "batch_id": str(item.get("batch_id") or ""),
        "tagline": str(item.get("tagline") or ""),
        "studios": studios_text,
        "production": studios_text,
        "production_companies": studios_text,
        "cast": cast_text,
        "cast_all": cast_full_text,
        "director": director_text,
        "directors": directors_text,
        "creators": creators_text,
        "episodes": ", ".join(episode_codes),
        "episodes_compact": _format_episode_ranges(episode_codes),
        "episodes_with_titles": " · ".join(episode_titles),
        "library": str(item.get("library_name") or ""),
        "library_name": str(item.get("library_name") or ""),
        "image_url": str(item.get("image_url") or ""),
        "poster_url": str(item.get("poster_url") or ""),
        "backdrop_url": str(item.get("backdrop_url") or ""),
        "banner_url": str(item.get("banner_url") or ""),
        "thumb_url": str(item.get("thumb_url") or ""),
        "logo_url": str(item.get("logo_url") or ""),
        "tmdb_poster_url": str(item.get("tmdb_poster_url") or ""),
        "tmdb_backdrop_url": str(item.get("tmdb_backdrop_url") or ""),
        "tmdb_logo_url": str(item.get("tmdb_logo_url") or ""),
        "tmdb_banner_url": str(item.get("tmdb_banner_url") or ""),
        "tmdb_thumb_url": str(item.get("tmdb_thumb_url") or ""),
        "emby_url": str(item.get("emby_url") or ""),
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "tvdb_id": tvdb_id,
        "trakt_id": trakt_id,
        "tmdb_url": tmdb_url,
        "imdb_url": imdb_url,
        "tvdb_url": tvdb_url,
        "trakt_url": trakt_url,
        "premiere_date": format_date(item.get("premiere_date")),
        "tmdb_rating": str(item.get("tmdb_rating") or ""),
        "imdb_rating": str(item.get("imdb_rating") or ""),
        "trakt_rating": str(item.get("trakt_rating") or ""),
        "rt_tomatometer": str(item.get("rt_tomatometer") or ""),
        "rt_audience": str(item.get("rt_audience") or ""),
        "metacritic_rating": str(item.get("metacritic_rating") or ""),
        "letterboxd_rating": str(item.get("letterboxd_rating") or ""),
        "jellyseerr_request_id": str(item.get("jellyseerr_request_id") or ""),
        "jellyseerr_request_status": str(item.get("jellyseerr_request_status") or ""),
        "jellyseerr_request_status_label": str(item.get("jellyseerr_request_status_label") or ""),
        "jellyseerr_requested_by": str(item.get("jellyseerr_requested_by") or ""),
        "jellyseerr_requested": str(item.get("jellyseerr_requested") or ""),
        "video_details": str(change.get("video_details") or item.get("video_details") or ""),
        "audio_details": str(change.get("audio_details") or item.get("audio_details") or ""),
        "audio_ita": str(change.get("audio_ita") or item.get("audio_ita") or ""),
        "audio_eng": str(change.get("audio_eng") or item.get("audio_eng") or ""),
        "audio_fra": str(change.get("audio_fra") or item.get("audio_fra") or ""),
        "audio_spa": str(change.get("audio_spa") or item.get("audio_spa") or ""),
        "audio_ger": str(change.get("audio_ger") or item.get("audio_ger") or ""),
        "audio_jpn": str(change.get("audio_jpn") or item.get("audio_jpn") or ""),
        "audio_langs": str(change.get("audio_langs") or item.get("audio_langs") or ""),
        "subtitle_langs": str(change.get("subtitle_langs") or item.get("subtitle_langs") or "")
    }

    # Add cast_N variants for different limits
    for limit in range(1, 21):
        context_raw[f"cast_{limit}"] = " · ".join(cast_list[:limit])

    # Extract image URL first
    image_url = extract_image_url(template, context_raw)

    # Prepare both raw and HTML-escaped contexts
    context = {}
    context_escaped = {}
    for key, value in context_raw.items():
        raw_value = "" if value is None else value
        context[key] = raw_value
        context_escaped[key] = html.escape(str(raw_value), quote=True)

    # Remove image tokens from template
    sanitized_template = strip_image_tokens(template)

    # Try to render template
    template_error = None
    try:
        message = render_template(sanitized_template, context, strict=True)
    except Exception as exc:
        template_error = str(exc)
        if allow_fallback:
            # Fall back to simple string replacement
            message = apply_template(sanitized_template, context_escaped)
        else:
            message = ""

    # Clean up whitespace
    lines = [line.rstrip() for line in message.splitlines()]
    rendered = "\n".join(lines).strip()

    if return_error:
        return rendered, image_url, template_error
    return rendered, image_url


def resolve_message_preset(latest_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve active message preset from settings.

    Args:
        latest_settings: Latest publications settings dict

    Returns:
        Preset dict with template
    """
    presets = latest_settings.get("PRESETS") or []
    active_id = latest_settings.get("ACTIVE_PRESET_ID") or ""
    if isinstance(active_id, str):
        active_id = active_id.strip()

    for preset in presets:
        if preset.get("id") == active_id:
            return preset

    return presets[0] if presets else {"template": default_message_template()}


def default_message_template() -> str:
    """
    Get default message template.

    Returns:
        Default template string with common tokens
    """
    return "\n".join([
        "🎬 {{ title }} ({{ year }})",
        "🆕 {{ update_label }} · {{ type }}",
        "🟢 {{ server }}",
        "⭐ {{ rating }} · {{ official_rating }}",
        "⏱ {{ runtime }}",
        "🎞 {{ quality }} {{ video_codec }} {{ audio_codec }}",
        "📅 {{ added_at }}",
        "{{ genres }}",
        "{{ overview }}",
        "{{ poster_url }}"
    ])


def default_message_preset() -> Dict[str, Any]:
    """
    Create default message preset.

    Returns:
        Default preset dict with template and metadata
    """
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": "Preset Base",
        "template": default_message_template(),
        "created_at": now_stamp,
        "updated_at": now_stamp
    }
