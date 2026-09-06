"""Shared snapshot refresh after a user-content operation."""

from __future__ import annotations

from typing import Iterable, List, Tuple

from emby_users.sync_results import require_complete_snapshots


UserTarget = Tuple[str, str]


def refresh_sync_states(
    state_tracker,
    targets: Iterable[UserTarget],
    origin: str,
    *,
    sync_config: bool = False,
    sync_library_access: bool = False,
    sync_playstate: bool = False,
    sync_favorites: bool = False,
    sync_playlists: bool = False,
) -> List[str]:
    """Refresh each affected domain once, preserving the caller's target set."""
    unique_targets = list(dict.fromkeys(targets))
    domains = []
    if sync_config or sync_library_access:
        domains.append("settings")
    if sync_playstate:
        domains.append("playstate")
    if sync_favorites:
        domains.append("favorites")
    if sync_playlists:
        domains.append("playlists")
    checkpoint_states = []
    for domain in domains:
        states = require_complete_snapshots(
            state_tracker.observe_many(domain, unique_targets, origin),
            len(unique_targets),
        )
        checkpoint_states.extend(states)
    state_tracker.commit_many(checkpoint_states)
    return domains
