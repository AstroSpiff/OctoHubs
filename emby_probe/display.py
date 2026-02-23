from __future__ import annotations

import os
import re
from typing import Any, Dict


def _extract_source_label(path: str | None, source_name: str | None) -> str:
    if source_name:
        return str(source_name).strip()
    if path:
        base = os.path.basename(path)
        if base.lower().endswith(".strm"):
            base = base[:-5]
        return base.strip()
    return ""


def _strip_wrapping_parens(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("(") and cleaned.endswith(")") and len(cleaned) > 2:
        return cleaned[1:-1].strip()
    return cleaned


def _strip_leading_year(value: str, year: int | None) -> str:
    if not year or not value:
        return value
    cleaned = value.strip()
    year_str = str(year)
    while True:
        candidate = cleaned.strip()
        removed = False
        for prefix in (f"({year_str})", f"[{year_str}]", year_str):
            if candidate.startswith(prefix):
                cleaned = candidate[len(prefix):].lstrip()
                cleaned = cleaned.lstrip("-:").lstrip()
                removed = True
                break
        if not removed:
            break
    return cleaned


def _normalize_movie_display_name(name: str, year: int) -> str:
    year_tag = f"({year})"
    if year_tag not in name:
        return name
    prefix, _, remainder = name.partition(year_tag)
    title = prefix.strip()
    rest = remainder.strip()
    if rest.startswith("-"):
        rest = rest[1:].strip()
    rest = _strip_leading_year(rest, year)
    rest = _strip_wrapping_parens(rest)
    rest = _strip_leading_year(rest, year)
    if rest:
        return f"{title} {year_tag} - {rest}".strip()
    return f"{title} {year_tag}".strip()


def _movie_label_from_path(path: str | None, year: int | None) -> str | None:
    if not path:
        return None
    source_label = _extract_source_label(path, None)
    if not source_label or not year:
        return None
    year_tag = f"({year})"
    if f"{year_tag} -" in source_label:
        return _normalize_movie_display_name(source_label, year)
    return None


def _inject_year_into_series_name(name: str, series_name: str, year: int) -> str:
    if not name or not series_name:
        return name
    year_tag = f"({year})"
    if not name.lower().startswith(series_name.lower()):
        return name
    remainder = name[len(series_name):].lstrip()
    if remainder.startswith(year_tag):
        return name
    if remainder.startswith("-"):
        remainder = remainder[1:].lstrip()
        return f"{series_name} {year_tag} - {remainder}"
    if remainder:
        return f"{series_name} {year_tag} {remainder}"
    return f"{series_name} {year_tag}"


def _format_movie_name(title: str, year: int | None, source_label: str) -> str:
    base_title = title or "Titolo"
    if year:
        year_tag = f"({year})"
        if year_tag.lower() not in base_title.lower():
            base_title = f"{base_title} {year_tag}"
    info = ""
    if source_label:
        normalized = source_label.strip()
        if base_title and normalized.lower().startswith(base_title.lower()):
            remainder = normalized[len(base_title):].strip()
            if remainder.startswith("-"):
                remainder = remainder[1:].strip()
            info = remainder
        else:
            title_only = title or ""
            if title_only and normalized.lower().startswith(title_only.lower()):
                remainder = normalized[len(title_only):].strip()
                year_tag = f"({year})" if year else ""
                if year_tag and remainder.startswith(year_tag):
                    remainder = remainder[len(year_tag):].strip()
                if remainder.startswith("-"):
                    remainder = remainder[1:].strip()
                info = remainder
            elif " - " in normalized and title_only and title_only.lower() in normalized.lower():
                parts = [part.strip() for part in normalized.split(" - ") if part.strip()]
                if parts and title_only.lower() in parts[0].lower():
                    info = " - ".join(parts[1:])
    if info:
        info = _strip_wrapping_parens(info)
        info = _strip_leading_year(info, year)
    return f"{base_title} - {info}".strip(" -") if info else base_title


def _format_episode_name(
    series_name: str | None,
    season_number: int | None,
    episode_number: int | None,
    episode_title: str | None,
    source_label: str,
    year: int | None
) -> str:
    code = ""
    if season_number is not None and episode_number is not None:
        code = f"S{int(season_number):02d}E{int(episode_number):02d}"
    series_label = series_name
    if series_label and year:
        year_tag = f"({year})"
        if year_tag.lower() not in series_label.lower():
            series_label = f"{series_label} {year_tag}"
    info = ""
    if source_label:
        normalized = source_label.strip()
        match = re.search(r"S\\d{1,2}E\\d{1,2}", normalized, re.IGNORECASE)
        if match:
            remainder = normalized[match.end():].strip(" -")
            if episode_title and remainder.lower().startswith(str(episode_title).lower()):
                remainder = remainder[len(str(episode_title)):].strip(" -")
            info = remainder
        elif series_name and normalized.lower().startswith(series_name.lower()):
            remainder = normalized[len(series_name):].strip(" -")
            if year:
                year_tag = f"({year})"
                if remainder.startswith(year_tag):
                    remainder = remainder[len(year_tag):].strip(" -")
            if code and remainder.upper().startswith(code.upper()):
                remainder = remainder[len(code):].strip(" -")
            if episode_title and remainder.lower().startswith(str(episode_title).lower()):
                remainder = remainder[len(str(episode_title)):].strip(" -")
            info = remainder

    parts = [part for part in [series_label, code, episode_title] if part]
    label = " - ".join(parts)
    if info:
        info = _strip_wrapping_parens(info)
        if info:
            label = f"{label} - {info}" if label else info
    return label or (episode_title or "Episodio")


def _format_probe_display_name(
    media_type: str | None,
    item_name: str,
    year: int | None,
    series_name: str | None,
    season_number: int | None,
    episode_number: int | None,
    path: str | None,
    source_name: str | None
) -> str:
    source_label = _extract_source_label(path, source_name)
    media_kind = (media_type or "").lower()
    if series_name or media_kind == "episode":
        return _format_episode_name(series_name, season_number, episode_number, item_name, source_label, year)
    return _format_movie_name(item_name, year, source_label)


def _format_display_name_from_queue(queue_item: Dict[str, Any]) -> str:
    name = queue_item.get("name") or ""
    media_type = queue_item.get("media_type")
    series_name = queue_item.get("series_name")
    season_number = queue_item.get("season_number")
    episode_number = queue_item.get("episode_number")
    year = queue_item.get("year")
    path = queue_item.get("path")
    media_kind = str(media_type or "").lower()

    if media_kind == "movie":
        movie_from_path = _movie_label_from_path(path, year)
        if movie_from_path:
            return movie_from_path
    if media_kind == "episode":
        name_with_year = _inject_year_into_series_name(name, series_name or "", year) if year else name
        if name_with_year:
            name = name_with_year
    if not name:
        name = queue_item.get("title") or queue_item.get("item_name") or ""
    if not name and path:
        name = _extract_source_label(path, None)

    if name:
        computed = _format_probe_display_name(
            media_type,
            name,
            year,
            series_name,
            season_number,
            episode_number,
            path,
            queue_item.get("source_name")
        )
        if computed:
            return computed

    return _format_probe_display_name(
        media_type,
        "Titolo",
        year,
        series_name,
        season_number,
        episode_number,
        path,
        queue_item.get("source_name")
    )
