"""JustWatch availability checker with database caching."""

from __future__ import annotations

import base64
import logging
import os
import requests
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from core.http_response_limits import read_bounded_json_response
from core.log_sanitization import format_exception_for_log, sanitize_diagnostic_text

if TYPE_CHECKING:
    from core.storage import DatabaseStorage

logger = logging.getLogger(__name__)
TV_EPISODE_CACHE_SUFFIX = "::episode-v2"
JW_HEADERS = {
    "User-Agent": "Mozilla/5.0"
}
JW_GRAPHQL_URL = "https://apis.justwatch.com/graphql"
JW_SEARCH_QUERY = """
query GetSearchTitles($searchTitlesFilter: TitleFilter!, $country: Country!, $language: Language!, $first: Int!, $filter: OfferFilter!) {
  popularTitles(country: $country, filter: $searchTitlesFilter, first: $first, sortBy: POPULAR) {
    edges {
      node {
        id
        objectType
        content(country: $country, language: $language) {
          title
          originalReleaseYear
          fullPath
        }
        offers(country: $country, platform: WEB, filter: $filter) {
          monetizationType
          package {
            clearName
            technicalName
          }
        }
      }
    }
  }
}
"""
JW_TITLE_QUERY = """
fragment TitleOffers on MovieOrShow {
  id
  offers(country: $country, platform: WEB) {
    monetizationType
    package {
      clearName
      technicalName
    }
  }
}

query GetTitleOffers($nodeId: ID!, $country: Country!) {
  node(id: $nodeId) {
    __typename
    ...TitleOffers
  }
}
"""
JW_SHOW_QUERY = """
fragment EpisodeFields on Episode {
  id
  content(country: $country, language: "qa-INVALID") {
    seasonNumber
    episodeNumber
  }
  offers(country: $country, platform: WEB) {
    monetizationType
    package {
      clearName
      technicalName
    }
  }
}

fragment SeasonFields on Season {
  id
  content(country: $country, language: "qa-INVALID") {
    seasonNumber
  }
  episodes {
    ...EpisodeFields
  }
}

fragment ShowFields on Show {
  id
  seasons {
    ...SeasonFields
  }
  offers(country: $country, platform: WEB) {
    monetizationType
    package {
      clearName
      technicalName
    }
  }
}

query GetNodeById($nodeId: ID!, $country: Country!) {
  node(id: $nodeId) {
    __typename
    ...ShowFields
  }
}
"""


class JustWatchError(RuntimeError):
    """Raised when JustWatch operations fail."""


