"""Composition root for Emby playstate synchronization workflows."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.playstate_exact import PlaystateExactMixin
from emby_users.playstate_merge import PlaystateMergeMixin
from emby_users.playstate_state import PlaystateStateMixin
from emby_users.playstate_support import PlaystateSupportMixin
from emby_users.playstate_sync import PlaystateSyncMixin


class PlaystateManager(
    PlaystateSupportMixin,
    PlaystateSyncMixin,
    PlaystateExactMixin,
    PlaystateStateMixin,
    PlaystateMergeMixin,
):
    def __init__(
        self,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_user_items_for_sync: Callable[[Dict[str, Any], str, bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_all_media_for_user: Callable[[Dict[str, Any], str], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_provider_ids: Callable[[Dict[str, Any], str, List[str], bool], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_items_by_safe_fallback: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        mark_item_played: Callable[[Dict[str, Any], str, str, Optional[str]], Tuple[bool, Optional[str]]],
        mark_item_unplayed: Callable[[Dict[str, Any], str, str], Tuple[bool, Optional[str]]],
        set_item_resume: Callable[..., Tuple[bool, Optional[str]]],
        set_item_hide_from_resume: Optional[Callable[[Dict[str, Any], str, str, bool], Tuple[bool, Optional[str]]]] = None,
    ):
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_user_items_for_sync = fetch_user_items_for_sync
        self._fetch_all_media_for_user_api = fetch_all_media_for_user
        self._fetch_items_by_provider_ids = fetch_items_by_provider_ids
        self._fetch_items_by_safe_fallback = fetch_items_by_safe_fallback
        self._mark_item_played = mark_item_played
        self._mark_item_unplayed = mark_item_unplayed
        self._set_item_resume = set_item_resume
        self._set_item_hide_from_resume = set_item_hide_from_resume or (lambda *_args: (True, None))
