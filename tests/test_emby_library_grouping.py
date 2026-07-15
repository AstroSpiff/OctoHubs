"""Library grouping behavior."""

from __future__ import annotations

import unittest

from emby_libraries.grouping import group_libraries


class EmbyLibraryGroupingTests(unittest.TestCase):
    def test_manual_assignment_to_existing_automatic_group_merges_into_that_group(self):
        servers_data = {
            "server-a": {
                "name": "Server A",
                "libraries": [
                    {"id": "movies-a", "name": "Movies", "collection_type": "movies"},
                ],
            },
            "server-b": {
                "name": "Server B",
                "libraries": [
                    {"id": "movies-b", "name": "Cinema", "collection_type": "movies"},
                ],
            },
        }

        groups = group_libraries(
            servers_data,
            manual_associations={("server-b", "movies-b"): "Movies"},
        )

        movie_groups = [group for group in groups if group["collection_type"] == "movies"]
        self.assertEqual(len(movie_groups), 1)
        self.assertEqual(movie_groups[0]["group_name"], "Movies")
        self.assertEqual(
            sorted(library["library_id"] for library in movie_groups[0]["libraries"]),
            ["movies-a", "movies-b"],
        )

    def test_manual_assignment_to_new_group_remains_separate(self):
        servers_data = {
            "server-a": {
                "name": "Server A",
                "libraries": [
                    {"id": "movies-a", "name": "Movies", "collection_type": "movies"},
                ],
            },
            "server-b": {
                "name": "Server B",
                "libraries": [
                    {"id": "movies-b", "name": "Cinema", "collection_type": "movies"},
                ],
            },
        }

        groups = group_libraries(
            servers_data,
            manual_associations={("server-b", "movies-b"): "Archivio"},
        )

        names = sorted(group["group_name"] for group in groups if group["collection_type"] == "movies")
        self.assertEqual(names, ["Archivio", "Movies"])


if __name__ == "__main__":
    unittest.main()