class JustWatchManager:
    """Manages JustWatch availability checks with intelligent caching."""

    def __init__(self, storage: DatabaseStorage, locale: str = "it_IT"):
        """
        Initialize JustWatch manager.

        Args:
            storage: DatabaseStorage instance for caching
            locale: JustWatch locale (default: it_IT for Italy)
        """
        self.storage = storage
        self.locale = locale
        self.language = locale.split("_")[0].lower()
        self.country = locale.split("_")[1].upper()  # IT from it_IT
        self._last_request_time: Optional[float] = None
        self._min_request_interval = 1.0  # Minimum 1 second between requests
        self._show_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._show_details_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._jw_id: Optional[str] = None
        self._jw_id_registered = False

    @staticmethod
    def _episode_cache_key(show_name: str) -> str:
        return f"{show_name}{TV_EPISODE_CACHE_SUFFIX}"

    def _rate_limit(self) -> None:
        """Enforce rate limiting between API requests."""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _generate_jw_id(self, tag: str = "C") -> str:
        raw = os.urandom(16)
        token = base64.b64encode(raw).decode("ascii").replace("+", "-").replace("/", "_")
        jw_id = token[:22]
        return jw_id[:16] + tag + jw_id[17:]

    def _ensure_jw_id(self) -> None:
        if self._jw_id_registered:
            return
        if not self._jw_id:
            self._jw_id = self._generate_jw_id()
        mutation = f"mutation RegisterDeviceId {{ registerDeviceId(input: \"{self._jw_id}\") {{ deviceId }} }}"
        headers = {"Content-Type": "application/json", **JW_HEADERS}
        try:
            response = requests.post(
                JW_GRAPHQL_URL,
                json={"query": mutation},
                headers=headers,
                timeout=15,
                stream=True,
            )
            payload = read_bounded_json_response(response)
        except requests.exceptions.RequestException as exc:
            raise JustWatchError(f"Errore registrazione JustWatch: {exc}") from exc
        if payload.get("errors"):
            raise JustWatchError(f"Errore registrazione JustWatch: {payload['errors']}")
        self._jw_id_registered = True

    def _graphql_headers(self) -> Dict[str, str]:
        self._ensure_jw_id()
        sg = urllib.parse.urlencode({
            "c": self.country,
            "l": self.language,
            "d": self._jw_id or ""
        })
        return {"Content-Type": "application/json", "sg": sg, **JW_HEADERS}

    def _graphql_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._rate_limit()
        try:
            response = requests.post(
                JW_GRAPHQL_URL,
                json=payload,
                headers=self._graphql_headers(),
                timeout=20,
                stream=True,
            )
            data = read_bounded_json_response(response)
        except requests.exceptions.RequestException as exc:
            raise JustWatchError(f"Errore richiesta JustWatch: {exc}") from exc
        if data.get("errors"):
            raise JustWatchError(f"Errore risposta JustWatch: {data['errors']}")
        return data

    def _search_title(
        self,
        title: str,
        year: Optional[int],
        object_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Search for a show on JustWatch.

        Args:
            show_name: Name of the TV show
            year: Optional year to narrow down results

        Returns:
            Show data if found, None otherwise
        """
        cache_key = f"{title}::{year or ''}::{object_type}"
        if cache_key in self._show_cache:
            return self._show_cache[cache_key]
        try:
            payload = {
                "operationName": "GetSearchTitles",
                "variables": {
                    "first": 10,
                    "searchTitlesFilter": {"searchQuery": title},
                    "language": self.language,
                    "country": self.country,
                    "filter": {"bestOnly": True}
                },
                "query": JW_SEARCH_QUERY
            }
            results = self._graphql_post(payload)
        except JustWatchError as exc:
            logger.error("Errore ricerca JustWatch per %r:\n%s", sanitize_diagnostic_text(title), format_exception_for_log(exc))
            self._show_cache[cache_key] = None
            return None
        edges = (
            results.get("data", {})
            .get("popularTitles", {})
            .get("edges", [])
        )
        if not edges:
            logger.warning("Titolo '%s' non trovato su JustWatch", sanitize_diagnostic_text(title))
            self._show_cache[cache_key] = None
            return None

        candidates = [edge.get("node") for edge in edges if isinstance(edge, dict)]
        candidates = [node for node in candidates if isinstance(node, dict)]
        candidates = [node for node in candidates if node.get("objectType") == object_type]
        target_year = None
        if year is not None:
            try:
                target_year = int(year)
            except (TypeError, ValueError):
                target_year = None
        if target_year is not None:
            for node in candidates:
                release_year = node.get("content", {}).get("originalReleaseYear")
                if release_year == target_year:
                    self._show_cache[cache_key] = node
                    return node
        node = candidates[0] if candidates else None
        self._show_cache[cache_key] = node
        return node

    def _search_show(self, show_name: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        return self._search_title(show_name, year, "SHOW")

    def _search_movie(self, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        return self._search_title(title, year, "MOVIE")

    def _get_show_details(self, node_id: str) -> Optional[Dict[str, Any]]:
        if node_id in self._show_details_cache:
            return self._show_details_cache[node_id]
        try:
            payload = {
                "operationName": "GetNodeById",
                "variables": {"nodeId": node_id, "country": self.country},
                "query": JW_SHOW_QUERY
            }
            response = self._graphql_post(payload)
        except JustWatchError as exc:
            logger.error("Errore recupero show %s:\n%s", node_id, format_exception_for_log(exc))
            self._show_details_cache[node_id] = None
            return None
        node = response.get("data", {}).get("node")
        if not isinstance(node, dict) or node.get("__typename") != "Show":
            self._show_details_cache[node_id] = None
            return None
        self._show_details_cache[node_id] = node
        return node

    def _get_episode_offers(
        self,
        node_id: str,
        season_num: int,
        episode_num: int
    ) -> list:
        show_details = self._get_show_details(node_id)
        if not show_details:
            return []
        seasons = show_details.get("seasons", [])
        if not isinstance(seasons, list):
            return []
        for season in seasons:
            if not isinstance(season, dict):
                continue
            season_content = season.get("content") or {}
            if season_content.get("seasonNumber") != season_num:
                continue
            episodes = season.get("episodes") or []
            if not isinstance(episodes, list):
                continue
            for episode in episodes:
                if not isinstance(episode, dict):
                    continue
                content = episode.get("content") or {}
                if content.get("episodeNumber") == episode_num:
                    offers = episode.get("offers") or []
                    if isinstance(offers, list) and offers:
                        return offers
                    return []
        return []

    def _get_title_offers(self, node_id: str) -> list:
        try:
            payload = {
                "operationName": "GetTitleOffers",
                "variables": {"nodeId": node_id, "country": self.country},
                "query": JW_TITLE_QUERY
            }
            response = self._graphql_post(payload)
        except JustWatchError as exc:
            logger.error("Errore recupero offerte %s:\n%s", node_id, format_exception_for_log(exc))
            return []
        node = response.get("data", {}).get("node")
        if not isinstance(node, dict):
            return []
        offers = node.get("offers") or []
        return offers if isinstance(offers, list) else []

    def _extract_offer_providers(self, offers: list) -> list:
        if not offers:
            return []
        labels = []
        seen = set()
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            label = None
            package = offer.get("package")
            if isinstance(package, dict):
                label = package.get("clearName") or package.get("technicalName")
            if not label:
                label = offer.get("provider_name") or offer.get("package_short_name")
            if not label:
                continue
            label = str(label)
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
        return labels

    def check_availability_details(
        self,
        show_name: str,
        season_num: int,
        episode_num: int,
        year: Optional[int] = None
    ) -> tuple:
        cache_key = self._episode_cache_key(show_name)
        cached = self.storage.get_justwatch_cache(
            show_name=cache_key,
            season=season_num,
            episode=episode_num
        )

        if cached:
            is_available = cached["is_available"]
            providers = cached.get("providers") or []
            last_checked = cached["last_checked"]
            if isinstance(last_checked, datetime) and last_checked.tzinfo is None:
                last_checked = last_checked.replace(tzinfo=timezone.utc)
            force_refresh = not providers

            if is_available and not force_refresh:
                logger.debug(
                    f"Cache HIT (disponibile): {show_name} S{season_num}E{episode_num}"
                )
                return True, providers

            age = datetime.now(timezone.utc) - last_checked
            if age < timedelta(hours=24) and not force_refresh:
                logger.debug(
                    f"Cache HIT (non disponibile, recente): {show_name} S{season_num}E{episode_num}"
                )
                return False, providers

            logger.debug(
                f"Cache STALE (>24h): {show_name} S{season_num}E{episode_num}"
            )

        logger.info(
            f"Verifico disponibilita JustWatch: {show_name} S{season_num}E{episode_num}"
        )

        show_data = self._search_show(show_name, year)
        if not show_data:
            self.storage.save_justwatch_cache(
                show_name=cache_key,
                season=season_num,
                episode=episode_num,
                is_available=False,
                providers=[]
            )
            return False, []

        show_id = show_data.get("id")
        if not show_id:
            logger.error(f"ID show mancante per '{show_name}'")
            self.storage.save_justwatch_cache(
                show_name=cache_key,
                season=season_num,
                episode=episode_num,
                is_available=False,
                providers=[]
            )
            return False, []

        offers = self._get_episode_offers(show_id, season_num, episode_num)
        offers = [offer for offer in offers if isinstance(offer, dict)]
        valid_offers = []
        for offer in offers:
            monetization_type = offer.get("monetizationType") or offer.get("monetization_type")
            monetization_type = str(monetization_type).lower()
            if monetization_type in ["flatrate", "rent", "buy"]:
                valid_offers.append(offer)
        offers = valid_offers
        is_available = bool(offers)
        providers = self._extract_offer_providers(offers)

        self.storage.save_justwatch_cache(
            show_name=cache_key,
            season=season_num,
            episode=episode_num,
            is_available=is_available,
            providers=providers
        )

        logger.info(
            f"JustWatch: {show_name} S{season_num}E{episode_num} - "
            f"{'DISPONIBILE' if is_available else 'NON DISPONIBILE'}"
        )

        return is_available, providers

    def check_movie_availability_details(
        self,
        title: str,
        year: Optional[int] = None
    ) -> tuple:
        cache_key = f"{title}::movie"
        cached = self.storage.get_justwatch_cache(
            show_name=cache_key,
            season=0,
            episode=0
        )

        if cached:
            is_available = cached["is_available"]
            providers = cached.get("providers") or []
            last_checked = cached["last_checked"]
            if isinstance(last_checked, datetime) and last_checked.tzinfo is None:
                last_checked = last_checked.replace(tzinfo=timezone.utc)
            force_refresh = not providers

            if is_available and not force_refresh:
                logger.debug("Cache HIT (movie disponibile): %s", sanitize_diagnostic_text(title))
                return True, providers

            age = datetime.now(timezone.utc) - last_checked
            if age < timedelta(hours=24) and not force_refresh:
                logger.debug("Cache HIT (movie non disponibile, recente): %s", sanitize_diagnostic_text(title))
                return False, providers

        logger.info("Verifico disponibilita JustWatch: %s (movie)", sanitize_diagnostic_text(title))

        movie_data = self._search_movie(title, year)
        if not movie_data:
            self.storage.save_justwatch_cache(
                show_name=cache_key,
                season=0,
                episode=0,
                is_available=False,
                providers=[]
            )
            return False, []

        movie_id = movie_data.get("id")
        if not movie_id:
            self.storage.save_justwatch_cache(
                show_name=cache_key,
                season=0,
                episode=0,
                is_available=False,
                providers=[]
            )
            return False, []

        search_offers = movie_data.get("offers") if isinstance(movie_data, dict) else None
        search_offers = search_offers if isinstance(search_offers, list) else []
        offers = search_offers
        if not offers:
            offers = self._get_title_offers(movie_id)
        offers = [offer for offer in offers if isinstance(offer, dict)]
        valid_offers = []
        for offer in offers:
            monetization_type = offer.get("monetizationType") or offer.get("monetization_type")
            monetization_type = str(monetization_type).lower()
            if monetization_type in ["flatrate", "rent", "buy"]:
                valid_offers.append(offer)
        offers = valid_offers
        is_available = bool(offers)
        providers = self._extract_offer_providers(offers)

        self.storage.save_justwatch_cache(
            show_name=cache_key,
            season=0,
            episode=0,
            is_available=is_available,
            providers=providers
        )

        logger.info(
            f"JustWatch: {title} (movie) - "
            f"{'DISPONIBILE' if is_available else 'NON DISPONIBILE'}"
        )

        return is_available, providers

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
        is_available, _providers = self.check_availability_details(
            show_name,
            season_num,
            episode_num,
            year=year
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
        cleared = self.storage.clear_justwatch_cache(show_name=show_name)
        if show_name:
            cleared += self.storage.clear_justwatch_cache(
                show_name=self._episode_cache_key(show_name)
            )
        return cleared

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
]
