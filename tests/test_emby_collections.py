"""Emby collections behavior and frontend contracts."""

from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from emby_collections.collection_emby import _clear_collection_items, _find_emby_item_ids
from emby_collections.collection_store import (
    list_collection_definitions,
    save_collection_definition,
    set_collection_enabled,
)
from emby_collections.source_inventory import (
    add_source_inventory_item,
    list_source_inventory,
    remove_source_inventory_item,
)
from emby_collections.collection_sync import run_collection_sync
from emby_collections.sources import build_source_link, fetch_source_items
from emby_collections.sources_mdblist import MdblistClient, _fetch_imdb_via_mdblist_items, _normalize_mdblist_entries
from emby_collections.sources_trakt import _parse_trakt_list_reference


class _CollectionStorage:
    def __init__(self, definitions=None):
        self.definitions = {item["id"]: dict(item) for item in (definitions or [])}
        self.saved = []
        self.deleted = []
        self.posters = {}
        self.backdrops = {}
        self.key_values = {}

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

    def get_key_value(self, key):
        return self.key_values.get(key)

    def set_key_value(self, key, value):
        self.key_values[key] = value


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

    def test_find_emby_item_ids_falls_back_to_tmdb_when_primary_provider_misses(self):
        calls = []

        def fake_call(_server, path, method="GET", params=None, **_kwargs):
            calls.append((path, method, params))
            if params["AnyProviderIdEquals"] == "Imdb.tt123":
                return True, {"Items": []}
            if params["AnyProviderIdEquals"] == "Tmdb.42":
                return True, {"Items": [{"Id": "movie-42"}]}
            return False, "unexpected provider"

        with patch("emby_collections.collection_emby._call_emby_api", side_effect=fake_call):
            result = _find_emby_item_ids(
                {"id": "server-a"},
                {
                    "provider_key": "imdb",
                    "provider_id": "tt123",
                    "provider_label": "Imdb",
                    "tmdb_id": "42",
                    "media_type": "movie",
                },
            )

        self.assertEqual(["movie-42"], result)
        self.assertEqual("Imdb.tt123", calls[0][2]["AnyProviderIdEquals"])
        self.assertEqual("Tmdb.42", calls[1][2]["AnyProviderIdEquals"])
        self.assertEqual("Movie", calls[1][2]["IncludeItemTypes"])


