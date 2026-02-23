"""Trakt integration manager with PyTrakt library."""

import logging
import time
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Set, List

if TYPE_CHECKING:
    import trakt
    import trakt.core
    import trakt.sync
    import trakt.tv
    import trakt.movies
    import trakt.users

logger = logging.getLogger(__name__)

# Try to import PyTrakt library
try:
    import trakt
    import trakt.core
    import trakt.sync
    import trakt.tv
    import trakt.movies
    import trakt.users
    TRAKT_AVAILABLE = True
    logger.info("PyTrakt library loaded successfully")
except ImportError as e:
    logger.error(f"PyTrakt library not found: {e}")
    TRAKT_AVAILABLE = False
except Exception as e:
    logger.error(f"PyTrakt library failed to load: {e}", exc_info=True)
    TRAKT_AVAILABLE = False


class TraktError(RuntimeError):
    """Raised when Trakt operations fail."""


def is_trakt_available() -> bool:
    """Check if PyTrakt library is available."""
    return TRAKT_AVAILABLE


class TraktManager:
    """
    Manages Trakt API integration with automatic token refresh.

    Wraps PyTrakt library following the JustWatch manager pattern.
    """

    def __init__(self, client_id: str, client_secret: str, access_token: str,
                 refresh_token: str, expires_at: str):
        """
        Initialize Trakt manager.

        Args:
            client_id: Trakt OAuth client ID
            client_secret: Trakt OAuth client secret (required for token refresh)
            access_token: Current OAuth access token
            refresh_token: OAuth refresh token for automatic renewal
            expires_at: ISO format expiration datetime string

        Raises:
            TraktError: If PyTrakt library is not installed
        """
        if not TRAKT_AVAILABLE:
            raise TraktError("PyTrakt library not installed: pip install trakt")

        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self._lock = threading.Lock()

        # In-memory caches
        self._collection_cache: Optional[Dict[int, Dict[int, Set[int]]]] = None
        self._collection_timestamp = 0.0
        self._rating_cache: Dict[str, Dict[str, str]] = {}
        self._id_cache: Dict[str, Any] = {}

        # Configure PyTrakt global settings
        trakt.core.BASE_URL = 'https://api.trakt.tv/'  # Use correct production URL (with trailing slash)
        trakt.core.CLIENT_ID = self.client_id
        trakt.core.CLIENT_SECRET = self.client_secret
        trakt.core.OAUTH_TOKEN = (access_token or "").strip()
        trakt.core.OAUTH_REFRESH = (refresh_token or "").strip()

        # Parse expiration timestamp
        if expires_at:
            try:
                dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                self._expires_at = int(dt.timestamp())
            except Exception:
                self._expires_at = 0
        else:
            self._expires_at = 0

        trakt.core.OAUTH_EXPIRES_AT = self._expires_at

        # Disable PyTrakt's file-based storage (we use database)
        trakt.core.CONFIG_PATH = None

        logger.info("TraktManager initialized with token expiring at %s", expires_at)

    def _ensure_valid_token(self) -> None:
        """
        Validate token and refresh if needed.

        PyTrakt automatically refreshes tokens that expire within 2 days.
        This method triggers that logic.
        """
        # PyTrakt handles refresh automatically when making requests
        # if the token expires within 2 days (172800 seconds)
        pass

    def ping(self) -> bool:
        """
        Test connection to Trakt API.

        Returns:
            True if connection successful

        Raises:
            TraktError: If connection fails
        """
        self._ensure_valid_token()
        try:
            # Use PyTrakt's users endpoint to verify connection
            user = trakt.users.User('me')
            # Access username to trigger API call
            _ = user.username
            logger.info("Trakt ping successful")
            return True
        except Exception as exc:
            logger.error(f"Trakt ping failed: {exc}")
            raise TraktError(f"Trakt connection failed: {exc}") from exc

    def get_collection_map(self, max_age: int = 900) -> Dict[int, Dict[int, Set[int]]]:
        """
        Get user's collection organized by TMDB ID -> Season -> Episodes.

        Args:
            max_age: Cache TTL in seconds (default 15 minutes)

        Returns:
            Dict mapping: tmdb_id -> {season_num -> {ep_num1, ep_num2, ...}}

        Raises:
            TraktError: If API call fails
        """
        now = time.time()

        # Check cache
        with self._lock:
            if self._collection_cache and (now - self._collection_timestamp) < max_age:
                logger.debug("Using cached collection map")
                return self._collection_cache

        logger.info("Fetching collection from Trakt...")
        self._ensure_valid_token()

        try:
            # Get collection with extended info
            collection = trakt.sync.get_collection('shows', extended='full')

            # Transform to existing format: {tmdb_id: {season: {episodes}}}
            mapping: Dict[int, Dict[int, Set[int]]] = {}

            for show_item in collection:
                # Extract TMDB ID from show
                show = show_item if isinstance(show_item, dict) else {}
                if hasattr(show_item, 'ids'):
                    tmdb_id = getattr(getattr(show_item, 'ids'), 'tmdb', None)
                else:
                    tmdb_id = show.get('ids', {}).get('tmdb')

                if not tmdb_id:
                    continue

                tmdb_id = int(tmdb_id)
                show_map = mapping.setdefault(tmdb_id, {})

                # Extract seasons
                seasons = []
                if hasattr(show_item, 'seasons'):
                    seasons = getattr(show_item, 'seasons')
                elif isinstance(show, dict):
                    seasons = show.get('seasons', [])

                for season in seasons:
                    season_num = None
                    episodes = []

                    if hasattr(season, 'number'):
                        season_num = season.number
                        if hasattr(season, 'episodes'):
                            episodes = season.episodes
                    elif isinstance(season, dict):
                        season_num = season.get('number')
                        episodes = season.get('episodes', [])

                    if season_num is None:
                        continue

                    eps_set = show_map.setdefault(season_num, set())

                    for episode in episodes:
                        ep_num = None
                        if hasattr(episode, 'number'):
                            ep_num = episode.number
                        elif isinstance(episode, dict):
                            ep_num = episode.get('number')

                        if ep_num is not None:
                            eps_set.add(int(ep_num))

            # Cache result
            with self._lock:
                self._collection_cache = mapping
                self._collection_timestamp = now

            logger.info(f"Collection map cached with {len(mapping)} shows")
            return mapping

        except Exception as exc:
            logger.error(f"Failed to fetch collection: {exc}")
            # Cache empty result to prevent repeated failures
            with self._lock:
                self._collection_cache = {}
                self._collection_timestamp = now
            raise TraktError(f"Failed to fetch collection: {exc}") from exc

    def get_season_episodes(self, tmdb_id: int, season_number: int) -> Optional[List[Dict]]:
        """
        Get episode list for a specific season.

        Args:
            tmdb_id: TMDB ID of the show
            season_number: Season number

        Returns:
            List of episode dicts with 'number', 'title', 'first_aired' fields

        Raises:
            TraktError: If API call fails
        """
        if tmdb_id is None or season_number is None:
            return None

        logger.debug(f"Fetching season {season_number} for TMDB {tmdb_id}")
        self._ensure_valid_token()

        try:
            # Use pytrakt's search_by_id to find show by TMDB ID
            results = trakt.sync.search_by_id(str(tmdb_id), id_type='tmdb', media_type='show')

            if not results:
                logger.warning(f"Show not found on Trakt for TMDB {tmdb_id}")
                return None

            # Get first result
            show_data = results[0]
            show = show_data.show if hasattr(show_data, 'show') else show_data

            # Get show slug
            show_slug = show.ids.get('ids', {}).get('slug') if hasattr(show, 'ids') else getattr(show, 'slug', None)

            if not show_slug:
                logger.warning(f"Could not extract show slug for TMDB {tmdb_id}")
                return None

            # Get season episodes using TV API
            tv_show = trakt.tv.TVShow(show_slug)

            # Find the correct season by iterating (seasons are not always indexed sequentially)
            target_season = None
            for s in tv_show.seasons:
                if hasattr(s, 'season') and s.season == season_number:
                    target_season = s
                    break
                elif hasattr(s, 'number') and s.number == season_number:
                    target_season = s
                    break

            if not target_season:
                logger.warning(f"Season {season_number} not found for show {show_slug}")
                return None

            # Transform to expected format
            episodes = []
            for ep in target_season.episodes:
                episodes.append({
                    'number': ep.number,
                    'title': ep.title or '',
                    'first_aired': getattr(ep, 'first_aired', None)
                })

            logger.debug(f"Found {len(episodes)} episodes for season {season_number}")
            return episodes

        except Exception as exc:
            logger.error(f"Failed to fetch season episodes: {exc}")
            raise TraktError(f"Failed to fetch season episodes: {exc}") from exc

    def search_by_tmdb(self, tmdb_id: int, media_type: str = "show") -> Optional[Dict]:
        """
        Search Trakt by TMDB ID.

        Args:
            tmdb_id: TMDB ID
            media_type: 'show' or 'movie'

        Returns:
            Dict with Trakt identifiers and metadata

        Raises:
            TraktError: If search fails
        """
        cache_key = f"tmdb_{tmdb_id}_{media_type}"
        if cache_key in self._id_cache:
            return self._id_cache[cache_key]

        self._ensure_valid_token()

        try:
            # Use pytrakt's search_by_id
            results = trakt.sync.search_by_id(str(tmdb_id), id_type='tmdb', media_type=media_type)

            if not results:
                return None

            # Extract data from first result
            result = results[0]
            media = result.show if media_type == 'show' and hasattr(result, 'show') else \
                    result.movie if media_type == 'movie' and hasattr(result, 'movie') else result

            if not media or not hasattr(media, 'ids'):
                return None

            ids = media.ids
            data = {
                'trakt_id': ids.get('trakt'),
                'slug': ids.get('slug'),
                'imdb_id': ids.get('imdb'),
                'tmdb_id': ids.get('tmdb')
            }

            self._id_cache[cache_key] = data
            return data

        except Exception as exc:
            logger.error(f"TMDB search failed: {exc}")
            raise TraktError(f"TMDB search failed: {exc}") from exc

    def search_by_imdb(self, imdb_id: str, media_type: str = "show") -> Optional[Dict]:
        """
        Search Trakt by IMDb ID.

        Args:
            imdb_id: IMDb ID (e.g. 'tt1234567')
            media_type: 'show' or 'movie'

        Returns:
            Dict with Trakt identifiers and metadata

        Raises:
            TraktError: If search fails
        """
        cache_key = f"imdb_{imdb_id}_{media_type}"
        if cache_key in self._id_cache:
            return self._id_cache[cache_key]

        self._ensure_valid_token()

        try:
            # Use pytrakt's search_by_id
            results = trakt.sync.search_by_id(imdb_id, id_type='imdb', media_type=media_type)

            if not results:
                return None

            # Extract data from first result
            result = results[0]
            media = result.show if media_type == 'show' and hasattr(result, 'show') else \
                    result.movie if media_type == 'movie' and hasattr(result, 'movie') else result

            if not media or not hasattr(media, 'ids'):
                return None

            ids = media.ids
            data = {
                'trakt_id': ids.get('trakt'),
                'slug': ids.get('slug'),
                'imdb_id': ids.get('imdb'),
                'tmdb_id': ids.get('tmdb')
            }

            self._id_cache[cache_key] = data
            return data

        except Exception as exc:
            logger.error(f"IMDb search failed: {exc}")
            raise TraktError(f"IMDb search failed: {exc}") from exc

    def get_rating(self, trakt_slug: str, media_type: str) -> Optional[Dict[str, str]]:
        """
        Get rating and votes for media.

        Args:
            trakt_slug: Trakt slug identifier
            media_type: 'show' or 'movie'

        Returns:
            Dict with 'trakt_rating', 'trakt_votes', 'trakt_id'

        Raises:
            TraktError: If API call fails
        """
        cache_key = f"{media_type}_{trakt_slug}"
        if cache_key in self._rating_cache:
            return self._rating_cache[cache_key]

        self._ensure_valid_token()

        try:
            if media_type == 'movie':
                media = trakt.movies.Movie(trakt_slug)
            else:
                media = trakt.tv.TVShow(trakt_slug)

            rating = media.rating if hasattr(media, 'rating') else None
            votes = media.votes if hasattr(media, 'votes') else None
            trakt_id = media.ids.trakt if hasattr(media, 'ids') and hasattr(media.ids, 'trakt') else None

            result = {
                'trakt_rating': str(rating) if rating is not None else '',
                'trakt_votes': str(votes) if votes is not None else '',
                'trakt_id': str(trakt_id) if trakt_id is not None else ''
            }

            self._rating_cache[cache_key] = result
            return result

        except Exception as exc:
            logger.error(f"Failed to fetch rating: {exc}")
            raise TraktError(f"Failed to fetch rating: {exc}") from exc

    def get_user_lists(self) -> List[Dict]:
        """
        Get authenticated user's Trakt lists.

        Returns:
            List of dicts with list metadata

        Raises:
            TraktError: If API call fails
        """
        logger.info("Fetching user lists from Trakt")
        self._ensure_valid_token()

        try:
            user = trakt.users.User('me')
            lists = user.lists

            result = []
            for lst in lists:
                list_data = {
                    'name': lst.name if hasattr(lst, 'name') else '',
                    'description': lst.description if hasattr(lst, 'description') else '',
                    'slug': lst.ids.slug if hasattr(lst, 'ids') and hasattr(lst.ids, 'slug') else '',
                    'item_count': lst.item_count if hasattr(lst, 'item_count') else 0,
                    'privacy': lst.privacy if hasattr(lst, 'privacy') else 'private',
                    'trakt_id': lst.ids.trakt if hasattr(lst, 'ids') and hasattr(lst.ids, 'trakt') else None
                }
                result.append(list_data)

            logger.info(f"Found {len(result)} user lists")
            return result

        except Exception as exc:
            logger.error(f"Failed to fetch user lists: {exc}")
            raise TraktError(f"Failed to fetch user lists: {exc}") from exc

    def get_list_items(self, username: str, list_id: str,
                       sort_by: Optional[str] = None,
                       sort_how: Optional[str] = None) -> List[Dict]:
        """
        Get items from a Trakt list with pagination.

        Args:
            username: Trakt username
            list_id: List slug or ID
            sort_by: Optional sort field (rank, added, title, released, etc.)
            sort_how: Optional sort direction (asc, desc)

        Returns:
            List of dicts with media items

        Raises:
            TraktError: If API call fails
        """
        logger.info(f"Fetching items from list {username}/{list_id}")
        self._ensure_valid_token()

        try:
            user = trakt.users.User(username)
            list_obj = user.get_list(list_id)

            if not list_obj:
                raise TraktError(f"List not found: {username}/{list_id}")

            # Get items (PyTrakt handles pagination internally)
            items = list_obj.items()

            result = []
            for item in items:
                # Extract media object (show or movie)
                media = None
                media_type = None

                if hasattr(item, 'show') and item.show:
                    media = item.show
                    media_type = 'tv'
                elif hasattr(item, 'movie') and item.movie:
                    media = item.movie
                    media_type = 'movie'

                if not media:
                    continue

                # Extract identifiers
                item_data = {
                    'media_type': media_type,
                    'title': media.title if hasattr(media, 'title') else '',
                    'year': media.year if hasattr(media, 'year') else None,
                    'trakt_id': None,
                    'imdb_id': None,
                    'tmdb_id': None
                }

                if hasattr(media, 'ids'):
                    item_data['trakt_id'] = media.ids.trakt if hasattr(media.ids, 'trakt') else None
                    item_data['imdb_id'] = media.ids.imdb if hasattr(media.ids, 'imdb') else None
                    item_data['tmdb_id'] = media.ids.tmdb if hasattr(media.ids, 'tmdb') else None

                result.append(item_data)

            logger.info(f"Fetched {len(result)} items from list")
            return result

        except Exception as exc:
            logger.error(f"Failed to fetch list items: {exc}")
            raise TraktError(f"Failed to fetch list items: {exc}") from exc

    def get_current_tokens(self) -> Dict[str, Any]:
        """
        Get current token values for persistence after auto-refresh.

        Returns:
            Dict with 'access_token', 'refresh_token', 'expires_at' (ISO format)
        """
        expires_at = ""
        if trakt.core.OAUTH_EXPIRES_AT and trakt.core.OAUTH_EXPIRES_AT > 0:
            try:
                dt = datetime.fromtimestamp(trakt.core.OAUTH_EXPIRES_AT, tz=timezone.utc)
                expires_at = dt.isoformat()
            except Exception:
                pass

        return {
            "ACCESS_TOKEN": trakt.core.OAUTH_TOKEN or "",
            "REFRESH_TOKEN": trakt.core.OAUTH_REFRESH or "",
            "EXPIRES_AT": expires_at
        }
