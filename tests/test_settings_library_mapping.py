from __future__ import annotations

import unittest

from emby_users.settings_library_mapping import remap_library_config_for_server


class SettingsLibraryMappingTests(unittest.TestCase):
    def test_config_library_fields_remap_aliases_to_target_preference_id(self):
        libraries_by_server = {
            "source": {
                "libraries": [
                    {
                        "id": "source-folder",
                        "folder_id": "source-folder",
                        "guid": "source-guid",
                        "view_ids": ["source-folder", "source-access-view"],
                    }
                ]
            },
            "target": {
                "libraries": [
                    {
                        "id": "target-folder",
                        "folder_id": "target-folder",
                        "guid": "target-guid",
                        "view_ids": ["target-folder", "target-access-view"],
                    }
                ]
            },
        }
        membership = {
            "source": {
                "source-folder": "movies::film",
                "source-guid": "movies::film",
                "source-access-view": "movies::film",
            },
            "target": {
                "target-folder": "movies::film",
                "target-guid": "movies::film",
                "target-access-view": "movies::film",
            },
        }

        remapped = remap_library_config_for_server(
            {
                "OrderedViews": ["source-access-view"],
                "LatestItemsExcludes": ["source-guid"],
                "MyMediaExcludes": ["source-folder"],
            },
            "target",
            "source",
            libraries_by_server,
            membership,
        )

        self.assertEqual(remapped["OrderedViews"], ["target-folder"])
        self.assertEqual(remapped["LatestItemsExcludes"], ["target-folder"])
        self.assertEqual(remapped["MyMediaExcludes"], ["target-folder"])


if __name__ == "__main__":
    unittest.main()