class CollectionSourceTests(unittest.TestCase):
    def test_mdblist_get_list_merges_movies_and_shows_from_same_response(self):
        class _FakeResponse:
            text = "{}"
            headers = {"X-Has-More": "false"}

            def json(self):
                return {
                    "movies": [{"tmdb_id": 1, "title": "Movie", "mediatype": "movie"}],
                    "shows": [{"tmdb_id": 2, "title": "Show", "mediatype": "show"}],
                }

        client = MdblistClient("key")
        with patch.object(client, "_request", return_value=_FakeResponse()):
            items = client.get_list("list-a")

        self.assertEqual(2, len(items))
        self.assertEqual(["Movie", "Show"], [item["title"] for item in items])

    def test_mdblist_entries_prefer_tmdb_identity_when_available(self):
        items = _normalize_mdblist_entries(
            [
                {
                    "imdb_id": "tt123",
                    "tmdb_id": 42,
                    "title": "Movie",
                    "mediatype": "movie",
                }
            ]
        )

        self.assertEqual("tmdb", items[0]["provider_key"])
        self.assertEqual("42", items[0]["provider_id"])
        self.assertEqual("Tmdb", items[0]["provider_label"])

    def test_imdb_via_mdblist_uses_matching_external_list(self):
        class _FakeClient:
            def __init__(self):
                self.calls = 0

            def get_my_lists(self):
                return [
                    {
                        "id": "external-42",
                        "name": "IMDb Top TV",
                        "external": {
                            "url": "https://www.imdb.com/it/chart/toptv/?sort=list_order%2Casc",
                        },
                    }
                ]

            def get_list(self, list_id, max_items=None):
                self.calls += 1
                self.list_id = list_id
                return [
                    {
                        "tmdb_id": 100 + self.calls,
                        "title": "Show",
                        "mediatype": "show",
                    }
                ]

        fake_client = _FakeClient()
        with patch("emby_collections.sources_mdblist._ensure_mdblist_client", return_value=fake_client):
            items = _fetch_imdb_via_mdblist_items("https://www.imdb.com/chart/toptv/")
            refreshed_items = _fetch_imdb_via_mdblist_items("https://www.imdb.com/chart/toptv/")

        self.assertEqual("external-42", fake_client.list_id)
        self.assertEqual(1, len(items))
        self.assertEqual("tmdb", items[0]["provider_key"])
        self.assertEqual("101", items[0]["provider_id"])
        self.assertEqual("102", refreshed_items[0]["provider_id"])
        self.assertEqual(2, fake_client.calls)

    def test_imdb_via_mdblist_explains_missing_external_list(self):
        class _FakeClient:
            def get_my_lists(self):
                return [{"id": "external-42", "name": "Other list"}]

        with patch("emby_collections.sources_mdblist._ensure_mdblist_client", return_value=_FakeClient()):
            with self.assertRaisesRegex(RuntimeError, "External List MDBList"):
                _fetch_imdb_via_mdblist_items("https://www.imdb.com/chart/toptv/")

    def test_source_registry_supports_imdb_via_mdblist(self):
        with patch(
            "emby_collections.sources_mdblist._ensure_mdblist_client",
        ) as ensure_client:
            ensure_client.return_value.get_my_lists.return_value = [
                {
                    "id": "external-42",
                    "name": "IMDb Top TV",
                    "source_url": "https://www.imdb.com/chart/toptv/",
                }
            ]
            ensure_client.return_value.get_list.return_value = [
                {"tmdb_id": 100, "title": "Show", "mediatype": "show"}
            ]

            items = fetch_source_items("imdb_mdblist", "https://www.imdb.com/chart/toptv/")

        self.assertEqual("100", items[0]["provider_id"])

    def test_trakt_source_link_handles_global_list_and_sort_query(self):
        self.assertEqual(
            "https://trakt.tv/lists/popular-list",
            build_source_link("trakt_list", "popular-list"),
        )
        self.assertEqual(
            "https://trakt.tv/users/roy/lists/my-list?sort=rank,desc",
            build_source_link("trakt_list", "roy/my-list?sort=rank,desc"),
        )

    def test_trakt_reference_normalizes_username_for_api_paths(self):
        reference = _parse_trakt_list_reference("RedPrimrose/festival-list?sort=rank,asc")

        self.assertIsNotNone(reference)
        self.assertEqual("redprimrose", reference["username"])
        self.assertEqual("/users/redprimrose/lists/festival-list/items", reference["path"])
        self.assertEqual("rank", reference["sort_by"])
        self.assertEqual("asc", reference["sort_how"])


