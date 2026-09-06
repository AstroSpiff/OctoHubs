"""Tests for the shared post-operation snapshot refresh helper."""

from __future__ import annotations

import unittest

from emby_users.sync_state_refresh import refresh_sync_states


class _Tracker:
    def __init__(self):
        self.calls = []
        self.committed = []

    def observe_many(self, domain, targets, origin):
        self.calls.append((domain, targets, origin))
        return [
            {"domain": domain, "server_id": server_id, "user_id": user_id}
            for server_id, user_id in targets
        ]

    def commit_many(self, states):
        self.committed = list(states)


class SyncStateRefreshTests(unittest.TestCase):
    def test_refreshes_each_affected_domain_once_with_unique_targets(self):
        tracker = _Tracker()

        domains = refresh_sync_states(
            tracker,
            [("a", "1"), ("a", "1"), ("b", "2")],
            "clone",
            sync_config=True,
            sync_library_access=True,
            sync_playstate=True,
            sync_favorites=True,
            sync_playlists=True,
        )

        self.assertEqual(domains, ["settings", "playstate", "favorites", "playlists"])
        self.assertEqual([call[0] for call in tracker.calls], domains)
        self.assertTrue(all(call[1] == [("a", "1"), ("b", "2")] for call in tracker.calls))
        self.assertTrue(all(call[2] == "clone" for call in tracker.calls))
        self.assertEqual(len(tracker.committed), len(domains) * 2)

    def test_does_not_commit_when_any_snapshot_fails(self):
        tracker = _Tracker()

        def observe_many(domain, targets, origin):
            tracker.calls.append((domain, targets, origin))
            return [
                {"domain": domain, "server_id": "a", "user_id": "1"},
                {"domain": domain, "server_id": "b", "user_id": "2", "error": "offline"},
            ]

        tracker.observe_many = observe_many
        with self.assertRaises(Exception):
            refresh_sync_states(
                tracker,
                [("a", "1"), ("b", "2")],
                "auto-sync",
                sync_favorites=True,
            )
        self.assertEqual(tracker.committed, [])


if __name__ == "__main__":
    unittest.main()
