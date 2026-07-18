"""Emby collections behavior and frontend contracts."""

from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from emby_collections.collection_emby import _clear_collection_items
from emby_collections.collection_store import (
    list_collection_definitions,
    save_collection_definition,
    set_collection_enabled,
)
from emby_collections.collection_sync import run_collection_sync


class _CollectionStorage:
    def __init__(self, definitions=None):
        self.definitions = {item["id"]: dict(item) for item in (definitions or [])}
        self.saved = []
        self.deleted = []
        self.posters = {}
        self.backdrops = {}

    def list_emby_collection_definitions(self):
        return [dict(item) for item in self.definitions.values()]

    def get_emby_collection_definition(self, definition_id):
        item = self.definitions.get(definition_id)
        return dict(item) if item else None

    def save_emby_collection_definition(self, definition):
        self.definitions[definition["id"]] = dict(definition)
        self.saved.append(dict(definition))

    def delete_emby_collection_definition(self, definition_id):
        self.deleted.append(definition_id)
        self.definitions.pop(definition_id, None)

    def list_emby_collection_poster_ids(self):
        return set(self.posters)

    def list_emby_collection_backdrop_ids(self):
        return set(self.backdrops)

    def get_emby_collection_poster(self, definition_id):
        return self.posters.get(definition_id)

    def save_emby_collection_poster(self, definition_id, mime_type, data):
        self.posters[definition_id] = {"mime_type": mime_type, "data": data}

    def delete_emby_collection_poster(self, definition_id):
        self.posters.pop(definition_id, None)

    def get_emby_collection_backdrop(self, definition_id):
        return self.backdrops.get(definition_id)

    def save_emby_collection_backdrop(self, definition_id, mime_type, data):
        self.backdrops[definition_id] = {"mime_type": mime_type, "data": data}

    def delete_emby_collection_backdrop(self, definition_id):
        self.backdrops.pop(definition_id, None)


def _servers():
    return {
        "server-a": {"id": "server-a", "name": "Alpha"},
        "server-b": {"id": "server-b", "alias": "Beta"},
    }


class CollectionEmbyTests(unittest.TestCase):
    def test_clear_collection_items_raises_when_emby_delete_fails(self):
        calls = []

        def fake_call(_server, path, method="GET", params=None, **_kwargs):
            calls.append((path, method, params))
            if method == "GET":
                return True, {"Items": [{"Id": "item-1"}, {"Id": "item-2"}]}
            if method == "DELETE":
                return False, "delete failed"
            return False, "unexpected"

        with patch("emby_collections.collection_emby._call_emby_api", side_effect=fake_call):
            with self.assertRaisesRegex(RuntimeError, "delete failed"):
                _clear_collection_items({"id": "server-a"}, "collection-1")

        self.assertEqual(
            [
                ("Collections/collection-1/Items", "GET", {"Fields": "Id"}),
                ("Collections/collection-1/Items", "DELETE", {"Ids": "item-1,item-2"}),
            ],
            calls,
        )


