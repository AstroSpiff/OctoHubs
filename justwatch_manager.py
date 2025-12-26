"""JustWatch availability checker with database caching."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

try:
    from justwatch import JustWatch
    JUSTWATCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    JUSTWATCH_AVAILABLE = False

if TYPE_CHECKING:
    from storage import DatabaseStorage

logger = logging.getLogger(__name__)


class JustWatchError(RuntimeError):
    """Raised when JustWatch operations fail."""


def is_justwatch_available() -> bool:
    """Check if JustWatch library is available."""
    return JUSTWATCH_AVAILABLE


class JustWatchManager:
    """Manages JustWatch availability checks with intelligent caching."""

    def __init__(self, storage: DatabaseStorage, locale: str = "it_IT"):
        """
        Initialize JustWatch manager.

        Args:
            storage: DatabaseStorage instance for caching
            locale: JustWatch locale (default: it_IT for Italy)
        """
        if not JUSTWATCH_AVAILABLE:  # pragma: no cover - runtime guard
            raise JustWatchError(
                "Per usare JustWatch installa la libreria: pip install JustWatch"
            )
        self.storage = storage
        self.locale = locale
        self.country = locale.split("_")[1].upper()  # IT from it_IT
        self.jw = JustWatch(country=self.country)
        self._last_request_time: Optional[float] = None
        self._min_request_interval = 1.0  # Minimum 1 second between requests

    def _rate_limit(self) -> None:
        """Enforce rate limiting between API requests."""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _search_show(self, show_name: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Search for a show on JustWatch.

        Args:
            show_name: Name of the TV show
            year: Optional year to narrow down results

        Returns:
            Show data if found, None otherwise
        """
        try:
            self._rate_limit()
            results = self.jw.search_for_item(query=show_name, content_types=["show"])

            if not results or "items" not in results or not results["items"]:
                logger.warning(f"Serie '{show_name}' non trovata su JustWatch")
                return None

            # If year provided, try to find matching release year
            if year:
                for item in results["items"]:
                    item_year = item.get("original_release_year")
                    if item_year == year:
                        return item

            # Return first result if no year match or no year provided
            return results["items"][0]

        except Exception as exc:
            logger.error(f"Errore ricerca JustWatch per '{show_name}': {exc}")
            return None

    def _get_season_id(self, show_id: int, season_num: int) -> Optional[int]:
        """
        Get JustWatch internal season_id for a specific season number.

        Args:
            show_id: JustWatch show ID
            season_num: Season number to find

        Returns:
            Internal season_id if found, None otherwise
        """
        try:
            self._rate_limit()

            # Get full show details including all seasons
            show_details = self.jw.get_title(title_id=show_id, content_type="show")

            if not show_details:
                logger.debug(f"Dettagli show non trovati per show_id={show_id}")
                return None

            # Look for seasons list
            seasons = show_details.get("seasons", [])

            if not seasons:
                logger.debug(f"Nessuna stagione trovata nei dettagli di show_id={show_id}")
                return None

            # Find the season matching season_num
            for season in seasons:
                if season.get("season_number") == season_num:
                    season_id = season.get("id")
                    if season_id:
                        logger.debug(
                            f"Trovato season_id={season_id} per stagione {season_num}"
                        )
                        return season_id

            logger.debug(
                f"Stagione {season_num} non trovata tra le {len(seasons)} stagioni "
                f"di show_id={show_id}"
            )
            return None

        except Exception as exc:
            logger.error(
                f"Errore recupero season_id per S{season_num} "
                f"di show_id={show_id}: {exc}"
            )
            return None

    def _get_episode_data(
        self,
        show_id: int,
        season_num: int,
        episode_num: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get data for a specific episode.

        Args:
            show_id: JustWatch show ID
            season_num: Season number
            episode_num: Episode number

        Returns:
            Episode data if found, None otherwise
        """
        try:
            # Step 1: Get internal season_id
            season_id = self._get_season_id(show_id, season_num)

            if not season_id:
                logger.debug(
                    f"Impossibile recuperare season_id per S{season_num} "
                    f"di show_id={show_id}"
                )
                return None

            # Step 2: Get season data using season_id
            self._rate_limit()
            season_data = self.jw.get_season(season_id)

            if not season_data:
                logger.debug(f"Dati stagione non trovati per season_id={season_id}")
                return None

            # Step 3: Look for the specific episode in the season's episodes list
            episodes = season_data.get("episodes", [])

            if not episodes:
                logger.debug(
                    f"Nessun episodio trovato nella stagione {season_num} "
                    f"(season_id={season_id})"
                )
                return None

            for ep in episodes:
                if ep.get("episode_number") == episode_num:
                    logger.debug(
                        f"Episodio {episode_num} trovato nella stagione {season_num} "
                        f"(season_id={season_id})"
                    )
                    return ep

            logger.debug(
                f"Episodio {episode_num} non trovato nella stagione {season_num} "
                f"(trovati {len(episodes)} episodi in season_id={season_id})"
            )
            return None

        except Exception as exc:
            logger.error(
                f"Errore recupero episodio S{season_num}E{episode_num} "
                f"per show_id={show_id}: {exc}"
            )
            return None

    def _check_episode_availability(self, episode_data: Optional[Dict[str, Any]]) -> bool:
        """
        Check if episode has streaming offers available.

        Args:
            episode_data: Episode data from JustWatch

        Returns:
            True if episode is available for streaming, False otherwise
        """
        if not episode_data:
            return False

        # Check if episode has offers
        offers = episode_data.get("offers", [])

        if not offers:
            logger.debug("Nessuna offerta trovata per l'episodio")
            return False

        # Check for valid monetization types
        for offer in offers:
            monetization_type = offer.get("monetization_type", "")
            # Accept: flatrate (subscription), rent, buy
            if monetization_type in ["flatrate", "rent", "buy"]:
                provider_id = offer.get("provider_id", "unknown")
                logger.debug(
                    f"Offerta trovata: {monetization_type} su provider {provider_id}"
                )
                return True

        logger.debug(
            f"Offerte presenti ({len(offers)}) ma nessuna valida "
            f"(flatrate/rent/buy)"
        )
        return False

    def check_availability(
        self,
        show_name: str,
        season_num: int,
        episode_num: int,
        year: Optional[int] = None
    ) -> bool:
        """
        Check if an episode is available for streaming in Italy.

        Uses database caching to minimize API calls:
        - If episode is marked as available (True), never recheck
        - If episode is not available (False), recheck after 24 hours

        Args:
            show_name: TV show name
            season_num: Season number
            episode_num: Episode number
            year: Optional release year for better matching

        Returns:
            True if episode is available for streaming, False otherwise
        """
        # Check cache first
        cached = self.storage.get_justwatch_cache(
            show_name=show_name,
            season=season_num,
            episode=episode_num
        )

        if cached:
            is_available = cached["is_available"]
            last_checked = cached["last_checked"]

            # If available, no need to recheck (episode is released)
            if is_available:
                logger.debug(
                    f"Cache HIT (disponibile): {show_name} S{season_num}E{episode_num}"
                )
                return True

            # If not available, recheck only after 24 hours
            age = datetime.now(timezone.utc) - last_checked
            if age < timedelta(hours=24):
                logger.debug(
                    f"Cache HIT (non disponibile, recente): {show_name} S{season_num}E{episode_num}"
                )
                return False

            logger.debug(
                f"Cache STALE (>24h): {show_name} S{season_num}E{episode_num}"
            )

        # Cache miss or stale - perform actual check
        logger.info(
            f"Verifico disponibilità JustWatch: {show_name} S{season_num}E{episode_num}"
        )

        # Search for the show
        show_data = self._search_show(show_name, year)
        if not show_data:
            # Show not found - cache as not available
            self.storage.save_justwatch_cache(
                show_name=show_name,
                season=season_num,
                episode=episode_num,
                is_available=False
            )
            return False

        show_id = show_data.get("id")
        if not show_id:
            logger.error(f"ID show mancante per '{show_name}'")
            self.storage.save_justwatch_cache(
                show_name=show_name,
                season=season_num,
                episode=episode_num,
                is_available=False
            )
            return False

        # Get specific episode data
        episode_data = self._get_episode_data(show_id, season_num, episode_num)

        # Check if episode is available
        is_available = self._check_episode_availability(episode_data)

        # Save to cache
        self.storage.save_justwatch_cache(
            show_name=show_name,
            season=season_num,
            episode=episode_num,
            is_available=is_available
        )

        logger.info(
            f"JustWatch: {show_name} S{season_num}E{episode_num} - "
            f"{'DISPONIBILE' if is_available else 'NON DISPONIBILE'}"
        )

        return is_available

    def clear_cache(self, show_name: Optional[str] = None) -> int:
        """
        Clear JustWatch cache entries.

        Args:
            show_name: If provided, clear only entries for this show.
                      If None, clear all cache.

        Returns:
            Number of entries cleared
        """
        return self.storage.clear_justwatch_cache(show_name=show_name)

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats (total, available, unavailable)
        """
        return self.storage.get_justwatch_cache_stats()


__all__ = [
    "JustWatchManager",
    "JustWatchError",
    "is_justwatch_available"
]
