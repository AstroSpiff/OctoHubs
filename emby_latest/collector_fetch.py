"""Concurrent Emby Latest fetch coordination."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from emby_latest.scan_cursor import incremental_stop_at_from_state


class LatestFetchCoordinator:
    def __init__(
        self,
        *,
        fast_mode: bool,
        per_server_limit: int,
        batch_fetch_limit: int,
        batch_fields: str,
        latest_state: Dict[str, Any],
        skip_existing_complete: bool,
        state_enabled: bool,
        requests_per_server: int,
        fetch_latest_items,
    ):
        self._fast_mode = fast_mode
        self._per_server_limit = per_server_limit
        self._batch_fetch_limit = batch_fetch_limit
        self._batch_fields = batch_fields
        self._latest_state = latest_state
        self._skip_existing_complete = skip_existing_complete
        self._state_enabled = state_enabled
        self._requests_per_server = requests_per_server
        self._fetch_latest_items = fetch_latest_items

    def server_batch_limit(self) -> int:
        if self._fast_mode:
            value = max(self._per_server_limit * 4, 120)
        else:
            value = max(self._per_server_limit * 8, 200)
        return min(value, self._batch_fetch_limit)

    def _fetch_latest_with_fallback(
        self,
        server: Dict[str, Any],
        item_type: str,
        batch_limit: int,
        stop_at: Optional[Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        kwargs = {"fields": self._batch_fields}
        if stop_at:
            kwargs["stop_at"] = stop_at
        items, error = self._fetch_latest_items(server, item_type, batch_limit, **kwargs)
        if not error:
            return items, None

        fallback_kwargs = {"stop_at": stop_at} if stop_at else {}
        fallback_items, fallback_error = self._fetch_latest_items(
            server,
            item_type,
            batch_limit,
            **fallback_kwargs,
        )
        if not fallback_error:
            return fallback_items, None
        return [], error

    def prepare_server(self, server: Dict[str, Any]) -> Dict[str, Any]:
        server_id = server.get("id")
        batch_limit = self.server_batch_limit()
        movie_stop_at = (
            incremental_stop_at_from_state(self._latest_state, server_id, "Movie")
            if self._skip_existing_complete and self._state_enabled else None
        )
        episode_stop_at = (
            incremental_stop_at_from_state(self._latest_state, server_id, "Episode")
            if self._skip_existing_complete and self._state_enabled else None
        )
        fetches = {
            "movie": ("Movie", movie_stop_at),
            "episode": ("Episode", episode_stop_at),
        }
        results: Dict[str, Tuple[List[Dict[str, Any]], Optional[Any]]] = {}
        worker_count = min(max(1, self._requests_per_server), len(fetches))
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="latest-emby") as executor:
                future_map = {
                    executor.submit(
                        self._fetch_latest_with_fallback,
                        server,
                        item_type,
                        batch_limit,
                        stop_at,
                    ): key
                    for key, (item_type, stop_at) in fetches.items()
                }
                for future in as_completed(future_map):
                    results[future_map[future]] = future.result()
        else:
            for key, (item_type, stop_at) in fetches.items():
                results[key] = self._fetch_latest_with_fallback(server, item_type, batch_limit, stop_at)

        movie_items, movie_error = results.get("movie", ([], None))
        episode_items, episode_error = results.get("episode", ([], None))
        return {
            "server_id": server_id,
            "batch_limit": batch_limit,
            "movie_stop_at": movie_stop_at,
            "episode_stop_at": episode_stop_at,
            "movie_items": movie_items,
            "movie_error": movie_error,
            "episode_items": episode_items,
            "episode_error": episode_error,
        }