class CollectionStoreTests(unittest.TestCase):
    def test_source_inventory_adds_deduplicates_and_removes_saved_links(self):
        backend = _CollectionStorage()

        with patch("emby_collections.source_inventory._ensure_db_backend", return_value=backend):
            first = add_source_inventory_item(
                {
                    "name": "Top TV",
                    "source_type": "imdb_mdblist",
                    "source_value": "https://www.imdb.com/it/chart/toptv/?sort=list_order%2Casc",
                },
                origin="manual",
            )
            updated = add_source_inventory_item(
                {
                    "name": "Top TV aggiornata",
                    "source_type": "imdb_mdblist",
                    "source_value": "https://www.imdb.com/chart/toptv/",
                },
                origin="manual",
            )
            items = list_source_inventory()
            remove_source_inventory_item(first["id"])
            empty = list_source_inventory()

        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(1, len(items))
        self.assertEqual("Top TV aggiornata", items[0]["name"])
        self.assertEqual([], empty)

    def test_save_collection_definition_auto_adds_source_to_inventory(self):
        backend = _CollectionStorage()

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ), patch(
            "emby_collections.source_inventory._ensure_db_backend",
            return_value=backend,
        ):
            save_collection_definition(
                {
                    "name": "Top TV",
                    "source_type": "imdb_mdblist",
                    "source_value": "https://www.imdb.com/chart/toptv/",
                    "server_ids": ["server-a"],
                }
            )
            items = list_source_inventory()

        self.assertEqual(1, len(items))
        self.assertEqual("Top TV", items[0]["name"])
        self.assertEqual("imdb_mdblist", items[0]["source_type"])
        self.assertEqual("auto", items[0]["origin"])

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

    def test_save_collection_definition_requires_at_least_one_server(self):
        backend = _CollectionStorage()

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ):
            with self.assertRaisesRegex(ValueError, "server Emby"):
                save_collection_definition(
                    {
                        "name": "Collection",
                        "source_type": "tmdb_list",
                        "source_value": "123",
                        "server_ids": [],
                    }
                )

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
    def test_run_collection_sync_reports_empty_source_before_matching_emby(self):
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

        with patch("emby_collections.collection_sync._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_sync._server_map",
            return_value=_servers(),
        ), patch(
            "emby_collections.collection_sync._collect_source_items",
            return_value=[],
        ), patch("emby_collections.collection_store._ensure_db_backend", return_value=backend):
            result = run_collection_sync("collection-1")

        saved = backend.definitions["collection-1"]
        self.assertEqual("warning", saved["last_sync_status"])
        self.assertEqual("La fonte non ha restituito contenuti", saved["last_sync_message"])
        self.assertEqual("warning", result["collection"]["last_sync_status"])

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

    def test_trakt_parser_preserves_supported_query_parameters(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        start = source.index("const parseTraktListToken =")
        end = source.index("const detectTraktListValue =", start)
        block = source[start:end]

        self.assertNotIn("split('?', 1)", block)
        self.assertIn("querySuffix", block)
        self.assertIn("return `${directMatch[1]}/${directMatch[2]}${querySuffix}`", block)
        self.assertIn("return `${userMatch[1]}/${userMatch[2]}${querySuffix}`", block)

    def test_save_form_requires_server_selection_before_api_call(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        start = source.index("const handleSave = async")
        end = source.index("const handleToggle = async", start)
        block = source[start:end]

        self.assertIn("if (!payload.server_ids.length)", block)
        self.assertIn("Seleziona almeno un server Emby.", block)

    def test_mdblist_rows_escape_link_and_source_attributes(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        start = source.index("const buildMdblistRow =")
        end = source.index("const renderMdblistLists =", start)
        block = source[start:end]

        self.assertIn("const link = escapeHtml(entry.link || '')", block)
        self.assertIn("const sourceValue = escapeHtml(entry.source_value || '')", block)

    def test_service_list_errors_are_shown_in_panel_status(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        mdblist_start = source.index("const fetchMdblistLists =")
        mdblist_end = source.index("const parseTraktListToken =", mdblist_start)
        mdblist_block = source[mdblist_start:mdblist_end]
        trakt_start = source.index("const fetchTraktLists =")
        trakt_end = source.index("const fetchCollections =", trakt_start)
        trakt_block = source[trakt_start:trakt_end]

        self.assertIn("updateMdblistStatus(error.message || 'Errore caricamento liste MDBList.')", mdblist_block)
        self.assertIn("updateTraktStatus(error.message || 'Errore caricamento liste Trakt.')", trakt_block)

    def test_imdb_links_prefer_mdblist_source_when_available(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")
        start = source.index("const handleSourceValueUpdate =")
        end = source.index("const getSourceLabel =", start)
        block = source[start:end]

        self.assertIn("const parsedImdb = parseImdbSourceValue(sourceValueInput.value)", block)
        self.assertIn("hasSourceType('imdb_mdblist')", block)
        self.assertIn("sourceTypeSelect.value = 'imdb_mdblist'", block)

    def test_source_inventory_panel_is_below_personal_service_lists(self):
        template = pathlib.Path("templates/emby_collections.html").read_text(encoding="utf-8")
        mdblist_index = template.index('id="mdblist-lists-card"')
        inventory_index = template.index('id="source-inventory-card"')

        self.assertGreater(inventory_index, mdblist_index)
        self.assertIn('id="source-inventory-name"', template)
        self.assertIn('id="source-inventory-body"', template)

    def test_source_inventory_frontend_uses_inventory_api(self):
        source = pathlib.Path("static/emby_collections.js").read_text(encoding="utf-8")

        self.assertIn("const sourceInventoryApiUrl = '/api/emby/collections/source-inventory'", source)
        self.assertIn("const fetchSourceInventory = async", source)
        self.assertIn("const handleSourceInventoryAdd = async", source)
        self.assertIn("const handleSourceInventoryActions = async", source)
        self.assertIn("await fetchSourceInventory()", source)


if __name__ == "__main__":
    unittest.main()
