"""SQLAlchemy models for OctoHub storage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, BigInteger, String, Text, LargeBinary, ForeignKey, Index, create_engine, func, or_, text
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import DeclarativeBase, declarative_base, sessionmaker

try:
    from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, BigInteger, String, Text, LargeBinary, ForeignKey, Index, create_engine, func, or_, text
    from sqlalchemy.dialects.postgresql import ARRAY
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import declarative_base, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    SQLALCHEMY_AVAILABLE = False
    SQLAlchemyError = Exception
    def _missing(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        raise RuntimeError("SQLAlchemy is not available")

    create_engine = _missing
    func = _missing
    or_ = _missing
    text = _missing
    sessionmaker = _missing
    JSON = Boolean = Column = DateTime = Integer = BigInteger = String = Text = LargeBinary = ForeignKey = Index = _missing
    ARRAY = _missing
else:
    DeclarativeBase = object

Base = declarative_base() if SQLALCHEMY_AVAILABLE else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


if SQLALCHEMY_AVAILABLE:

    class AppSettings(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "app_settings"
        id = Column(Integer, primary_key=True, default=1)  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyLatestCacheMeta(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_cache_meta"
        cache_kind = Column(String(20), primary_key=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]
        limit = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]
        per_server_limit = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]

    class EmbyLatestCacheItem(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_cache_items"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        cache_kind = Column(String(20), nullable=False, index=True)  # type: ignore[assignment]
        item_type = Column(String(20), index=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        item_id = Column(String(36), index=True)  # type: ignore[assignment]
        signature = Column(String(255), index=True)  # type: ignore[assignment]
        batch_id = Column(String(255), index=True)  # type: ignore[assignment]
        title = Column(String(500))  # type: ignore[assignment]
        original_title = Column(String(500))  # type: ignore[assignment]
        series_name = Column(String(500))  # type: ignore[assignment]
        season_name = Column(String(500))  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        episode_title = Column(String(500))  # type: ignore[assignment]
        year = Column(Integer)  # type: ignore[assignment]
        overview = Column(Text)  # type: ignore[assignment]
        genres = Column(ARRAY(String))  # type: ignore[assignment]
        community_rating = Column(String(50))  # type: ignore[assignment]
        official_rating = Column(String(50))  # type: ignore[assignment]
        runtime_minutes = Column(Integer)  # type: ignore[assignment]
        added_at = Column(DateTime)  # type: ignore[assignment]
        premiere_date = Column(DateTime)  # type: ignore[assignment]
        child_count = Column(Integer)  # type: ignore[assignment]
        season_count = Column(Integer)  # type: ignore[assignment]
        episode_count = Column(Integer)  # type: ignore[assignment]
        image_tag = Column(String(255))  # type: ignore[assignment]
        image_url = Column(Text)  # type: ignore[assignment]
        poster_url = Column(Text)  # type: ignore[assignment]
        backdrop_url = Column(Text)  # type: ignore[assignment]
        banner_url = Column(Text)  # type: ignore[assignment]
        thumb_url = Column(Text)  # type: ignore[assignment]
        logo_url = Column(Text)  # type: ignore[assignment]
        emby_url = Column(Text)  # type: ignore[assignment]
        tagline = Column(Text)  # type: ignore[assignment]
        studios = Column(ARRAY(String))  # type: ignore[assignment]
        cast_members = Column(ARRAY(String))  # type: ignore[assignment]
        directors = Column(ARRAY(String))  # type: ignore[assignment]
        creators = Column(ARRAY(String))  # type: ignore[assignment]
        tmdb_id = Column(String(50))  # type: ignore[assignment]
        imdb_id = Column(String(50))  # type: ignore[assignment]
        tvdb_id = Column(String(50))  # type: ignore[assignment]
        trakt_id = Column(String(100))  # type: ignore[assignment]
        library_id = Column(String(36))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        server_name = Column(String(255))  # type: ignore[assignment]
        server_icon = Column(String(100))  # type: ignore[assignment]
        server_icon_color = Column(String(50))  # type: ignore[assignment]
        server_icon_style = Column(String(50))  # type: ignore[assignment]
        update_type = Column(String(20))  # type: ignore[assignment]
        update_label = Column(String(200))  # type: ignore[assignment]
        tmdb_poster_url = Column(Text)  # type: ignore[assignment]
        tmdb_backdrop_url = Column(Text)  # type: ignore[assignment]
        tmdb_banner_url = Column(Text)  # type: ignore[assignment]
        tmdb_thumb_url = Column(Text)  # type: ignore[assignment]
        tmdb_rating = Column(String(50))  # type: ignore[assignment]
        tmdb_votes = Column(String(50))  # type: ignore[assignment]
        imdb_rating = Column(String(50))  # type: ignore[assignment]
        imdb_votes = Column(String(50))  # type: ignore[assignment]
        metacritic_rating = Column(String(50))  # type: ignore[assignment]
        trakt_rating = Column(String(50))  # type: ignore[assignment]
        trakt_votes = Column(String(50))  # type: ignore[assignment]
        omdb_fetched_at = Column(DateTime)  # type: ignore[assignment]
        sort_ts = Column(DateTime, index=True)  # type: ignore[assignment]
        __table_args__ = (
            Index("ix_latest_cache_kind_server_type", "cache_kind", "server_id", "item_type"),  # type: ignore
            Index("ix_latest_cache_kind_sort", "cache_kind", "sort_ts"),  # type: ignore
        )

    class JellyseerrRequest(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "jellyseerr_requests"
        request_id = Column(String(50), primary_key=True)  # type: ignore[assignment]
        tmdb_id = Column(Integer, index=True)  # type: ignore[assignment]
        media_type = Column(String(10), index=True)  # type: ignore[assignment]
        status = Column(String(50))  # type: ignore[assignment]
        status_label = Column(String(100))  # type: ignore[assignment]
        requested_by = Column(String(255))  # type: ignore[assignment]
        created_at = Column(DateTime)  # type: ignore[assignment]
        updated_at = Column(DateTime, index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]

    class EmbyLatestCacheChange(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_cache_changes"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        cache_kind = Column(String(20), index=True)  # type: ignore[assignment]
        cache_item_id = Column(Integer, index=True)  # type: ignore[assignment]
        sort_index = Column(Integer, default=0)  # type: ignore[assignment]
        kind = Column(String(50))  # type: ignore[assignment]
        label = Column(String(200))  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        episode_title = Column(String(500))  # type: ignore[assignment]
        quality = Column(String(100))  # type: ignore[assignment]
        resolution = Column(String(100))  # type: ignore[assignment]
        video_codec = Column(String(100))  # type: ignore[assignment]
        audio_codec = Column(String(100))  # type: ignore[assignment]
        audio_channels = Column(String(50))  # type: ignore[assignment]
        container = Column(String(50))  # type: ignore[assignment]
        bitrate = Column(String(50))  # type: ignore[assignment]
        source_name = Column(String(200))  # type: ignore[assignment]
        path = Column(Text)  # type: ignore[assignment]
        size = Column(BigInteger)  # type: ignore[assignment]
        media_source_id = Column(String(100))  # type: ignore[assignment]
        added_at = Column(DateTime)  # type: ignore[assignment]
        video_details = Column(Text)  # type: ignore[assignment]
        audio_details = Column(Text)  # type: ignore[assignment]
        audio_ita = Column(Text)  # type: ignore[assignment]
        audio_eng = Column(Text)  # type: ignore[assignment]
        audio_fra = Column(Text)  # type: ignore[assignment]
        audio_spa = Column(Text)  # type: ignore[assignment]
        audio_ger = Column(Text)  # type: ignore[assignment]
        audio_jpn = Column(Text)  # type: ignore[assignment]
        audio_langs = Column(Text)  # type: ignore[assignment]
        subtitle_langs = Column(Text)  # type: ignore[assignment]
        created_at = Column(DateTime, default=_utcnow)  # type: ignore[assignment]

    class EmbyLatestCacheError(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_cache_errors"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        cache_kind = Column(String(20), index=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        message = Column(Text, nullable=False)  # type: ignore[assignment]
        created_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyImageCache(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_image_cache"
        cache_key = Column(String(255), primary_key=True)  # type: ignore[assignment]
        image_url = Column(Text, nullable=False)  # type: ignore[assignment]
        mime_type = Column(String(100))  # type: ignore[assignment]
        image_data = Column(LargeBinary)  # type: ignore[assignment]
        image_hash = Column(String(64))  # type: ignore[assignment]
        created_at = Column(DateTime, default=_utcnow)  # type: ignore[assignment]
        expires_at = Column(DateTime)  # type: ignore[assignment]

    class EmbyLatestStateMovie(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_state_movies"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        state_key = Column(String(255), primary_key=True)  # type: ignore[assignment]
        item_id = Column(String(36), index=True)  # type: ignore[assignment]
        signature = Column(String(255))  # type: ignore[assignment]
        title = Column(String(500))  # type: ignore[assignment]
        year = Column(Integer)  # type: ignore[assignment]
        last_seen_at = Column(DateTime, index=True)  # type: ignore[assignment]
        media_source_keys = Column(ARRAY(String))  # type: ignore[assignment]
        notified = Column(Boolean, default=False)  # type: ignore[assignment]
        notified_at = Column(DateTime)  # type: ignore[assignment]

    class EmbyLatestStateSeries(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_state_series"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        series_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        title = Column(String(500))  # type: ignore[assignment]
        year = Column(Integer)  # type: ignore[assignment]
        last_seen_at = Column(DateTime, index=True)  # type: ignore[assignment]
        seasons = Column(ARRAY(Integer))  # type: ignore[assignment]
        notified = Column(Boolean, default=False)  # type: ignore[assignment]
        notified_at = Column(DateTime)  # type: ignore[assignment]

    class EmbyLatestStateEpisode(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_state_episodes"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        series_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        episode_key = Column(String(255), primary_key=True)  # type: ignore[assignment]
        episode_id = Column(String(36), index=True)  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        title = Column(String(500))  # type: ignore[assignment]
        last_seen_at = Column(DateTime, index=True)  # type: ignore[assignment]
        media_source_keys = Column(ARRAY(String))  # type: ignore[assignment]

    class EmbyLatestStateSeriesGroup(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_state_series_groups"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        series_id = Column(String(36), index=True)  # type: ignore[assignment]
        sort_index = Column(Integer, default=0)  # type: ignore[assignment]
        update_type = Column(String(20))  # type: ignore[assignment]
        update_label = Column(String(200))  # type: ignore[assignment]
        batch_id = Column(String(255))  # type: ignore[assignment]
        added_at = Column(DateTime)  # type: ignore[assignment]

    class EmbyLatestStateSeriesChange(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_state_series_changes"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        group_id = Column(Integer, index=True)  # type: ignore[assignment]
        sort_index = Column(Integer, default=0)  # type: ignore[assignment]
        kind = Column(String(50))  # type: ignore[assignment]
        label = Column(String(200))  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        episode_title = Column(String(500))  # type: ignore[assignment]
        quality = Column(String(100))  # type: ignore[assignment]
        resolution = Column(String(100))  # type: ignore[assignment]
        video_codec = Column(String(100))  # type: ignore[assignment]
        audio_codec = Column(String(100))  # type: ignore[assignment]
        audio_channels = Column(String(50))  # type: ignore[assignment]
        container = Column(String(50))  # type: ignore[assignment]
        bitrate = Column(String(50))  # type: ignore[assignment]
        source_name = Column(String(200))  # type: ignore[assignment]
        path = Column(Text)  # type: ignore[assignment]
        size = Column(BigInteger)  # type: ignore[assignment]
        media_source_id = Column(String(100))  # type: ignore[assignment]
        added_at = Column(DateTime)  # type: ignore[assignment]
        video_details = Column(Text)  # type: ignore[assignment]
        audio_details = Column(Text)  # type: ignore[assignment]
        audio_ita = Column(Text)  # type: ignore[assignment]
        audio_eng = Column(Text)  # type: ignore[assignment]
        audio_fra = Column(Text)  # type: ignore[assignment]
        audio_spa = Column(Text)  # type: ignore[assignment]
        audio_ger = Column(Text)  # type: ignore[assignment]
        audio_jpn = Column(Text)  # type: ignore[assignment]
        audio_langs = Column(Text)  # type: ignore[assignment]
        subtitle_langs = Column(Text)  # type: ignore[assignment]

    class EmbyCollectionDefinition(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_collection_definitions"
        id = Column(String(50), primary_key=True)  # type: ignore[assignment]
        data = Column(JSON, nullable=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyCollectionPoster(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_collection_posters"
        collection_id = Column(String(50), primary_key=True)  # type: ignore[assignment]
        mime_type = Column(String(50))  # type: ignore[assignment]
        data = Column(LargeBinary)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyCollectionBackdrop(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_collection_backdrops"
        collection_id = Column(String(50), primary_key=True)  # type: ignore[assignment]
        mime_type = Column(String(50))  # type: ignore[assignment]
        data = Column(LargeBinary)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class RequestRuleEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "request_rule_entries"
        request_id = Column(String(50), primary_key=True)  # type: ignore[assignment]
        rules = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class ScanResultEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "scan_results"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        generated_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]

    class RequestCacheEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "request_cache"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        request_id = Column(String(50), index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyLatestProgress(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_latest_progress"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        state = Column(String(50))  # type: ignore[assignment]
        total = Column(Integer)  # type: ignore[assignment]
        completed = Column(Integer)  # type: ignore[assignment]
        message = Column(Text)  # type: ignore[assignment]
        started_at = Column(DateTime)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class LibraryAssociation(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "library_associations"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        library_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        group_name = Column(String(500), index=True)  # type: ignore[assignment]
        collection_type = Column(String(50))  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class LibraryGroupOrder(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "library_group_order"
        collection_type = Column(String(50), primary_key=True)  # type: ignore[assignment]
        group_name = Column(String(500), primary_key=True)  # type: ignore[assignment]
        position = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class TabOrder(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "tab_order"
        page = Column(String(50), primary_key=True)  # type: ignore[assignment]
        tab_key = Column(String(100), primary_key=True)  # type: ignore[assignment]
        position = Column(Integer, nullable=False, default=0)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyProbeBlacklist(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_blacklist"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        item_id = Column(String(36), index=True)  # type: ignore[assignment]
        item_name = Column(String(500))  # type: ignore[assignment]
        item_type = Column(String(50))  # type: ignore[assignment]
        reason = Column(Text)  # type: ignore[assignment]
        error_type = Column(String(20))  # type: ignore[assignment]
        retry_count = Column(Integer, default=0)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        server_name = Column(String(255))  # type: ignore[assignment]
        library_id = Column(String(36))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        scope = Column(String(20))  # type: ignore[assignment]
        failed_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyProbeQueue(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_queue"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        item_id = Column(String(36), index=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        scope = Column(String(20))  # type: ignore[assignment]
        library_id = Column(String(36))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        name = Column(String(500))  # type: ignore[assignment]
        series_name = Column(String(500))  # type: ignore[assignment]
        season_number = Column(Integer)  # type: ignore[assignment]
        episode_number = Column(Integer)  # type: ignore[assignment]
        year = Column(Integer)  # type: ignore[assignment]
        media_type = Column(String(50))  # type: ignore[assignment]
        path = Column(Text)  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyProbeHistory(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_history"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        item_id = Column(String(36), index=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        media_source_id = Column(String(36))  # type: ignore[assignment]
        scope = Column(String(20))  # type: ignore[assignment]
        name = Column(String(500))  # type: ignore[assignment]
        library_name = Column(String(500))  # type: ignore[assignment]
        processed_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]
        status = Column(String(20))  # type: ignore[assignment]
        error_details = Column(Text)  # type: ignore[assignment]
        duration_ms = Column(Integer)  # type: ignore[assignment]

    class JustWatchCache(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "justwatch_cache"
        show_name = Column(String(500), primary_key=True)  # type: ignore[assignment]
        season = Column(Integer, primary_key=True, default=0)  # type: ignore[assignment]
        episode = Column(Integer, primary_key=True, default=0)  # type: ignore[assignment]
        is_available = Column(Boolean, default=False)  # type: ignore[assignment]
        providers = Column(JSON)  # type: ignore[assignment]
        last_checked = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]

    class RssItem(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "rss_items"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        source_name = Column(String(200))  # type: ignore[assignment]
        source_url = Column(String(1000))  # type: ignore[assignment]
        source_tags = Column(JSON)  # type: ignore[assignment]
        title = Column(String(1000))  # type: ignore[assignment]
        link = Column(String(2000))  # type: ignore[assignment]
        guid = Column(String(1000))  # type: ignore[assignment]
        author = Column(String(500))  # type: ignore[assignment]
        summary = Column(Text)  # type: ignore[assignment]
        content = Column(Text)  # type: ignore[assignment]
        categories = Column(ARRAY(String))  # type: ignore[assignment]
        published_at = Column(DateTime)  # type: ignore[assignment]
        updated_at = Column(DateTime)  # type: ignore[assignment]
        ingested_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        extra = Column(JSON)  # type: ignore[assignment]

    class CategoryBlacklist(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "category_blacklist"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        category_name = Column(String(200), index=True)  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class CategoryHidden(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "category_hidden"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        category_name = Column(String(200), index=True)  # type: ignore[assignment]
        added_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyProbeRecentScan(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_probe_recent_scans"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), index=True)  # type: ignore[assignment]
        library_id = Column(String(36), index=True)  # type: ignore[assignment]
        server_name = Column(String(255))  # type: ignore[assignment]
        event_type = Column(String(50))  # type: ignore[assignment]
        status = Column(String(50))  # type: ignore[assignment]
        last_scan_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]
        oldest_scanned_timestamp = Column(DateTime)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]

    class KeyValueEntry(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "key_value"
        key = Column(String(100), primary_key=True)  # type: ignore[assignment]
        value = Column(JSON, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyUserLink(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_user_links"
        server_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        user_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        group_id = Column(String(255))  # type: ignore[assignment]
        username = Column(String(255), nullable=False)  # type: ignore[assignment]
        link_key = Column(String(255), nullable=True, index=True)  # type: ignore[assignment]
        is_leader = Column(Boolean, default=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyUserBackup(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_user_backups"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        server_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        user_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        username = Column(String(255), nullable=True)  # type: ignore[assignment]
        backup_type = Column(String(50), nullable=True)  # type: ignore[assignment]
        data = Column(JSON, nullable=False)  # type: ignore[assignment]
        created_at = Column(DateTime, default=_utcnow, nullable=False)  # type: ignore[assignment]

    class EmbyIconProfile(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_profiles"
        id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        label = Column(String(255), nullable=False)  # type: ignore[assignment]
        is_group_profile = Column(Boolean, default=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyIconRule(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_rules"
        profile_id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        column_key = Column(String(100), primary_key=True)  # type: ignore[assignment]
        icon_path = Column(Text)  # type: ignore[assignment]
        image_data = Column(LargeBinary)  # type: ignore[assignment]
        mime_type = Column(String(50))  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyIconBinding(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_icon_bindings"
        target_type = Column(String(20), primary_key=True)  # type: ignore[assignment]
        target_id = Column(String(255), primary_key=True)  # type: ignore[assignment]
        profile_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class EmbyGroupPassword(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "emby_group_passwords"
        group_id = Column(String(255), primary_key=True)  # type: ignore[assignment]
        password_enc = Column(Text, nullable=False)  # type: ignore[assignment]
        updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)  # type: ignore[assignment]

    class WorkflowExecution(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "workflow_executions"
        id = Column(String(36), primary_key=True)  # type: ignore[assignment]
        workflow_type = Column(String(20), nullable=False)  # type: ignore[assignment]
        status = Column(String(20), nullable=False, index=True)  # type: ignore[assignment]
        context = Column(JSON, nullable=True)  # type: ignore[assignment]
        error = Column(Text, nullable=True)  # type: ignore[assignment]
        started_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        completed_at = Column(DateTime, nullable=True)  # type: ignore[assignment]

    class ManualSearchHistory(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "manual_search_history"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        generated_at = Column(DateTime, default=_utcnow, nullable=False, index=True)  # type: ignore[assignment]
        payload = Column(JSON, nullable=False)  # type: ignore[assignment]

    class WorkflowStep(Base):  # type: ignore[valid-type,misc]
        __tablename__ = "workflow_steps"
        id = Column(Integer, primary_key=True, autoincrement=True)  # type: ignore[assignment]
        workflow_id = Column(String(36), nullable=False, index=True)  # type: ignore[assignment]
        step_id = Column(String(20), nullable=False)  # type: ignore[assignment]
        step_index = Column(Integer, nullable=False)  # type: ignore[assignment]
        status = Column(String(20), nullable=False)  # type: ignore[assignment]
        progress = Column(Integer, default=0)  # type: ignore[assignment]
        details = Column(Text, nullable=True)  # type: ignore[assignment]
        started_at = Column(DateTime, nullable=True)  # type: ignore[assignment]
        completed_at = Column(DateTime, nullable=True)  # type: ignore[assignment]
        duration_seconds = Column(Integer, nullable=True)  # type: ignore[assignment]

else:
    _PLACEHOLDER = object
    AppSettings = EmbyLatestCacheMeta = EmbyLatestCacheItem = JellyseerrRequest = EmbyLatestCacheChange = EmbyLatestCacheError = EmbyImageCache = EmbyLatestStateMovie = EmbyLatestStateSeries = EmbyLatestStateEpisode = EmbyLatestStateSeriesGroup = EmbyLatestStateSeriesChange = EmbyCollectionDefinition = EmbyCollectionPoster = EmbyCollectionBackdrop = RequestRuleEntry = ScanResultEntry = RequestCacheEntry = EmbyLatestProgress = LibraryAssociation = LibraryGroupOrder = TabOrder = EmbyProbeBlacklist = EmbyProbeQueue = EmbyProbeHistory = JustWatchCache = RssItem = CategoryBlacklist = CategoryHidden = EmbyProbeRecentScan = KeyValueEntry = EmbyUserLink = EmbyUserBackup = EmbyIconProfile = EmbyIconRule = EmbyIconBinding = EmbyGroupPassword = WorkflowExecution = ManualSearchHistory = WorkflowStep = _PLACEHOLDER  # type: ignore[assignment]


__all__ = [
    "SQLALCHEMY_AVAILABLE",
    "SQLAlchemyError",
    "Base",
    "_utcnow",
    "create_engine",
    "func",
    "or_",
    "text",
    "sessionmaker",
    "AppSettings",
    "EmbyLatestCacheMeta",
    "EmbyLatestCacheItem",
    "JellyseerrRequest",
    "EmbyLatestCacheChange",
    "EmbyLatestCacheError",
    "EmbyImageCache",
    "EmbyLatestStateMovie",
    "EmbyLatestStateSeries",
    "EmbyLatestStateEpisode",
    "EmbyLatestStateSeriesGroup",
    "EmbyLatestStateSeriesChange",
    "EmbyCollectionDefinition",
    "EmbyCollectionPoster",
    "EmbyCollectionBackdrop",
    "RequestRuleEntry",
    "ScanResultEntry",
    "RequestCacheEntry",
    "EmbyLatestProgress",
    "LibraryAssociation",
    "LibraryGroupOrder",
    "TabOrder",
    "EmbyProbeBlacklist",
    "EmbyProbeQueue",
    "EmbyProbeHistory",
    "JustWatchCache",
    "RssItem",
    "CategoryBlacklist",
    "CategoryHidden",
    "EmbyProbeRecentScan",
    "KeyValueEntry",
    "EmbyUserLink",
    "EmbyUserBackup",
    "EmbyIconProfile",
    "EmbyIconRule",
    "EmbyIconBinding",
    "EmbyGroupPassword",
    "WorkflowExecution",
    "ManualSearchHistory",
    "WorkflowStep",
]
