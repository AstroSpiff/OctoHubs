"""Helpers for Trakt/JustWatch integrations tied to app config."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from core import config_manager
from core.config import _merge_trakt_settings
from core.config_manager import _db_enabled, _ensure_db_backend
from core.justwatch_manager import JustWatchManager, JustWatchError, is_justwatch_available
from search.parsing import _try_parse_int


_JUSTWATCH_MANAGER: Optional[JustWatchManager] = None
_JUSTWATCH_SIGNATURE: Optional[str] = None


class TraktAPIError(RuntimeError):
    """Raised when Trakt API calls fail."""


class TraktClient:
    BASE_URL = "https://api.trakt.tv"
    REFRESH_MARGIN_SECONDS = 24 * 60 * 60
    OAUTH_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        client_secret: str = "",
        refresh_token: str = "",
        expires_at: str = "",
        on_token_update=None,
    ):
        self.client_id = (client_id or "").strip()
        self.access_token = (access_token or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.refresh_token = (refresh_token or "").strip()
        self.expires_at = self._parse_expires_at(expires_at)
        self._on_token_update = on_token_update
        self._collection_cache = None
        self._collection_timestamp = 0.0
        self._season_cache: Dict[tuple, Any] = {}
        self._show_id_cache: Dict[int, Any] = {}
        self._lock = threading.Lock()
        self._token_lock = threading.Lock()

    @staticmethod
    def _parse_expires_at(value: Any) -> float:
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            return 0.0
        if text.isdigit():
            return float(text)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def _headers(self):
        return {
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OctoHub/1.0 (+https://github.com/roy/octohub)",
        }

    def _token_refresh_payload(self):
        return {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.OAUTH_REDIRECT_URI,
            "grant_type": "refresh_token",
        }

    def _refresh_access_token(self) -> bool:
        if not self.client_id or not self.client_secret or not self.refresh_token:
            return False
        with self._token_lock:
            response = requests.post(
                f"{self.BASE_URL}/oauth/token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json=self._token_refresh_payload(),
                timeout=15,
            )
            if response.status_code != 200:
                detail = ""
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        detail = payload.get("error_description") or payload.get("error") or ""
                except Exception:
                    detail = response.text
                detail = (detail or response.text or "").strip()
                raise TraktAPIError(
                    f"Refresh token Trakt non riuscito ({response.status_code})"
                    + (f": {detail}" if detail else ".")
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise TraktAPIError("Risposta refresh Trakt non valida.") from exc
            access_token = (payload.get("access_token") or "").strip()
            refresh_token = (payload.get("refresh_token") or self.refresh_token or "").strip()
            if not access_token or not refresh_token:
                raise TraktAPIError("Risposta refresh Trakt incompleta.")
            expires_in = payload.get("expires_in") or 604800
            try:
                expires_seconds = int(expires_in)
            except (TypeError, ValueError):
                expires_seconds = 604800
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.expires_at = expires_at.timestamp()
            update = {
                "ACCESS_TOKEN": access_token,
                "REFRESH_TOKEN": refresh_token,
                "EXPIRES_AT": expires_at.isoformat(),
            }
            if self._on_token_update is not None:
                self._on_token_update(update)
            return True

    def _ensure_valid_token(self) -> None:
        if not self.refresh_token:
            return
        if not self.expires_at:
            return
        refresh_at = self.expires_at - self.REFRESH_MARGIN_SECONDS
        if time.time() >= refresh_at:
            self._refresh_access_token()

    def _request(self, method: str, path: str, **kwargs):
        self._ensure_valid_token()
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        timeout = kwargs.pop("timeout", 15)
        try:
            response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            raise TraktAPIError(f"Errore di rete Trakt: {exc}") from exc
        if response.status_code == 401:
            if self._refresh_access_token():
                headers = kwargs.pop("headers", {})
                headers.update(self._headers())
                try:
                    response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
                except requests.RequestException as exc:
                    raise TraktAPIError(f"Errore di rete Trakt: {exc}") from exc
                if response.status_code != 401:
                    return self._decode_response(response)
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = (
                        payload.get("error_description")
                        or payload.get("description")
                        or payload.get("error")
                    )
            except Exception:
                detail = response.text
            detail = (detail or response.text or "").strip()
            if detail:
                raise TraktAPIError(f"Credenziali Trakt non valide (401): {detail}")
            raise TraktAPIError("Credenziali Trakt non valide (401).")
        if response.status_code == 403:
            raise TraktAPIError("Accesso Trakt negato (403).")
        if response.status_code >= 500:
            raise TraktAPIError("Trakt non disponibile (errore 5xx).")
        if response.status_code >= 400:
            raise TraktAPIError(f"Errore Trakt {response.status_code}.")
        return self._decode_response(response)

    def _decode_response(self, response):
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise TraktAPIError("Risposta Trakt non valida.") from exc

    def ping(self) -> bool:
        self._request("GET", "/sync/last_activities")
        return True

    def get_collection_map(self, max_age: int = 900) -> Dict[int, Dict[int, set]]:
        now = time.time()
        with self._lock:
            if self._collection_cache and (now - self._collection_timestamp) < max_age:
                return self._collection_cache
        try:
            payload = self._request(
                "GET",
                "/sync/collection/shows?extended=episodes",
                timeout=30,
            ) or []
        except TraktAPIError:
            with self._lock:
                self._collection_cache = {}
                self._collection_timestamp = now
            raise
        mapping: Dict[int, Dict[int, set]] = {}
        for entry in payload:
            show = entry.get("show") or {}
            ids = show.get("ids") or {}
            tmdb_id = ids.get("tmdb")
            tmdb_id = _try_parse_int(tmdb_id)
            if not tmdb_id:
                continue
            show_map = mapping.setdefault(tmdb_id, {})
            for season in entry.get("seasons") or []:
                season_number = _try_parse_int(season.get("number"))
                if season_number is None:
                    continue
                eps_set = show_map.setdefault(season_number, set())
                for episode in season.get("episodes") or []:
                    ep_number = _try_parse_int(episode.get("number"))
                    if ep_number is not None:
                        eps_set.add(ep_number)
        with self._lock:
            self._collection_cache = mapping
            self._collection_timestamp = now
        return mapping

    def get_season(self, tmdb_id: int, season_number: int):
        if tmdb_id is None or season_number is None:
            return None
        cache_key = (tmdb_id, season_number)
        with self._lock:
            if cache_key in self._season_cache:
                return self._season_cache[cache_key]
        show_identifier = self._resolve_show_identifier(tmdb_id)
        if not show_identifier:
            return None
        path = f"/shows/{show_identifier}/seasons/{season_number}?extended=episodes"
        payload = self._request("GET", path) or []
        with self._lock:
            self._season_cache[cache_key] = payload
        return payload

    def _resolve_show_identifier(self, tmdb_id: int):
        if tmdb_id in self._show_id_cache:
            return self._show_id_cache[tmdb_id]
        try:
            search_results = self._request(
                "GET",
                f"/search/tmdb/{tmdb_id}?type=show",
                timeout=10,
            )
        except TraktAPIError:
            search_results = None
        identifier = None
        if isinstance(search_results, list):
            for entry in search_results:
                show = entry.get("show") if isinstance(entry, dict) else None
                ids = show.get("ids") if isinstance(show, dict) else None
                if ids:
                    identifier = ids.get("slug") or ids.get("trakt") or ids.get("tmdb")
                    if identifier:
                        break
        if not identifier:
            identifier = tmdb_id
        with self._lock:
            self._show_id_cache[tmdb_id] = identifier
        return identifier


def _log_justwatch_status() -> None:
    settings = _active_justwatch_settings()
    if not _justwatch_enabled(settings):
        return
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    if not is_justwatch_available():
        print("   -> JustWatch: libreria non installata (pip install JustWatch)")
        return
    try:
        manager = _get_justwatch_manager(settings)
    except Exception as exc:
        print(f"   -> JustWatch: errore inizializzazione: {exc}")
        return
    if manager:
        print(f"   -> JustWatch: attivo (locale {locale})")
    else:
        print("   -> JustWatch: non disponibile (verifica database/config)")


def _trakt_enabled(settings: Dict[str, Any] | None) -> bool:
    if not settings:
        return False
    if not settings.get("ENABLED"):
        return False
    # Require credentials for authenticated Trakt calls (e.g. /users/me/lists).
    client_id = (settings.get("CLIENT_ID") or "").strip()
    access_token = (settings.get("ACCESS_TOKEN") or "").strip()
    return bool(client_id and access_token)


def _justwatch_enabled(settings: Dict[str, Any] | None) -> bool:
    if not settings:
        return False
    return bool(settings.get("ENABLED"))


def _persist_trakt_token_update(token_update: Dict[str, Any]) -> None:
    if not token_update:
        return
    backend = _ensure_db_backend()
    app_settings = backend.load_app_settings() or {}
    if not isinstance(app_settings, dict):
        app_settings = {}

    active_trakt = (
        config_manager._ACTIVE_CONFIG.get("TRAKT", {})
        if isinstance(config_manager._ACTIVE_CONFIG, dict)
        else {}
    )
    stored_trakt = app_settings.get("TRAKT", {})
    if not isinstance(active_trakt, dict):
        active_trakt = {}
    if not isinstance(stored_trakt, dict):
        stored_trakt = {}

    trakt_settings = dict(active_trakt)
    trakt_settings.update(stored_trakt)
    trakt_settings.update(token_update)
    trakt_settings["ENABLED"] = True
    merged_trakt = _merge_trakt_settings(trakt_settings)

    app_settings["TRAKT"] = merged_trakt
    backend.save_app_settings(app_settings)
    if isinstance(config_manager._ACTIVE_CONFIG, dict):
        config_manager._ACTIVE_CONFIG["TRAKT"] = merged_trakt


def _get_trakt_client(settings: Dict[str, Any] | None) -> Optional[TraktClient]:
    if not settings:
        return None
    return TraktClient(
        client_id=settings.get("CLIENT_ID", ""),
        access_token=settings.get("ACCESS_TOKEN", ""),
        client_secret=settings.get("CLIENT_SECRET", ""),
        refresh_token=settings.get("REFRESH_TOKEN", ""),
        expires_at=settings.get("EXPIRES_AT", ""),
        on_token_update=_persist_trakt_token_update,
    )


def _get_justwatch_manager(settings: Dict[str, Any] | None) -> Optional[JustWatchManager]:
    global _JUSTWATCH_MANAGER, _JUSTWATCH_SIGNATURE
    if not settings:
        return None
    if not _justwatch_enabled(settings):
        return None
    if not is_justwatch_available():
        return None
    db_settings = (
        config_manager._ACTIVE_CONFIG.get("DATABASE")
        if config_manager._ACTIVE_CONFIG
        else None
    )
    if not _db_enabled(db_settings):
        return None
    locale = (settings.get("LOCALE") or "it_IT").strip() or "it_IT"
    signature = f"{locale}"
    if _JUSTWATCH_MANAGER is None or _JUSTWATCH_SIGNATURE != signature:
        try:
            _JUSTWATCH_MANAGER = JustWatchManager(_ensure_db_backend(), locale=locale)
            _JUSTWATCH_SIGNATURE = signature
        except JustWatchError:
            return None
    return _JUSTWATCH_MANAGER


def _active_trakt_settings() -> Dict[str, Any]:
    if config_manager._ACTIVE_CONFIG is None:
        return {}
    return config_manager._ACTIVE_CONFIG.get("TRAKT", {})


def _active_justwatch_settings() -> Dict[str, Any]:
    if config_manager._ACTIVE_CONFIG is None:
        return {}
    return config_manager._ACTIVE_CONFIG.get("JUSTWATCH", {})
