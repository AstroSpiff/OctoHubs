"""Latest cache/state storage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    EmbyLatestCacheMeta,
    EmbyLatestCacheItem,
    EmbyLatestCacheChange,
    EmbyLatestCacheError,
    EmbyLatestStateMovie,
    EmbyLatestStateSeries,
    EmbyLatestStateEpisode,
    EmbyLatestStateSeriesGroup,
    EmbyLatestStateSeriesChange,
    EmbyLatestProgress,
    _utcnow,
)
from core.storage.storage_utils import (
    _parse_datetime_value,
    _normalize_text_array,
    _normalize_int_array,
    _parse_int,
    _normalize_text_value,
    _truncate_text_value,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageLatestMixin(_SessionProvider):
    def _normalize_latest_cache_kind(self, cache_kind: Optional[str]) -> str:
        value = str(cache_kind or "").strip().lower()
        if value in ("history", "latest_history", "batch_history"):
            return "batch"
        if value in ("feed", "feed_cache", "cache_feed", "latest_feed"):
            return "feed"
        if value in ("batch", "cache", "latest", "latest_cache"):
            return "batch"
        return "feed"

    # --- Emby latest cache ---

    def _latest_cache_item_to_dict(self, row: Any, changes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        def _dt(value: Optional[datetime]) -> Optional[str]:
            return value.isoformat() if isinstance(value, datetime) else None

        item_type = str(row.item_type or "").lower()
        directors = list(row.directors or [])
        creators = list(row.creators or [])
        if item_type in ("series", "episode"):
            directors = []
        else:
            creators = []

        return {
            "item_id": row.item_id,
            "title": row.title,
            "original_title": row.original_title,
            "series_name": row.series_name,
            "season_name": row.season_name,
            "season_number": row.season_number,
            "episode_number": row.episode_number,
            "episode_title": row.episode_title,
            "year": row.year,
            "overview": row.overview,
            "genres": list(row.genres or []),
            "community_rating": row.community_rating,
            "official_rating": row.official_rating,
            "runtime_minutes": row.runtime_minutes,
            "added_at": _dt(row.added_at),
            "premiere_date": _dt(row.premiere_date),
            "child_count": row.child_count,
            "season_count": row.season_count,
            "episode_count": row.episode_count,
            "image_tag": row.image_tag,
            "image_url": row.image_url,
            "poster_url": row.poster_url,
            "backdrop_url": row.backdrop_url,
            "banner_url": row.banner_url,
            "thumb_url": row.thumb_url,
            "logo_url": row.logo_url,
            "emby_url": row.emby_url,
            "tagline": row.tagline,
            "studios": list(row.studios or []),
            "cast": list(row.cast_members or []),
            "directors": directors,
            "creators": creators,
            "tmdb_id": row.tmdb_id,
            "imdb_id": row.imdb_id,
            "tvdb_id": row.tvdb_id,
            "trakt_id": row.trakt_id,
            "library_id": row.library_id,
            "library_name": row.library_name,
            "server_id": row.server_id,
            "server_name": row.server_name,
            "server_icon": row.server_icon,
            "server_icon_color": row.server_icon_color,
            "server_icon_style": row.server_icon_style,
            "item_type": row.item_type,
            "signature": row.signature,
            "batch_id": row.batch_id,
            "update_type": row.update_type,
            "update_label": row.update_label,
            "tmdb_poster_url": row.tmdb_poster_url,
            "tmdb_backdrop_url": row.tmdb_backdrop_url,
            "tmdb_banner_url": row.tmdb_banner_url,
            "tmdb_thumb_url": row.tmdb_thumb_url,
            "tmdb_rating": row.tmdb_rating,
            "tmdb_votes": row.tmdb_votes,
            "imdb_rating": row.imdb_rating,
            "imdb_votes": row.imdb_votes,
            "metacritic_rating": row.metacritic_rating,
            "trakt_rating": row.trakt_rating,
            "trakt_votes": row.trakt_votes,
            "omdb_fetched_at": _dt(row.omdb_fetched_at),
            "changes": changes or []
        }

    def load_latest_cache(self, cache_kind: str) -> Dict[str, Any]:
        session = self._get_session()
        try:
            kind = self._normalize_latest_cache_kind(cache_kind)
            meta = session.get(EmbyLatestCacheMeta, kind)
            if not meta:
                return {}

            items = (
                session.query(EmbyLatestCacheItem)
                .filter(EmbyLatestCacheItem.cache_kind == kind)  # type: ignore[attr-defined]
                .order_by(EmbyLatestCacheItem.sort_ts.desc(), EmbyLatestCacheItem.id.desc())  # type: ignore[attr-defined]
                .all()
            )
            item_ids = [row.id for row in items]
            changes_map: Dict[int, List[Dict[str, Any]]] = {}
            if item_ids:
                change_rows = (
                    session.query(EmbyLatestCacheChange)
                    .filter(EmbyLatestCacheChange.cache_item_id.in_(item_ids))  # type: ignore[attr-defined]
                    .order_by(EmbyLatestCacheChange.sort_index.asc(), EmbyLatestCacheChange.id.asc())  # type: ignore[attr-defined]
                    .all()
                )
                for row in change_rows:
                    entry = {
                        "kind": row.kind,
                        "label": row.label,
                        "season_number": row.season_number,
                        "episode_number": row.episode_number,
                        "episode_title": row.episode_title,
                        "quality": row.quality,
                        "resolution": row.resolution,
                        "video_codec": row.video_codec,
                        "audio_codec": row.audio_codec,
                        "audio_channels": row.audio_channels,
                        "container": row.container,
                        "bitrate": row.bitrate,
                        "source_name": row.source_name,
                        "path": row.path,
                        "size": row.size,
                        "media_source_id": row.media_source_id,
                        "added_at": row.added_at.isoformat() if isinstance(row.added_at, datetime) else None,
                        "video_details": row.video_details,
                        "audio_details": row.audio_details,
                        "audio_ita": row.audio_ita,
                        "audio_eng": row.audio_eng,
                        "audio_fra": row.audio_fra,
                        "audio_spa": row.audio_spa,
                        "audio_ger": row.audio_ger,
                        "audio_jpn": row.audio_jpn,
                        "audio_langs": row.audio_langs,
                        "subtitle_langs": row.subtitle_langs
                    }
                    changes_map.setdefault(row.cache_item_id, []).append(entry)

            movies: List[Dict[str, Any]] = []
            series: List[Dict[str, Any]] = []
            for row in items:
                item_dict = self._latest_cache_item_to_dict(row, changes_map.get(row.id, []))
                if str(row.item_type or "").lower() == "movie":
                    movies.append(item_dict)
                else:
                    series.append(item_dict)

            errors_rows = (
                session.query(EmbyLatestCacheError)
                .filter(EmbyLatestCacheError.cache_kind == kind)  # type: ignore[attr-defined]
                .order_by(EmbyLatestCacheError.id.asc())  # type: ignore[attr-defined]
                .all()
            )
            errors = [
                {"server_id": row.server_id, "message": row.message}
                for row in errors_rows
            ]

            updated_at = meta.updated_at.isoformat() if isinstance(meta.updated_at, datetime) else None
            return {
                "updated_at": updated_at,
                "params": {
                    "limit": int(meta.limit or 0),
                    "per_server_limit": int(meta.per_server_limit or 0)
                },
                "payload": {
                    "movies": movies,
                    "series": series,
                    "errors": errors
                }
            }
        finally:
            session.close()

    def save_latest_cache(
        self,
        cache_kind: str,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        updated_at: Optional[datetime] = None
    ) -> None:
        session = self._get_session()
        try:
            kind = self._normalize_latest_cache_kind(cache_kind)
            session.query(EmbyLatestCacheChange).filter(EmbyLatestCacheChange.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestCacheItem).filter(EmbyLatestCacheItem.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestCacheError).filter(EmbyLatestCacheError.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]

            movies = payload.get("movies") if isinstance(payload, dict) else []
            series = payload.get("series") if isinstance(payload, dict) else []
            errors = payload.get("errors") if isinstance(payload, dict) else []
            items = []

            def _parse_int(value: Any) -> Optional[int]:
                try:
                    return int(value) if value is not None else None
                except (TypeError, ValueError):
                    return None

            def _string(value: Any) -> Optional[str]:
                return _normalize_text_value(value)

            def _string_max(value: Any, max_len: Optional[int]) -> Optional[str]:
                return _truncate_text_value(value, max_len)

            for entry in (movies or []) + (series or []):
                if not isinstance(entry, dict):
                    continue
                item_type = _string_max(entry.get("item_type"), 20)
                is_series = str(item_type or "").lower() in ("series", "episode")
                directors = _normalize_text_array(entry.get("directors")) if not is_series else []
                creators = _normalize_text_array(entry.get("creators")) if is_series else []
                imdb_rating = _string_max(entry.get("imdb_rating"), 50)
                metacritic_rating = _string_max(entry.get("metacritic_rating"), 50)
                row = EmbyLatestCacheItem(
                    cache_kind=kind,
                    item_type=item_type,
                    server_id=_string_max(entry.get("server_id"), 36),
                    item_id=_string_max(entry.get("item_id"), 36),
                    signature=_string_max(entry.get("signature"), 255),
                    batch_id=_string_max(entry.get("batch_id"), 255),
                    title=_string_max(entry.get("title"), 500),
                    original_title=_string_max(entry.get("original_title"), 500),
                    series_name=_string_max(entry.get("series_name"), 500),
                    season_name=_string_max(entry.get("season_name"), 500),
                    season_number=_parse_int(entry.get("season_number")),
                    episode_number=_parse_int(entry.get("episode_number")),
                    episode_title=_string_max(entry.get("episode_title"), 500),
                    year=_parse_int(entry.get("year")),
                    overview=_normalize_text_value(entry.get("overview")),
                    genres=_normalize_text_array(entry.get("genres")),
                    community_rating=_string_max(entry.get("community_rating"), 50),
                    official_rating=_string_max(entry.get("official_rating"), 50),
                    runtime_minutes=_parse_int(entry.get("runtime_minutes")),
                    added_at=_parse_datetime_value(entry.get("added_at")),
                    premiere_date=_parse_datetime_value(entry.get("premiere_date")),
                    child_count=_parse_int(entry.get("child_count")),
                    season_count=_parse_int(entry.get("season_count")),
                    episode_count=_parse_int(entry.get("episode_count")),
                    image_tag=_string_max(entry.get("image_tag"), 255),
                    image_url=_string(entry.get("image_url")),
                    poster_url=_string(entry.get("poster_url")),
                    backdrop_url=None,
                    banner_url=None,
                    thumb_url=None,
                    logo_url=None,
                    emby_url=_string(entry.get("emby_url")),
                    tagline=_string(entry.get("tagline")),
                    studios=_normalize_text_array(entry.get("studios")),
                    cast_members=_normalize_text_array(entry.get("cast")),
                    directors=directors,
                    creators=creators,
                    tmdb_id=_string_max(entry.get("tmdb_id"), 50),
                    imdb_id=_string_max(entry.get("imdb_id"), 50),
                    tvdb_id=_string_max(entry.get("tvdb_id"), 50),
                    trakt_id=_string_max(entry.get("trakt_id"), 100),
                    library_id=_string_max(entry.get("library_id"), 36),
                    library_name=_string_max(entry.get("library_name"), 500),
                    server_name=_string_max(entry.get("server_name"), 255),
                    server_icon=_string_max(entry.get("server_icon"), 100),
                    server_icon_color=_string_max(entry.get("server_icon_color"), 50),
                    server_icon_style=_string_max(entry.get("server_icon_style"), 50),
                    update_type=_string_max(entry.get("update_type"), 20),
                    update_label=_string_max(entry.get("update_label"), 200),
                    tmdb_poster_url=_string(entry.get("tmdb_poster_url")),
                    tmdb_backdrop_url=None,
                    tmdb_banner_url=None,
                    tmdb_thumb_url=None,
                    tmdb_rating=_string_max(entry.get("tmdb_rating"), 50),
                    tmdb_votes=_string_max(entry.get("tmdb_votes"), 50),
                    imdb_rating=imdb_rating,
                    imdb_votes=_string_max(entry.get("imdb_votes"), 50),
                    metacritic_rating=metacritic_rating,
                    trakt_rating=_string_max(entry.get("trakt_rating"), 50),
                    trakt_votes=_string_max(entry.get("trakt_votes"), 50),
                    omdb_fetched_at=_parse_datetime_value(entry.get("omdb_fetched_at"))
                )
                row.sort_ts = row.added_at or row.premiere_date or datetime(1970, 1, 1, tzinfo=timezone.utc)  # type: ignore[assignment]
                session.add(row)
                items.append((row, entry))

            session.flush()

            for row, entry in items:
                changes = entry.get("changes")
                if not isinstance(changes, list):
                    continue
                for idx, change in enumerate(changes):
                    if not isinstance(change, dict):
                        continue
                    change_row = EmbyLatestCacheChange(
                        cache_kind=kind,
                        cache_item_id=row.id,
                        sort_index=idx,
                        kind=_string_max(change.get("kind"), 50),
                        label=_string_max(change.get("label"), 200),
                        season_number=_parse_int(change.get("season_number")),
                        episode_number=_parse_int(change.get("episode_number")),
                        episode_title=_string_max(change.get("episode_title"), 500),
                        quality=_string_max(change.get("quality"), 100),
                        resolution=_string_max(change.get("resolution"), 100),
                        video_codec=_string_max(change.get("video_codec"), 100),
                        audio_codec=_string_max(change.get("audio_codec"), 100),
                        audio_channels=_string_max(change.get("audio_channels"), 50),
                        container=_string_max(change.get("container"), 50),
                        bitrate=_string_max(change.get("bitrate"), 50),
                        source_name=_string_max(change.get("source_name"), 200),
                        path=_string(change.get("path")),
                        size=_parse_int(change.get("size")),
                        media_source_id=_string_max(change.get("media_source_id"), 100),
                        added_at=_parse_datetime_value(change.get("added_at")),
                        video_details=_string(change.get("video_details")),
                        audio_details=_string(change.get("audio_details")),
                        audio_ita=_string(change.get("audio_ita")),
                        audio_eng=_string(change.get("audio_eng")),
                        audio_fra=_string(change.get("audio_fra")),
                        audio_spa=_string(change.get("audio_spa")),
                        audio_ger=_string(change.get("audio_ger")),
                        audio_jpn=_string(change.get("audio_jpn")),
                        audio_langs=_string(change.get("audio_langs")),
                        subtitle_langs=_string(change.get("subtitle_langs"))
                    )
                    session.add(change_row)

            stamp = updated_at or _utcnow()
            if isinstance(errors, list):
                for entry in errors:
                    if not isinstance(entry, dict):
                        continue
                    error_row = EmbyLatestCacheError(
                        cache_kind=kind,
                        server_id=_string(entry.get("server_id")),
                        message=_string(entry.get("message")),
                        created_at=stamp
                    )
                    session.add(error_row)

            meta = session.get(EmbyLatestCacheMeta, kind)
            if not meta:
                meta = EmbyLatestCacheMeta(cache_kind=kind)
            meta.updated_at = stamp  # type: ignore[assignment]
            meta.limit = int(limit or 0)  # type: ignore[assignment]
            meta.per_server_limit = int(per_server_limit or 0)  # type: ignore[assignment]
            session.add(meta)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio latest cache: {exc}") from exc
        finally:
            session.close()

    def clear_latest_cache(self, cache_kind: Optional[str] = None) -> None:
        session = self._get_session()
        try:
            kind = self._normalize_latest_cache_kind(cache_kind) if cache_kind else None
            if kind:
                session.query(EmbyLatestCacheChange).filter(EmbyLatestCacheChange.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
                session.query(EmbyLatestCacheItem).filter(EmbyLatestCacheItem.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
                session.query(EmbyLatestCacheError).filter(EmbyLatestCacheError.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
                session.query(EmbyLatestCacheMeta).filter(EmbyLatestCacheMeta.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
            else:
                session.query(EmbyLatestCacheChange).delete(synchronize_session=False)
                session.query(EmbyLatestCacheItem).delete(synchronize_session=False)
                session.query(EmbyLatestCacheError).delete(synchronize_session=False)
                session.query(EmbyLatestCacheMeta).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore pulizia latest cache: {exc}") from exc
        finally:
            session.close()

    def delete_latest_cache_for_server(self, server_id: str, cache_kind: Optional[str] = None) -> None:
        if not server_id:
            return
        session = self._get_session()
        try:
            kind = self._normalize_latest_cache_kind(cache_kind) if cache_kind else None
            query = session.query(EmbyLatestCacheItem)
            if kind:
                query = query.filter(EmbyLatestCacheItem.cache_kind == kind)  # type: ignore[attr-defined]
            query = query.filter(EmbyLatestCacheItem.server_id == server_id)  # type: ignore[attr-defined]
            rows = query.all()
            item_ids = [row.id for row in rows]
            if item_ids:
                session.query(EmbyLatestCacheChange).filter(EmbyLatestCacheChange.cache_item_id.in_(item_ids)).delete(synchronize_session=False)  # type: ignore[attr-defined]
            query.delete(synchronize_session=False)
            error_query = session.query(EmbyLatestCacheError).filter(EmbyLatestCacheError.server_id == server_id)  # type: ignore[attr-defined]
            if kind:
                error_query = error_query.filter(EmbyLatestCacheError.cache_kind == kind)  # type: ignore[attr-defined]
            error_query.delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione latest cache per server: {exc}") from exc
        finally:
            session.close()

    # --- Jellyseerr requests ---

    def load_latest_state(self) -> Dict[str, Any]:
        session = self._get_session()
        try:
            state: Dict[str, Any] = {}

            def _ensure_server(server_id: str) -> Dict[str, Any]:
                server_state = state.setdefault(server_id, {})
                if not isinstance(server_state.get("movies"), dict):
                    server_state["movies"] = {"items": {}}
                if not isinstance(server_state.get("series"), dict):
                    server_state["series"] = {"items": {}}
                return server_state

            movie_rows = session.query(EmbyLatestStateMovie).all()
            for row in movie_rows:
                server_state = _ensure_server(row.server_id)
                items = server_state["movies"].setdefault("items", {})
                entry = {
                    "title": row.title,
                    "year": row.year,
                    "last_seen_at": row.last_seen_at.isoformat() if isinstance(row.last_seen_at, datetime) else None,
                    "media_source_keys": list(row.media_source_keys or []),
                    "notified": bool(row.notified),
                    "notified_at": row.notified_at.isoformat() if isinstance(row.notified_at, datetime) else "",
                }
                if row.item_id:
                    entry["item_id"] = row.item_id
                if row.signature:
                    entry["signature"] = row.signature
                items[row.state_key] = entry

            series_rows = session.query(EmbyLatestStateSeries).all()
            for row in series_rows:
                server_state = _ensure_server(row.server_id)
                series_items = server_state["series"].setdefault("items", {})
                series_items[row.series_id] = {
                    "series_id": row.series_id,
                    "item_id": row.series_id,
                    "title": row.title or "",
                    "year": row.year,
                    "last_seen_at": row.last_seen_at.isoformat() if isinstance(row.last_seen_at, datetime) else "",
                    "episodes": {},
                    "seasons": list(row.seasons or []),
                    "last_changes": [],
                    "notified": bool(row.notified),
                    "notified_at": row.notified_at.isoformat() if isinstance(row.notified_at, datetime) else ""
                }

            episode_rows = session.query(EmbyLatestStateEpisode).all()
            for row in episode_rows:
                server_state = _ensure_server(row.server_id)
                series_items = server_state["series"].setdefault("items", {})
                series_entry = series_items.get(row.series_id)
                if not isinstance(series_entry, dict):
                    series_entry = {
                        "series_id": row.series_id,
                        "title": "",
                        "year": None,
                        "last_seen_at": "",
                        "episodes": {},
                        "seasons": [],
                        "last_changes": [],
                        "notified": False,
                        "notified_at": ""
                    }
                    series_items[row.series_id] = series_entry
                episodes = series_entry.setdefault("episodes", {})
                episode_key = row.episode_key or row.episode_id or ""
                if not episode_key:
                    continue
                episodes[episode_key] = {
                    "season": row.season_number,
                    "episode": row.episode_number,
                    "title": row.title or "",
                    "last_seen_at": row.last_seen_at.isoformat() if isinstance(row.last_seen_at, datetime) else "",
                    "media_source_keys": list(row.media_source_keys or []),
                    "key": row.episode_key,
                    "episode_id": row.episode_id
                }

            group_rows = (
                session.query(EmbyLatestStateSeriesGroup)
                .order_by(EmbyLatestStateSeriesGroup.sort_index.asc(), EmbyLatestStateSeriesGroup.id.asc())  # type: ignore[attr-defined]
                .all()
            )
            change_rows = (
                session.query(EmbyLatestStateSeriesChange)
                .order_by(EmbyLatestStateSeriesChange.sort_index.asc(), EmbyLatestStateSeriesChange.id.asc())  # type: ignore[attr-defined]
                .all()
            )

            groups_by_id: Dict[int, Dict[str, Any]] = {}
            groups_by_series: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
            for row in group_rows:
                group = {
                    "update_type": row.update_type,
                    "update_label": row.update_label,
                    "changes": [],
                    "batch_id": row.batch_id,
                    "added_at": row.added_at.isoformat() if isinstance(row.added_at, datetime) else ""
                }
                groups_by_id[row.id] = group
                key = (row.server_id, row.series_id)
                groups_by_series.setdefault(key, []).append(group)

            for row in change_rows:
                group = groups_by_id.get(row.group_id)
                if not group:
                    continue
                group["changes"].append({
                    "kind": row.kind,
                    "label": row.label,
                    "season_number": row.season_number,
                    "episode_number": row.episode_number,
                    "episode_title": row.episode_title,
                    "quality": row.quality,
                    "resolution": row.resolution,
                    "video_codec": row.video_codec,
                    "audio_codec": row.audio_codec,
                    "audio_channels": row.audio_channels,
                    "container": row.container,
                    "bitrate": row.bitrate,
                    "source_name": row.source_name,
                    "path": row.path,
                    "size": row.size,
                    "media_source_id": row.media_source_id,
                    "added_at": row.added_at.isoformat() if isinstance(row.added_at, datetime) else "",
                    "video_details": row.video_details,
                    "audio_details": row.audio_details,
                    "audio_ita": row.audio_ita,
                    "audio_eng": row.audio_eng,
                    "audio_fra": row.audio_fra,
                    "audio_spa": row.audio_spa,
                    "audio_ger": row.audio_ger,
                    "audio_jpn": row.audio_jpn,
                    "audio_langs": row.audio_langs,
                    "subtitle_langs": row.subtitle_langs
                })

            for (server_id, series_id), groups in groups_by_series.items():
                server_state = _ensure_server(server_id)
                series_items = server_state["series"].setdefault("items", {})
                series_entry = series_items.get(series_id)
                if isinstance(series_entry, dict):
                    series_entry["last_changes"] = groups

            return state
        finally:
            session.close()

    def save_latest_state(self, state: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            session.query(EmbyLatestStateSeriesChange).delete(synchronize_session=False)
            session.query(EmbyLatestStateSeriesGroup).delete(synchronize_session=False)
            session.query(EmbyLatestStateEpisode).delete(synchronize_session=False)
            session.query(EmbyLatestStateMovie).delete(synchronize_session=False)
            session.query(EmbyLatestStateSeries).delete(synchronize_session=False)

            for server_id, server_state in (state or {}).items():
                if not isinstance(server_state, dict):
                    continue
                movies_state = server_state.get("movies", {})
                movie_items = movies_state.get("items") if isinstance(movies_state, dict) else {}
                if isinstance(movie_items, dict):
                    for state_key, entry in movie_items.items():
                        if not state_key or not isinstance(entry, dict):
                            continue
                        row = EmbyLatestStateMovie(
                            server_id=str(server_id),
                            state_key=str(state_key),
                            item_id=_normalize_text_value(entry.get("item_id")),
                            signature=_normalize_text_value(entry.get("signature")),
                            title=_normalize_text_value(entry.get("title")),
                            year=_parse_int(entry.get("year")),
                            last_seen_at=_parse_datetime_value(entry.get("last_seen_at")),
                            media_source_keys=_normalize_text_array(entry.get("media_source_keys")),
                            notified=bool(entry.get("notified")),
                            notified_at=_parse_datetime_value(entry.get("notified_at"))
                        )
                        session.add(row)

                series_state = server_state.get("series", {})
                series_items = series_state.get("items") if isinstance(series_state, dict) else {}
                if isinstance(series_items, dict):
                    for series_id, entry in series_items.items():
                        if not series_id or not isinstance(entry, dict):
                            continue
                        row = EmbyLatestStateSeries(
                            server_id=str(server_id),
                            series_id=str(series_id),
                            title=_normalize_text_value(entry.get("title")),
                            year=_parse_int(entry.get("year")),
                            last_seen_at=_parse_datetime_value(entry.get("last_seen_at")),
                            seasons=_normalize_int_array(entry.get("seasons")),
                            notified=bool(entry.get("notified")),
                            notified_at=_parse_datetime_value(entry.get("notified_at"))
                        )
                        session.add(row)

                        episodes = entry.get("episodes")
                        if isinstance(episodes, dict):
                            for episode_key, ep_entry in episodes.items():
                                if not episode_key or not isinstance(ep_entry, dict):
                                    continue
                                session.add(EmbyLatestStateEpisode(
                                    server_id=str(server_id),
                                    series_id=str(series_id),
                                    episode_key=str(episode_key),
                                    episode_id=_normalize_text_value(ep_entry.get("episode_id")),
                                    season_number=_parse_int(ep_entry.get("season") or ep_entry.get("season_number")),
                                    episode_number=_parse_int(ep_entry.get("episode") or ep_entry.get("episode_number")),
                                    title=_normalize_text_value(ep_entry.get("title")),
                                    last_seen_at=_parse_datetime_value(ep_entry.get("last_seen_at")),
                                    media_source_keys=_normalize_text_array(ep_entry.get("media_source_keys"))
                                ))

                        last_changes = entry.get("last_changes")
                        if isinstance(last_changes, list):
                            for group_index, group in enumerate(last_changes):
                                if not isinstance(group, dict):
                                    continue
                                group_row = EmbyLatestStateSeriesGroup(
                                    server_id=str(server_id),
                                    series_id=str(series_id),
                                    sort_index=group_index,
                                    update_type=_normalize_text_value(group.get("update_type")),
                                    update_label=_normalize_text_value(group.get("update_label")),
                                    batch_id=_normalize_text_value(group.get("batch_id")),
                                    added_at=_parse_datetime_value(group.get("added_at"))
                                )
                                session.add(group_row)
                                session.flush()
                                changes = group.get("changes")
                                if isinstance(changes, list):
                                    for idx, change in enumerate(changes):
                                        if not isinstance(change, dict):
                                            continue
                                        session.add(EmbyLatestStateSeriesChange(
                                            group_id=group_row.id,
                                            sort_index=idx,
                                            kind=_normalize_text_value(change.get("kind")),
                                            label=_normalize_text_value(change.get("label")),
                                            season_number=_parse_int(change.get("season_number")),
                                            episode_number=_parse_int(change.get("episode_number")),
                                            episode_title=_normalize_text_value(change.get("episode_title")),
                                            quality=_normalize_text_value(change.get("quality")),
                                            resolution=_normalize_text_value(change.get("resolution")),
                                            video_codec=_normalize_text_value(change.get("video_codec")),
                                            audio_codec=_normalize_text_value(change.get("audio_codec")),
                                            audio_channels=_normalize_text_value(change.get("audio_channels")),
                                            container=_normalize_text_value(change.get("container")),
                                            bitrate=_normalize_text_value(change.get("bitrate")),
                                            source_name=_normalize_text_value(change.get("source_name")),
                                            path=_normalize_text_value(change.get("path")),
                                            size=_parse_int(change.get("size")),
                                            media_source_id=_normalize_text_value(change.get("media_source_id")),
                                            added_at=_parse_datetime_value(change.get("added_at")),
                                            video_details=_normalize_text_value(change.get("video_details")),
                                            audio_details=_normalize_text_value(change.get("audio_details")),
                                            audio_ita=_normalize_text_value(change.get("audio_ita")),
                                            audio_eng=_normalize_text_value(change.get("audio_eng")),
                                            audio_fra=_normalize_text_value(change.get("audio_fra")),
                                            audio_spa=_normalize_text_value(change.get("audio_spa")),
                                            audio_ger=_normalize_text_value(change.get("audio_ger")),
                                            audio_jpn=_normalize_text_value(change.get("audio_jpn")),
                                            audio_langs=_normalize_text_value(change.get("audio_langs")),
                                            subtitle_langs=_normalize_text_value(change.get("subtitle_langs"))
                                        ))

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio latest state: {exc}") from exc
        finally:
            session.close()

    def clear_latest_state(self) -> None:
        session = self._get_session()
        try:
            session.query(EmbyLatestStateSeriesChange).delete(synchronize_session=False)
            session.query(EmbyLatestStateSeriesGroup).delete(synchronize_session=False)
            session.query(EmbyLatestStateEpisode).delete(synchronize_session=False)
            session.query(EmbyLatestStateMovie).delete(synchronize_session=False)
            session.query(EmbyLatestStateSeries).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore pulizia latest state: {exc}") from exc
        finally:
            session.close()

    def delete_latest_state_for_server(self, server_id: str) -> None:
        if not server_id:
            return
        session = self._get_session()
        try:
            groups = session.query(EmbyLatestStateSeriesGroup).filter(EmbyLatestStateSeriesGroup.server_id == server_id).all()  # type: ignore[attr-defined]
            group_ids = [row.id for row in groups]
            if group_ids:
                session.query(EmbyLatestStateSeriesChange).filter(EmbyLatestStateSeriesChange.group_id.in_(group_ids)).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestStateSeriesGroup).filter(EmbyLatestStateSeriesGroup.server_id == server_id).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestStateEpisode).filter(EmbyLatestStateEpisode.server_id == server_id).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestStateMovie).filter(EmbyLatestStateMovie.server_id == server_id).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.query(EmbyLatestStateSeries).filter(EmbyLatestStateSeries.server_id == server_id).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione latest state per server: {exc}") from exc
        finally:
            session.close()

    # --- Latest progress tracking ---

    def save_latest_progress(self, progress: Dict[str, Any]) -> None:
        """
        Save progress tracking data for Latest refresh operations.

        Args:
            progress: Dict with keys: state, total, completed, message, started_at
        """
        if not isinstance(progress, dict):
            return
        session = self._get_session()
        try:
            row = session.query(EmbyLatestProgress).filter(EmbyLatestProgress.id == 1).first()  # type: ignore[attr-defined]
            if row:
                row.state = str(progress.get("state", "idle"))
                row.total = int(progress.get("total", 0))
                row.completed = int(progress.get("completed", 0))
                row.message = _normalize_text_value(progress.get("message"))
                row.started_at = _parse_datetime_value(progress.get("started_at"))
            else:
                row = EmbyLatestProgress(
                    id=1,
                    state=str(progress.get("state", "idle")),
                    total=int(progress.get("total", 0)),
                    completed=int(progress.get("completed", 0)),
                    message=_normalize_text_value(progress.get("message")),
                    started_at=_parse_datetime_value(progress.get("started_at"))
                )
                session.add(row)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio latest progress: {exc}") from exc
        finally:
            session.close()

    def load_latest_progress(self) -> Dict[str, Any]:
        """
        Load progress tracking data from database.

        Returns:
            Dict with keys: state, total, completed, message, started_at, updated_at
        """
        session = self._get_session()
        try:
            row = session.query(EmbyLatestProgress).filter(EmbyLatestProgress.id == 1).first()  # type: ignore[attr-defined]
            if not row:
                return {
                    "state": "idle",
                    "total": 0,
                    "completed": 0,
                    "message": "",
                    "started_at": None,
                    "updated_at": None
                }
            return {
                "state": str(row.state) if row.state else "idle",
                "total": int(row.total) if row.total is not None else 0,
                "completed": int(row.completed) if row.completed is not None else 0,
                "message": str(row.message) if row.message else "",
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None
            }
        finally:
            session.close()
