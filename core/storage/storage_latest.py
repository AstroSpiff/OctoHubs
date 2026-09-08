"""Latest cache/state storage operations."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional, Protocol

from core.emby_image_urls import build_latest_emby_image_urls
from core.storage.field_limits import (
    INTERNAL_SERVER_ID_MAX_LENGTH,
    optional_emby_identifier,
    require_bounded_text,
)
from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_latest_state_merge import merge_notification_updates
from core.storage.storage_locks import lock_latest_refresh, lock_latest_state
from core.storage.storage_models import (
    SQLAlchemyError,
    EmbyLatestCacheMeta,
    EmbyLatestCacheItem,
    EmbyLatestCacheChange,
    EmbyLatestCacheError,
    EmbyLatestStateDocument,
    EmbyLatestNotificationDelivery,
    EmbyLatestProgress,
    _utcnow,
    text,
)
from core.storage.storage_utils import (
    _parse_datetime_value,
    _normalize_text_array,
    _parse_int,
    _normalize_text_value,
    _truncate_text_value,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


_LATEST_CACHE_ADVISORY_LOCKS = {
    "batch": 6_103_601_282_114_701_101,
    "feed": 6_103_601_282_114_701_102,
}
_latest_cache_write_lock = threading.RLock()


def _lock_latest_cache_write(session: Any, kind: str) -> None:
    get_bind = getattr(session, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": _LATEST_CACHE_ADVISORY_LOCKS[kind]},
    )


def _configure_latest_cache_read_snapshot(session: Any) -> None:
    """Keep all cache tables on one PostgreSQL MVCC snapshot."""
    get_bind = getattr(session, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return
    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})


def _cache_text(value: Any, max_len: Optional[int] = None) -> Optional[str]:
    if max_len is None:
        return _normalize_text_value(value)
    return _truncate_text_value(value, max_len)


def _optional_latest_server_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return require_bounded_text(
        value,
        field="server_id",
        max_length=INTERNAL_SERVER_ID_MAX_LENGTH,
    )


def _validate_latest_cache_identifiers(payload: Dict[str, Any]) -> None:
    """Reject unsafe remote IDs before opening a cache-write transaction."""
    source = payload if isinstance(payload, dict) else {}
    for entry in (source.get("movies") or []) + (source.get("series") or []):
        if not isinstance(entry, dict):
            continue
        _optional_latest_server_id(entry.get("server_id"))
        optional_emby_identifier(entry.get("item_id"), field="item_id")
        optional_emby_identifier(entry.get("library_id"), field="library_id")
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if isinstance(change, dict):
                optional_emby_identifier(
                    change.get("media_source_id"), field="media_source_id"
                )
    for error in source.get("errors") or []:
        if isinstance(error, dict):
            _optional_latest_server_id(error.get("server_id"))


def _build_latest_cache_item(kind: str, entry: Dict[str, Any]) -> Any:
    item_type = _cache_text(entry.get("item_type"), 20)
    is_series = str(item_type or "").lower() in ("series", "episode")
    image_urls = build_latest_emby_image_urls(
        entry.get("server_id"),
        entry.get("item_id"),
        primary_tag=entry.get("image_tag"),
    )
    row = EmbyLatestCacheItem(
        cache_kind=kind,
        item_type=item_type,
        server_id=_optional_latest_server_id(entry.get("server_id")),
        item_id=optional_emby_identifier(entry.get("item_id"), field="item_id"),
        signature=_cache_text(entry.get("signature"), 255),
        batch_id=_cache_text(entry.get("batch_id"), 255),
        title=_cache_text(entry.get("title"), 500),
        original_title=_cache_text(entry.get("original_title"), 500),
        series_name=_cache_text(entry.get("series_name"), 500),
        season_name=_cache_text(entry.get("season_name"), 500),
        season_number=_parse_int(entry.get("season_number")),
        episode_number=_parse_int(entry.get("episode_number")),
        episode_title=_cache_text(entry.get("episode_title"), 500),
        year=_parse_int(entry.get("year")),
        overview=_normalize_text_value(entry.get("overview")),
        genres=_normalize_text_array(entry.get("genres")),
        community_rating=_cache_text(entry.get("community_rating"), 50),
        official_rating=_cache_text(entry.get("official_rating"), 50),
        runtime_minutes=_parse_int(entry.get("runtime_minutes")),
        added_at=_parse_datetime_value(entry.get("added_at")),
        premiere_date=_parse_datetime_value(entry.get("premiere_date")),
        child_count=_parse_int(entry.get("child_count")),
        season_count=_parse_int(entry.get("season_count")),
        episode_count=_parse_int(entry.get("episode_count")),
        image_tag=_cache_text(entry.get("image_tag"), 255),
        image_url=_cache_text(image_urls["image_url"]),
        poster_url=_cache_text(image_urls["poster_url"]),
        backdrop_url=_cache_text(image_urls["backdrop_url"]),
        banner_url=_cache_text(image_urls["banner_url"]),
        thumb_url=_cache_text(image_urls["thumb_url"]),
        logo_url=_cache_text(image_urls["logo_url"]),
        emby_url=_cache_text(entry.get("emby_url")),
        tagline=_cache_text(entry.get("tagline")),
        studios=_normalize_text_array(entry.get("studios")),
        cast_members=_normalize_text_array(entry.get("cast")),
        directors=_normalize_text_array(entry.get("directors")) if not is_series else [],
        creators=_normalize_text_array(entry.get("creators")) if is_series else [],
        tmdb_id=_cache_text(entry.get("tmdb_id"), 50),
        imdb_id=_cache_text(entry.get("imdb_id"), 50),
        tvdb_id=_cache_text(entry.get("tvdb_id"), 50),
        trakt_id=_cache_text(entry.get("trakt_id"), 100),
        library_id=optional_emby_identifier(entry.get("library_id"), field="library_id"),
        library_name=_cache_text(entry.get("library_name"), 500),
        server_name=_cache_text(entry.get("server_name"), 255),
        server_icon=_cache_text(entry.get("server_icon"), 100),
        server_icon_color=_cache_text(entry.get("server_icon_color"), 50),
        server_icon_style=_cache_text(entry.get("server_icon_style"), 50),
        update_type=_cache_text(entry.get("update_type"), 20),
        update_label=_cache_text(entry.get("update_label"), 200),
        tmdb_poster_url=_cache_text(entry.get("tmdb_poster_url")),
        tmdb_backdrop_url=None,
        tmdb_banner_url=None,
        tmdb_thumb_url=None,
        tmdb_rating=_cache_text(entry.get("tmdb_rating"), 50),
        tmdb_votes=_cache_text(entry.get("tmdb_votes"), 50),
        imdb_rating=_cache_text(entry.get("imdb_rating"), 50),
        imdb_votes=_cache_text(entry.get("imdb_votes"), 50),
        metacritic_rating=_cache_text(entry.get("metacritic_rating"), 50),
        trakt_rating=_cache_text(entry.get("trakt_rating"), 50),
        trakt_votes=_cache_text(entry.get("trakt_votes"), 50),
        omdb_fetched_at=_parse_datetime_value(entry.get("omdb_fetched_at")),
        trakt_fetched_at=_parse_datetime_value(entry.get("trakt_fetched_at")),
    )
    row.sort_ts = row.added_at or row.premiere_date or datetime(1970, 1, 1, tzinfo=timezone.utc)  # type: ignore[assignment]
    return row


def _build_latest_cache_change(kind: str, item_id: int, index: int, change: Dict[str, Any]) -> Any:
    return EmbyLatestCacheChange(
        cache_kind=kind,
        cache_item_id=item_id,
        sort_index=index,
        kind=_cache_text(change.get("kind"), 50),
        label=_cache_text(change.get("label"), 200),
        season_number=_parse_int(change.get("season_number")),
        episode_number=_parse_int(change.get("episode_number")),
        episode_title=_cache_text(change.get("episode_title"), 500),
        quality=_cache_text(change.get("quality"), 100),
        resolution=_cache_text(change.get("resolution"), 100),
        video_codec=_cache_text(change.get("video_codec"), 100),
        audio_codec=_cache_text(change.get("audio_codec"), 100),
        audio_channels=_cache_text(change.get("audio_channels"), 50),
        container=_cache_text(change.get("container"), 50),
        bitrate=_cache_text(change.get("bitrate"), 50),
        source_name=_cache_text(change.get("source_name"), 200),
        path=_cache_text(change.get("path")),
        size=_parse_int(change.get("size")),
        media_source_id=optional_emby_identifier(
            change.get("media_source_id"), field="media_source_id"
        ),
        added_at=_parse_datetime_value(change.get("added_at")),
        video_details=_cache_text(change.get("video_details")),
        audio_details=_cache_text(change.get("audio_details")),
        audio_ita=_cache_text(change.get("audio_ita")),
        audio_eng=_cache_text(change.get("audio_eng")),
        audio_fra=_cache_text(change.get("audio_fra")),
        audio_spa=_cache_text(change.get("audio_spa")),
        audio_ger=_cache_text(change.get("audio_ger")),
        audio_jpn=_cache_text(change.get("audio_jpn")),
        audio_langs=_cache_text(change.get("audio_langs")),
        subtitle_langs=_cache_text(change.get("subtitle_langs")),
    )


def _add_latest_cache_items(session: Any, kind: str, entries: Any) -> List[tuple[Any, Dict[str, Any]]]:
    added: List[tuple[Any, Dict[str, Any]]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        row = _build_latest_cache_item(kind, entry)
        session.add(row)
        added.append((row, entry))
    return added


def _add_latest_cache_changes(session: Any, kind: str, items: List[tuple[Any, Dict[str, Any]]]) -> None:
    for row, entry in items:
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for index, change in enumerate(changes):
            if isinstance(change, dict):
                session.add(_build_latest_cache_change(kind, row.id, index, change))


def _add_latest_cache_errors(session: Any, kind: str, errors: Any, stamp: datetime) -> None:
    if not isinstance(errors, list):
        return
    for entry in errors:
        if isinstance(entry, dict):
            session.add(
                EmbyLatestCacheError(
                    cache_kind=kind,
                    server_id=_optional_latest_server_id(entry.get("server_id")),
                    message=_cache_text(entry.get("message")),
                    created_at=stamp,
                )
            )


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

        image_urls = build_latest_emby_image_urls(
            row.server_id,
            row.item_id,
            primary_tag=row.image_tag,
        )

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
            "image_url": image_urls["image_url"],
            "poster_url": image_urls["poster_url"],
            "backdrop_url": image_urls["backdrop_url"],
            "banner_url": image_urls["banner_url"],
            "thumb_url": image_urls["thumb_url"],
            "logo_url": image_urls["logo_url"],
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
            "trakt_fetched_at": _dt(row.trakt_fetched_at),
            "changes": changes or []
        }

    def load_latest_cache(self, cache_kind: str) -> Dict[str, Any]:
        session = self._get_session()
        try:
            kind = self._normalize_latest_cache_kind(cache_kind)
            _configure_latest_cache_read_snapshot(session)
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
            close_session_safely(session)

    def save_latest_cache(
        self,
        cache_kind: str,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        updated_at: Optional[datetime] = None
    ) -> None:
        kind = self._normalize_latest_cache_kind(cache_kind)
        _validate_latest_cache_identifiers(payload)
        with _latest_cache_write_lock:
            self._save_latest_cache_locked(
                kind,
                payload,
                limit,
                per_server_limit,
                updated_at,
            )

    def _save_latest_cache_locked(
        self,
        kind: str,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        updated_at: Optional[datetime],
    ) -> None:
        session = self._get_session()
        try:
            self._replace_latest_cache_in_session(
                session,
                kind,
                payload,
                limit,
                per_server_limit,
                updated_at,
            )
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio latest cache: {exc}") from exc
        finally:
            close_session_safely(session)

    def _replace_latest_cache_in_session(
        self,
        session: Any,
        kind: str,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        updated_at: Optional[datetime],
    ) -> None:
        _lock_latest_cache_write(session, kind)
        session.query(EmbyLatestCacheChange).filter(EmbyLatestCacheChange.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
        session.query(EmbyLatestCacheItem).filter(EmbyLatestCacheItem.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]
        session.query(EmbyLatestCacheError).filter(EmbyLatestCacheError.cache_kind == kind).delete(synchronize_session=False)  # type: ignore[attr-defined]

        source = payload if isinstance(payload, dict) else {}
        items = _add_latest_cache_items(
            session,
            kind,
            (source.get("movies") or []) + (source.get("series") or []),
        )
        session.flush()
        _add_latest_cache_changes(session, kind, items)

        stamp = updated_at or _utcnow()
        _add_latest_cache_errors(session, kind, source.get("errors"), stamp)
        meta = session.get(EmbyLatestCacheMeta, kind)
        if not meta:
            meta = EmbyLatestCacheMeta(cache_kind=kind)
        meta.updated_at = stamp  # type: ignore[assignment]
        meta.limit = int(limit or 0)  # type: ignore[assignment]
        meta.per_server_limit = int(per_server_limit or 0)  # type: ignore[assignment]
        session.add(meta)

    def publish_latest_refresh(
        self,
        payload: Dict[str, Any],
        limit: int,
        per_server_limit: int,
        latest_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Atomically replace both caches and optional collector state."""
        _validate_latest_cache_identifiers(payload)
        session = self._get_session()
        try:
            lock_latest_refresh(session)
            with _latest_cache_write_lock:
                published_at = _utcnow()
                self._replace_latest_cache_in_session(
                    session,
                    "batch",
                    payload,
                    limit,
                    per_server_limit,
                    published_at,
                )
                self._replace_latest_cache_in_session(
                    session,
                    "feed",
                    payload,
                    limit,
                    per_server_limit,
                    published_at,
                )
                if latest_state is not None:
                    lock_latest_state(session)
                    persisted_state = self._load_latest_state_in_session(session)
                    merged_state = merge_notification_updates(
                        latest_state,
                        persisted_state,
                    )
                    self._replace_latest_state_in_session(session, merged_state)
                session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore pubblicazione Latest: {exc}") from exc
        except Exception:
            rollback_session_safely(session)
            raise
        finally:
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore pulizia latest cache: {exc}") from exc
        finally:
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione latest cache per server: {exc}") from exc
        finally:
            close_session_safely(session)

    # --- Jellyseerr requests ---

    def load_latest_state(self) -> Dict[str, Any]:
        session = self._get_session()
        try:
            return self._load_latest_state_in_session(session)
        finally:
            close_session_safely(session)

    def _load_latest_state_in_session(self, session: Any) -> Dict[str, Any]:
        document = session.get(EmbyLatestStateDocument, 1)
        if document is not None and isinstance(document.payload, dict):
            return copy.deepcopy(document.payload)

        return {}

    def save_latest_state(self, state: Dict[str, Any]) -> None:
        session = self._get_session()
        try:
            self._replace_latest_state_in_session(session, state)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio latest state: {exc}") from exc
        finally:
            close_session_safely(session)

    def _replace_latest_state_in_session(
        self,
        session: Any,
        state: Dict[str, Any],
    ) -> None:
        document = session.get(EmbyLatestStateDocument, 1)
        if document is None:
            document = EmbyLatestStateDocument(id=1, payload={})
        document.payload = copy.deepcopy(state or {})  # type: ignore[assignment]
        document.updated_at = _utcnow()  # type: ignore[assignment]
        session.add(document)


    def clear_latest_state(self) -> None:
        session = self._get_session()
        try:
            session.query(EmbyLatestStateDocument).delete(synchronize_session=False)
            session.query(EmbyLatestNotificationDelivery).delete(synchronize_session=False)
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore pulizia latest state: {exc}") from exc
        finally:
            close_session_safely(session)

    def delete_latest_state_for_server(self, server_id: str) -> None:
        if not server_id:
            return
        session = self._get_session()
        try:
            document = session.get(EmbyLatestStateDocument, 1)
            if document is not None and isinstance(document.payload, dict):
                payload = copy.deepcopy(document.payload)
                payload.pop(server_id, None)
                document.payload = payload  # type: ignore[assignment]
                document.updated_at = _utcnow()  # type: ignore[assignment]
                session.add(document)
            session.query(EmbyLatestNotificationDelivery).filter(EmbyLatestNotificationDelivery.server_id == server_id).delete(synchronize_session=False)  # type: ignore[attr-defined]
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore rimozione latest state per server: {exc}") from exc
        finally:
            close_session_safely(session)

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
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio latest progress: {exc}") from exc
        finally:
            close_session_safely(session)

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
            close_session_safely(session)
