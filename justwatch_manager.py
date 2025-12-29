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

try:
    from justwatch import JustWatch
    JUSTWATCH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    JUSTWATCH_AVAILABLE = False

if TYPE_CHECKING:
    from storage import DatabaseStorage

logger = logging.getLogger(__name__)
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
        self.language = locale.split("_")[0].lower()
        self.country = locale.split("_")[1].upper()  # IT from it_IT
        self.jw = JustWatch(country=self.country)
        self._last_request_time: Optional[float] = None
        self._min_request_interval = 1.0  # Minimum 1 second between requests
        self._provider_map: Optional[Dict[int, str]] = None
        self._show_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._show_details_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._jw_id: Optional[str] = None
        self._jw_id_registered = False

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
                timeout=15
            )
            response.raise_for_status()
            payload = response.json()
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
                timeout=20
            )
            response.raise_for_status()
            data = response.json()
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
            logger.error(f"Errore ricerca JustWatch per '{title}': {exc}")
            self._show_cache[cache_key] = None
            return None
        edges = (
            results.get("data", {})
            .get("popularTitles", {})
            .get("edges", [])
        )
        if not edges:
            logger.warning(f"Titolo '{title}' non trovato su JustWatch")
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
            logger.error(f"Errore recupero show {node_id}: {exc}")
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
                    break
        offers = show_details.get("offers") or []
        return offers if isinstance(offers, list) else []

    def _get_title_offers(self, node_id: str) -> list:
        try:
            payload = {
                "operationName": "GetTitleOffers",
                "variables": {"nodeId": node_id, "country": self.country},
                "query": JW_TITLE_QUERY
            }
            response = self._graphql_post(payload)
        except JustWatchError as exc:
            logger.error(f"Errore recupero offerte {node_id}: {exc}")
            return []
        node = response.get("data", {}).get("node")
        if not isinstance(node, dict):
            return []
        offers = node.get("offers") or []
        return offers if isinstance(offers, list) else []

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
            show_details = self._get_title_details(show_id)

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

    def _get_title_details(self, show_id: int) -> Optional[Dict[str, Any]]:
        try:
            self._rate_limit()
            return self.jw.get_title(title_id=show_id, content_type="show")
        except requests.exceptions.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                logger.error(f"Errore dettagli show_id={show_id}: {exc}")
                return None
            try:
                path = f"titles/show/{show_id}/locale/{self.country}"
                api_url = self.jw.api_base_template.format(path=path)
                self._rate_limit()
                response = self.jw.requests.get(api_url, headers=JW_HEADERS)
                response.raise_for_status()
                return response.json()
            except Exception as fallback_exc:
                logger.error(f"Errore dettagli show_id={show_id}: {fallback_exc}")
                return None
        except Exception as exc:
            logger.error(f"Errore dettagli show_id={show_id}: {exc}")
            return None

    def _get_season_details(self, season_id: int) -> Optional[Dict[str, Any]]:
        try:
            self._rate_limit()
            return self.jw.get_season(season_id)
        except requests.exceptions.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                logger.error(f"Errore dati stagione season_id={season_id}: {exc}")
                return None
            try:
                api_url = (
                    "https://apis.justwatch.com/content/titles/show_season/"
                    f"{season_id}/locale/{self.country}"
                )
                self._rate_limit()
                response = self.jw.requests.get(api_url, headers=JW_HEADERS)
                response.raise_for_status()
                return response.json()
            except Exception as fallback_exc:
                logger.error(
                    f"Errore dati stagione season_id={season_id}: {fallback_exc}"
                )
                return None
        except Exception as exc:
            logger.error(f"Errore dati stagione season_id={season_id}: {exc}")
            return None

    def _get_provider_map(self) -> Dict[int, str]:
        if self._provider_map is not None:
            return self._provider_map
        try:
            self._rate_limit()
            providers = self.jw.get_providers()
        except requests.exceptions.HTTPError as exc:
            providers = None
            if exc.response is not None and exc.response.status_code == 404:
                try:
                    path = f"providers/locale/{self.country}"
                    api_url = self.jw.api_base_template.format(path=path)
                    self._rate_limit()
                    response = self.jw.requests.get(api_url, headers=JW_HEADERS)
                    response.raise_for_status()
                    providers = response.json()
                except Exception as fallback_exc:
                    logger.error(f"Errore recupero provider JustWatch: {fallback_exc}")
                    self._provider_map = {}
                    return self._provider_map
            else:
                logger.error(f"Errore recupero provider JustWatch: {exc}")
                self._provider_map = {}
                return self._provider_map
        except Exception as exc:
            logger.error(f"Errore recupero provider JustWatch: {exc}")
            self._provider_map = {}
            return self._provider_map
        mapping: Dict[int, str] = {}
        for provider in providers or []:
            if not isinstance(provider, dict):
                continue
            provider_id = provider.get("id") or provider.get("provider_id")
            try:
                provider_id = int(provider_id)
            except (TypeError, ValueError):
                continue
            label = (
                provider.get("clear_name")
                or provider.get("name")
                or provider.get("short_name")
            )
            if label:
                mapping[provider_id] = str(label)
        self._provider_map = mapping
        return mapping

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
            season_data = self._get_season_details(season_id)

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

    def _get_valid_offers(self, episode_data: Optional[Dict[str, Any]]) -> list:
        if not episode_data:
            return []
        offers = episode_data.get("offers", [])
        if not isinstance(offers, list):
            return []
        valid_offers = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            monetization_type = offer.get("monetizationType") or offer.get("monetization_type", "")
            monetization_type = str(monetization_type).lower()
            if monetization_type in ["flatrate", "rent", "buy"]:
                valid_offers.append(offer)
        return valid_offers

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

        offers = self._get_valid_offers(episode_data)
        if not offers:
            logger.debug("Nessuna offerta valida trovata per l'episodio")
            return False

        for offer in offers:
            provider_id = offer.get("provider_id", "unknown")
            logger.debug(
                f"Offerta trovata: {offer.get('monetization_type')} su provider {provider_id}"
            )
        return True

    def check_availability_details(
        self,
        show_name: str,
        season_num: int,
        episode_num: int,
        year: Optional[int] = None
    ) -> tuple:
        cached = self.storage.get_justwatch_cache(
            show_name=show_name,
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
                show_name=show_name,
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
                show_name=show_name,
                season=season_num,
                episode=episode_num,
                is_available=False,
                providers=[]
            )
            return False, []

        search_offers = show_data.get("offers") if isinstance(show_data, dict) else None
        search_offers = search_offers if isinstance(search_offers, list) else []
        offers = self._get_episode_offers(show_id, season_num, episode_num)
        offers = offers if offers else search_offers
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
            show_name=show_name,
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
                logger.debug(f"Cache HIT (movie disponibile): {title}")
                return True, providers

            age = datetime.now(timezone.utc) - last_checked
            if age < timedelta(hours=24) and not force_refresh:
                logger.debug(f"Cache HIT (movie non disponibile, recente): {title}")
                return False, providers

        logger.info(f"Verifico disponibilita JustWatch: {title} (movie)")

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
