"""
Data models for Latest Publications system.
Defines TypedDicts, dataclasses, and enums for type safety.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ProgressState(str, Enum):
    """Progress state for background operations."""
    IDLE = "idle"
    COLLECTING = "collecting"
    ENRICHING = "enriching"
    DONE = "done"
    ERROR = "error"


class LatestItemType(str, Enum):
    """Item type classification."""
    MOVIE = "Movie"
    SERIES = "Series"
    EPISODE = "Episode"


class LatestChangeKind(str, Enum):
    """Change type classification."""
    NEW = "new"
    NEW_SOURCE = "new_source"
    QUALITY_UPGRADE = "quality_upgrade"
    NEW_EPISODE = "new_episode"
    NEW_SEASON = "new_season"


# TypedDicts for data structures

class LatestChange(TypedDict, total=False):
    """Represents a change/update to a media item."""
    kind: str  # "new_source", "quality_upgrade", etc.
    label: str
    sort_index: int
    season_number: Optional[int]
    episode_number: Optional[int]
    episode_title: Optional[str]
    quality: Optional[str]
    resolution: Optional[str]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    audio_channels: Optional[str]
    container: Optional[str]
    bitrate: Optional[str]
    source_name: Optional[str]
    path: Optional[str]
    size: Optional[int]
    media_source_id: Optional[str]
    added_at: Optional[datetime]
    video_details: Optional[str]
    audio_details: Optional[str]
    audio_langs: Optional[str]
    subtitle_langs: Optional[str]


class LatestItem(TypedDict, total=False):
    """Represents a latest publication item (movie or series)."""
    # Core identifiers
    item_id: str
    server_id: str
    item_type: str  # "Movie" or "Series"
    signature: str
    batch_id: Optional[str]

    # Basic metadata
    title: str
    original_title: Optional[str]
    year: Optional[int]
    overview: Optional[str]
    tagline: Optional[str]

    # Series-specific
    series_name: Optional[str]
    season_name: Optional[str]
    season_number: Optional[int]
    episode_number: Optional[int]
    episode_title: Optional[str]
    season_count: Optional[int]
    episode_count: Optional[int]
    child_count: Optional[int]

    # Ratings
    community_rating: Optional[float]
    official_rating: Optional[str]
    tmdb_rating: Optional[str]
    tmdb_votes: Optional[str]
    imdb_rating: Optional[str]
    imdb_votes: Optional[str]
    metacritic_rating: Optional[str]
    trakt_rating: Optional[str]
    trakt_votes: Optional[str]

    # Media info
    runtime_minutes: Optional[int]
    genres: List[str]
    studios: List[str]
    cast_members: List[str]
    directors: List[str]
    creators: List[str]

    # Images
    image_tag: Optional[str]
    image_url: Optional[str]
    poster_url: Optional[str]
    backdrop_url: Optional[str]
    banner_url: Optional[str]
    thumb_url: Optional[str]
    logo_url: Optional[str]
    emby_url: Optional[str]
    tmdb_poster_url: Optional[str]
    tmdb_backdrop_url: Optional[str]
    tmdb_banner_url: Optional[str]
    tmdb_thumb_url: Optional[str]

    # External IDs
    tmdb_id: Optional[str]
    imdb_id: Optional[str]
    tvdb_id: Optional[str]
    trakt_id: Optional[str]

    # Dates
    added_at: Optional[datetime]
    premiere_date: Optional[datetime]
    omdb_fetched_at: Optional[datetime]

    # Server/Library
    library_id: Optional[str]
    library_name: Optional[str]
    server_name: Optional[str]
    server_icon: Optional[str]
    server_icon_color: Optional[str]
    server_icon_style: Optional[str]

    # Update tracking
    update_type: Optional[str]
    update_label: Optional[str]
    changes: List[LatestChange]

    # Sorting
    sort_ts: Optional[datetime]


class LatestError(TypedDict):
    """Represents an error during collection."""
    server_id: str
    message: str


class LatestPayload(TypedDict):
    """Complete payload for latest items."""
    movies: List[LatestItem]
    series: List[LatestItem]
    errors: List[LatestError]


class LatestCacheData(TypedDict):
    """Cache data structure."""
    payload: LatestPayload
    updated_at: str  # ISO datetime
    params: Dict[str, int]  # {limit, per_server_limit}


class LatestStateMovieItem(TypedDict, total=False):
    """State tracking for a movie."""
    item_id: str
    signature: str
    title: str
    year: Optional[int]
    last_seen_at: datetime
    media_source_keys: List[str]
    notified: bool
    notified_at: Optional[datetime]


class LatestStateSeriesItem(TypedDict, total=False):
    """State tracking for a series."""
    series_id: str
    title: str
    year: Optional[int]
    last_seen_at: datetime
    seasons: List[int]
    notified: bool
    notified_at: Optional[datetime]
    episodes: Dict[str, Any]  # episode_key -> episode data
    last_changes: List[Dict[str, Any]]  # Change groups


class LatestState(TypedDict):
    """Complete state structure (server_id -> content)."""
    # server_id: {movies: {items: {...}}, series: {items: {...}}}


class ProgressSnapshot(TypedDict):
    """Progress tracking snapshot."""
    state: str  # ProgressState enum value
    total: int
    completed: int
    message: str
    started_at: Optional[str]  # ISO datetime
    updated_at: Optional[str]  # ISO datetime


class ProgressResponse(TypedDict):
    """Response from progress endpoint."""
    progress: ProgressSnapshot
    refreshing: bool


# Dataclasses for structured data

@dataclass
class LatestBatch:
    """Represents a batch of items grouped by time window."""
    server_id: str
    item_type: str  # "Movie" or "Series"
    items: List[LatestItem] = field(default_factory=list)
    batch_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    gap_minutes: int = 10  # Default 10-minute gap

    def add_item(self, item: LatestItem) -> None:
        """Add item to batch."""
        self.items.append(item)

    def compute_batch_id(self) -> str:
        """Generate batch ID from items."""
        if not self.items:
            return ""

        from emby_latest.batch_processor import build_batch_id
        self.batch_id = build_batch_id(self.server_id, self.item_type, self.items)
        return self.batch_id


@dataclass
class MediaVersion:
    """Represents a media source version."""
    media_source_id: str
    quality: Optional[str] = None
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[str] = None
    container: Optional[str] = None
    bitrate: Optional[str] = None
    path: Optional[str] = None
    size: Optional[int] = None
    added_at: Optional[datetime] = None
    video_details: Optional[str] = None
    audio_details: Optional[str] = None
    audio_langs: Optional[str] = None
    subtitle_langs: Optional[str] = None


@dataclass
class EnrichmentResult:
    """Result from enrichment operation."""
    success: bool
    enriched_entry: Optional[LatestItem] = None
    added_fields: List[str] = field(default_factory=list)
    updated_fields: List[str] = field(default_factory=list)
    unchanged_fields: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class NotificationResult:
    """Result from notification dispatch."""
    sent: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    server_filter: Optional[str] = None


# Constants

VALID_ITEM_TYPES = [LatestItemType.MOVIE, LatestItemType.SERIES, LatestItemType.EPISODE]
VALID_CACHE_KINDS = ["feed", "batch"]
VALID_PROGRESS_STATES = [state.value for state in ProgressState]

DEFAULT_BATCH_GAP_MINUTES = 10
DEFAULT_CACHE_TTL_SECONDS = 60
DEFAULT_MAX_ITEMS = 200
DEFAULT_PER_SERVER_LIMIT = 50
DEFAULT_RETENTION_DAYS = 30
DEFAULT_OMDB_CACHE_HOURS = 168  # 7 days
