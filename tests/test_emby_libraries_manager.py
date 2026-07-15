"""Emby library manager snapshots."""

from __future__ import annotations

import unittest

from emby_libraries.manager import EmbyLibrariesManager


class _Backend:
    def __init__(self):
        self.associations = {}

    def load_library_associations(self):
        return dict(self.associations)

    def save_library_associations(self, associations):
        self.associations = dict(associations)


class EmbyLibrariesManagerTests(unittest.TestCase):
    def test_associations_post_normalizes_valid_entries_and_ignores_incomplete_rows(self):
        backend = _Backend()
        manager = EmbyLibrariesManager(
            load_config=lambda: ({}, True),
            ensure_db_backend=lambda: backend,
            json_error=lambda message, status_code=400: ({"success": False, "message": message}, status_code),
            storage_error_cls=Exception,
        )

        payload, status_code = manager.build_associations_post_snapshot([
            {"server_id": "server-a", "library_id": "lib-a", "group_name": "Movies"},
            {"server_id": "server-b", "library_id": "", "group_name": "Movies"},
            {"server_id": "server-c", "library_id": "lib-c", "group_name": "Nascondi"},
            "invalid",
        ])

        self.assertEqual(status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(
            backend.associations,
            {
                ("server-a", "lib-a"): "Movies",
                ("server-c", "lib-c"): "Nascondi",
            },
        )
        self.assertEqual(len(payload["associations"]), 2)


if __name__ == "__main__":
    unittest.main()
