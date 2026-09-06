"""Helpers for Trakt/JustWatch integrations tied to app config."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from core import config_manager
from core.config import _merge_trakt_settings
from core.config_manager import _db_enabled, _ensure_db_backend
from core.justwatch_manager import JustWatchManager, JustWatchError, is_justwatch_available
from core.safe_output import safe_print as print
from core.log_sanitization import format_exception_for_log
from core.outbound_redirects import response_is_redirect
from search.parsing import _try_parse_int


_JUSTWATCH_MANAGER: Optional[JustWatchManager] = None
_JUSTWATCH_SIGNATURE: Optional[str] = None
_TRAKT_CLIENT: Optional["TraktClient"] = None
_TRAKT_SIGNATURE: Optional[str] = None
_TRAKT_CLIENT_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class TraktAPIError(RuntimeError):
    """Raised when Trakt API calls fail."""


class TraktClient:
    BASE_URL = "https://api.trakt.tv"
    REFRESH_MARGIN_SECONDS = 24 * 60 * 60
    SHORT_TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60
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
            "User-Agent": "OctoHubs/1.0 (+https://github.com/AstroSpiff/OctoHubs)",
        }

    def _token_refresh_payload(self):
        return {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.OAUTH_REDIRECT_URI,
            "grant_type": "refresh_token",
        }

    def _request_token_refresh(self) -> Dict[str, Any]:
        try:
            response = requests.post(
                f"{self.BASE_URL}/oauth/token",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json=self._token_refresh_payload(),
                allow_redirects=False,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise TraktAPIError("Errore di rete durante il refresh Trakt.") from exc
        if response_is_redirect(response):
            raise TraktAPIError("Redirect Trakt rifiutato.")
        if response.status_code != 200:
            raise TraktAPIError(
                f"Refresh token Trakt non riuscito ({response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TraktAPIError("Risposta refresh Trakt non valida.") from exc
        if not isinstance(payload, dict):
            raise TraktAPIError("Risposta refresh Trakt non valida.")
        return payload

    def _token_values_from_refresh(
        self, payload: Dict[str, Any]
    ) -> tuple[str, str, datetime]:
        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or self.refresh_token or "").strip()
        if not access_token or not refresh_token:
            raise TraktAPIError("Risposta refresh Trakt incompleta.")
        try:
            expires_seconds = int(payload.get("expires_in") or 604800)
        except (TypeError, ValueError):
            expires_seconds = 604800
        return (
            access_token,
            refresh_token,
            datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    def _token_needs_refresh(self) -> bool:
        if not self.refresh_token or not self.expires_at:
            return False
        remaining = self.expires_at - time.time()
        margin = (
            self.REFRESH_MARGIN_SECONDS
            if remaining > self.REFRESH_MARGIN_SECONDS
            else self.SHORT_TOKEN_REFRESH_MARGIN_SECONDS
        )
        return remaining <= margin

    def _refresh_access_token(
        self,
        *,
        force: bool = False,
        expected_access_token: Optional[str] = None,
    ) -> bool:
        if not self.client_id or not self.client_secret or not self.refresh_token:
            return False
        with self._token_lock:
            # A different caller may already have refreshed while this caller
            # waited for the single-flight lock.
            if expected_access_token is not None and self.access_token != expected_access_token:
                return True
            if not force and not self._token_needs_refresh():
                return True
            payload = self._request_token_refresh()
            access_token, refresh_token, expires_at = self._token_values_from_refresh(payload)
            update = {
                "ACCESS_TOKEN": access_token,
                "REFRESH_TOKEN": refresh_token,
                "EXPIRES_AT": expires_at.isoformat(),
            }
            if self._on_token_update is not None:
                accepted = self._on_token_update(update)
                if accepted is False:
                    raise TraktAPIError(
                        "Configurazione Trakt cambiata durante il refresh; token non salvati."
                    )
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.expires_at = expires_at.timestamp()
            return True

    def _ensure_valid_token(self) -> None:
        if self._token_needs_refresh():
            self._refresh_access_token()

    def _request(self, method: str, path: str, **kwargs):
        self._ensure_valid_token()
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        request_access_token = self.access_token
        timeout = kwargs.pop("timeout", 15)
        kwargs.pop("allow_redirects", None)
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                allow_redirects=False,
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise TraktAPIError("Errore di rete Trakt.") from exc
        if response_is_redirect(response):
            raise TraktAPIError("Redirect Trakt rifiutato.")
        if response.status_code == 401:
            if self._refresh_access_token(
                force=True,
                expected_access_token=request_access_token,
            ):
                headers = kwargs.pop("headers", {})
                headers.update(self._headers())
                try:
                    response = requests.request(
                        method,
                        url,
                        headers=headers,
                        allow_redirects=False,
                        timeout=timeout,
                        **kwargs,
                    )
                except requests.RequestException as exc:
                    raise TraktAPIError("Errore di rete Trakt.") from exc
                if response_is_redirect(response):
                    raise TraktAPIError("Redirect Trakt rifiutato.")
                if response.status_code != 401:
                    return self._decode_response(response)
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
        logger.error(
            "Inizializzazione JustWatch non riuscita:\n%s",
            format_exception_for_log(exc),
        )
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


def _trakt_settings_revision(settings: Dict[str, Any] | None) -> str:
    normalized = _merge_trakt_settings(dict(settings or {}))
    relevant = {
        key: normalized.get(key)
        for key in (
            "ENABLED",
            "CLIENT_ID",
            "CLIENT_SECRET",
            "ACCESS_TOKEN",
            "REFRESH_TOKEN",
            "EXPIRES_AT",
        )
    }
    serialized = json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@config_manager.serialized_config_update
def _persist_trakt_token_update(
    token_update: Dict[str, Any],
    *,
    expected_revision: str,
) -> bool:
    if not token_update:
        return False
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
    if _trakt_settings_revision(trakt_settings) != expected_revision:
        logger.warning(
            "[TRAKT] Token refresh discarded because configuration changed concurrently"
        )
        return False
    trakt_settings.update(token_update)
    trakt_settings["ENABLED"] = True
    merged_trakt = _merge_trakt_settings(trakt_settings)

    app_settings["TRAKT"] = merged_trakt
    backend.save_app_settings(app_settings)
    config_manager.publish_active_config_updates({"TRAKT": merged_trakt})
    return True


def _get_trakt_client(settings: Dict[str, Any] | None) -> Optional[TraktClient]:
    global _TRAKT_CLIENT, _TRAKT_SIGNATURE
    if not settings:
        return None
    signature = _trakt_settings_revision(settings)
    with _TRAKT_CLIENT_LOCK:
        if _TRAKT_CLIENT is not None and _TRAKT_SIGNATURE == signature:
            return _TRAKT_CLIENT

        revision = [signature]
        persisted_settings = [dict(settings)]

        def persist_if_current(token_update: Dict[str, Any]) -> bool:
            accepted = _persist_trakt_token_update(
                token_update,
                expected_revision=revision[0],
            )
            if accepted:
                updated = dict(persisted_settings[0])
                updated.update(token_update)
                updated["ENABLED"] = True
                persisted_settings[0] = updated
                revision[0] = _trakt_settings_revision(updated)
            return accepted

        _TRAKT_CLIENT = TraktClient(
            client_id=settings.get("CLIENT_ID", ""),
            access_token=settings.get("ACCESS_TOKEN", ""),
            client_secret=settings.get("CLIENT_SECRET", ""),
            refresh_token=settings.get("REFRESH_TOKEN", ""),
            expires_at=settings.get("EXPIRES_AT", ""),
            on_token_update=persist_if_current,
        )
        _TRAKT_SIGNATURE = signature
        return _TRAKT_CLIENT


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