class CollectionStoreTests(unittest.TestCase):
    def test_save_and_list_collection_definition_normalizes_servers_and_assets(self):
        backend = _CollectionStorage(
            [
                {
                    "id": "collection-1",
                    "name": "Old name",
                    "sort_name": "Old name",
                    "source": {"type": "tmdb_list", "value": "10"},
                    "server_ids": ["server-a"],
                    "last_sync_status": "success",
                    "last_sync_per_server": [{"server_id": "server-a", "items": [{"title": "hidden"}]}],
                }
            ]
        )
        backend.posters["collection-1"] = {"mime_type": "image/png", "data": b"poster"}
        backend.backdrops["collection-1"] = {"mime_type": "image/jpeg", "data": b"backdrop"}

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ):
            saved = save_collection_definition(
                {
                    "id": "collection-1",
                    "name": "Collection",
                    "source_type": "tmdb_list",
                    "source_value": "123",
                    "server_ids": ["server-b", "server-b", "missing"],
                    "auto_frequency": "150",
                }
            )
            listed = list_collection_definitions()

        self.assertEqual(["server-b"], saved["server_ids"])
        self.assertEqual("Beta", saved["server_display"])
        self.assertEqual(100, saved["auto_frequency"])
        self.assertEqual("success", backend.saved[-1]["last_sync_status"])
        self.assertEqual(1, len(listed))
        self.assertTrue(listed[0]["poster_uploaded"])
        self.assertTrue(listed[0]["background_uploaded"])
        self.assertNotIn("items", listed[0]["last_sync_per_server"][0])

    def test_disabling_collection_deletes_emby_matches_and_persists_disabled_state(self):
        backend = _CollectionStorage(
            [
                {
                    "id": "collection-1",
                    "name": "Collection",
                    "sort_name": "Collection",
                    "source": {"type": "tmdb_list", "value": "123"},
                    "server_ids": ["server-a"],
                    "enabled": True,
                }
            ]
        )
        deleted = []

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ), patch(
            "emby_collections.collection_store._find_collection_ids_for_definition",
            return_value=(["box-1"], True),
        ), patch(
            "emby_collections.collection_store._delete_emby_collection",
            side_effect=lambda _server, collection_id: deleted.append(collection_id) or True,
        ):
            result = set_collection_enabled("collection-1", False)

        self.assertFalse(result["enabled"])
        self.assertFalse(backend.definitions["collection-1"]["enabled"])
        self.assertEqual(["box-1"], deleted)


class CollectionSyncTests(unittest.TestCase):
    def test_run_collection_sync_saves_per_server_summary(self):
        backend = _CollectionStorage(
            [
                {
                    "id": "collection-1",
                    "name": "Collection",
                    "sort_name": "Collection",
                    "source": {"type": "tmdb_list", "value": "123"},
                    "server_ids": ["server-a", "server-b"],
                    "enabled": True,
                }
            ]
        )
        source_items = [
            {"provider_key": "tmdb", "provider_id": "1", "title": "One"},
            {"provider_key": "tmdb", "provider_id": "2", "title": "Two"},
        ]

        def fake_sync(server, *_args, **_kwargs):
            if server["id"] == "server-a":
                return {
                    "status": "success",
                    "message": "2 elementi sincronizzati",
                    "matched": 2,
                    "candidates": 2,
                    "missing": 0,
                    "items": [],
                    "server_label": "Alpha",
                }
            return {
                "status": "partial",
                "message": "1 elementi sincronizzati (1 mancanti)",
                "matched": 1,
                "candidates": 2,
                "missing": 1,
                "items": [],
                "server_label": "Beta",
            }

        with patch("emby_collections.collection_sync._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_sync._server_map",
            return_value=_servers(),
        ), patch(
            "emby_collections.collection_sync._collect_source_items",
            return_value=source_items,
        ), patch(
            "emby_collections.collection_sync._sync_collection_to_server",
            side_effect=fake_sync,
        ), patch("emby_collections.collection_store._ensure_db_backend", return_value=backend):
            result = run_collection_sync("collection-1")

        saved = backend.definitions["collection-1"]
        self.assertEqual("partial", saved["last_sync_status"])
        self.assertEqual("Alpha 2/2 · Beta 1/2", saved["last_sync_message"])
        self.assertEqual(1, saved["last_sync_items"])
        self.assertEqual(2, saved["last_sync_candidates"])
        self.assertEqual(2, len(saved["last_sync_per_server"]))
        self.assertEqual("partial", result["collection"]["last_sync_status"])


class CollectionFrontendTests(unittest.TestCase):
    def test_toggle_checks_api_error_before_refreshing_collection_list(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        start = source.index("const handleToggle = async")
        end = source.index("const handleSync = async", start)
        block = source[start:end]

        self.assertIn("const response = await baseCsrfFetch", block)
        self.assertIn("const data = await response.json()", block)
        self.assertIn("if (!response.ok || data.success === false)", block)
        self.assertIn("throw new Error(data.error || 'Errore aggiornamento stato.')", block)

    def test_background_preview_uses_backdrop_aspect_ratio(self):
        template = pathlib.Path("templates/emby_collections.html").read_text(encoding="utf-8")
        start = template.index(".collection-media-preview--background")
        end = template.index(".collection-media-preview img", start)
        block = template[start:end]

        self.assertIn("aspect-ratio: 16 / 9;", block)


if __name__ == "__main__":
    unittest.main()
