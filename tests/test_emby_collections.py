"""Emby collections behavior and frontend contracts."""

from __future__ import annotations

import json
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from emby_collections.collection_common import (
    _build_collection_tags,
    _extract_octohubs_definition_id,
)
from emby_collections.collection_emby import _clear_collection_items, _find_emby_item_ids
from emby_collections.collection_store import (
    list_collection_definitions,
    save_collection_definition,
    set_collection_enabled,
)
from emby_collections.source_inventory import (
    add_source_inventory_item,
    detect_inventory_source_type,
    list_source_inventory,
    remove_source_inventory_item,
)
from emby_collections.collection_sync import run_collection_sync
from emby_collections.routes import (
    api_emby_collections_get_backdrop,
    api_emby_collections_get_poster,
    api_emby_collections_save,
    api_emby_collections_mdblist_lists,
    api_emby_collections_sync,
    api_emby_collections_sync_all,
    api_emby_collections_trakt_lists,
)
from emby_collections.sources import SOURCE_TYPES, build_source_link, fetch_source_items
from emby_collections.sources_mdblist import (
    MdblistClient,
    _normalize_mdblist_entries,
    list_mdblist_user_lists,
)
from emby_collections.sources_tmdb import _extract_tmdb_identifier, _fetch_tmdb_list_items
from emby_collections.sources_trakt import _parse_trakt_list_reference


def _test_image_bytes(image_format):
    mode = "RGB"
    image = Image.new(mode, (2, 2), (40, 90, 140))
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


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
        "server-a": {"id": "server-a", "name": "Alpha", "icon": "fa-server", "icon_color": "#19a36f"},
        "server-b": {"id": "server-b", "alias": "Beta", "icon": "fa-film", "icon_color": "#8B5CF6", "icon_style": "regular"},
    }


class CollectionEmbyTests(unittest.TestCase):
    def test_collection_tags_use_octohubs_and_drop_legacy_octohub_tags(self):
        tags = _build_collection_tags(
            {"id": "definition-a"},
            ["Featured", "OctoHub", "OctoHub:old-definition"],
        )

        self.assertEqual(tags, ["Featured", "OctoHubs", "OctoHubs:definition-a"])

    def test_extract_collection_id_accepts_legacy_octohub_tag(self):
        self.assertEqual(
            _extract_octohubs_definition_id(["OctoHub:definition-a"]),
            "definition-a",
        )

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
    def test_tmdb_list_identifier_accepts_slugged_grid_url(self):
        identifier = _extract_tmdb_identifier(
            "https://www.themoviedb.org/list/49435-movies-trending?view=grid",
            "list",
        )

        self.assertEqual("49435", identifier)

    def test_tmdb_list_fetches_all_pages(self):
        payloads = [
            {
                "page": 1,
                "total_pages": 2,
                "items": [
                    {
                        "id": 10,
                        "title": "First page movie",
                        "media_type": "movie",
                    }
                ],
            },
            {
                "page": 2,
                "total_pages": 2,
                "items": [
                    {
                        "id": 20,
                        "name": "Second page show",
                        "media_type": "tv",
                    }
                ],
            },
        ]

        with patch("emby_collections.sources_tmdb._fetch_tmdb_payload", side_effect=payloads) as fetcher:
            items = _fetch_tmdb_list_items("123")

        self.assertEqual(["10", "20"], [item["provider_id"] for item in items])
        self.assertEqual(["First page movie", "Second page show"], [item["title"] for item in items])
        self.assertEqual([1, 2], [call.kwargs["page"] for call in fetcher.call_args_list])
        self.assertEqual(2, fetcher.call_count)

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

    def test_mdblist_direct_source_can_fetch_external_list_by_prefix(self):
        class _FakeClient:
            def __init__(self):
                self.list_id = ""

            def get_external_list(self, list_id, max_items=None):
                self.list_id = str(list_id)
                return [
                    {
                        "tmdb_id": 550,
                        "title": "Movie",
                        "mediatype": "movie",
                    }
                ]

        fake_client = _FakeClient()
        with patch("emby_collections.sources_mdblist._ensure_mdblist_client", return_value=fake_client):
            items = fetch_source_items("mdblist", "external:2868")

        self.assertEqual("2868", fake_client.list_id)
        self.assertEqual("550", items[0]["provider_id"])

    def test_mdblist_user_lists_include_external_lists(self):
        class _FakeClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def get_my_lists(self):
                return [
                    {
                        "id": "list-1",
                        "name": "Regular list",
                        "slug": "regular-list",
                        "user_name": "roy",
                        "items": 3,
                    }
                ]

            def get_user_external_lists(self):
                return [
                    {
                        "id": 2868,
                        "name": "IMDb Top TV",
                        "source_url": "https://www.imdb.com/chart/toptv/",
                        "user_name": "roy",
                        "items": 250,
                    }
                ]

        with patch("emby_collections.sources_mdblist.load_config", return_value=({}, None)), patch(
            "emby_collections.sources_mdblist._collect_mdblist_api_keys",
            return_value=["key"],
        ), patch(
            "emby_collections.sources_mdblist.MdblistClient",
            _FakeClient,
        ):
            lists = list_mdblist_user_lists()

        self.assertEqual("list-1", lists[0]["source_value"])
        self.assertEqual("mdblist", lists[0]["source_type"])
        self.assertEqual("external:2868", lists[1]["source_value"])
        self.assertEqual("mdblist", lists[1]["source_type"])
        self.assertTrue(lists[1]["external"])

    def test_source_registry_excludes_imdb_sources(self):
        source_values = {entry["value"] for entry in SOURCE_TYPES}

        self.assertNotIn("imdb_list", source_values)
        self.assertNotIn("imdb_mdblist", source_values)
        with self.assertRaisesRegex(RuntimeError, "non supportata"):
            fetch_source_items("imdb_list", "")
        with self.assertRaisesRegex(RuntimeError, "non supportata"):
            fetch_source_items("imdb_mdblist", "")

    def test_trakt_source_link_handles_global_list_and_sort_query(self):
        self.assertEqual(
            "https://trakt.tv/lists/popular-list",
            build_source_link("trakt_list", "popular-list"),
        )
        self.assertEqual(
            "https://trakt.tv/users/roy/lists/my-list?sort=rank,desc",
            build_source_link("trakt_list", "roy/my-list?sort=rank,desc"),
        )
        self.assertEqual(
            "https://trakt.tv/users/redprimrose/lists/festival-list",
            build_source_link("trakt_list", "RedPrimrose/festival-list"),
        )

    def test_trakt_reference_normalizes_username_for_api_paths(self):
        reference = _parse_trakt_list_reference("RedPrimrose/festival-list?sort=rank,asc")

        self.assertIsNotNone(reference)
        self.assertEqual("redprimrose", reference["username"])
        self.assertEqual("/users/redprimrose/lists/festival-list/items", reference["path"])
        self.assertEqual("rank", reference["sort_by"])
        self.assertEqual("asc", reference["sort_how"])


class CollectionStoreTests(unittest.TestCase):
    def test_source_inventory_rejects_imdb_links(self):
        backend = _CollectionStorage()

        with patch("emby_collections.source_inventory._ensure_db_backend", return_value=backend):
            detected = detect_inventory_source_type("https://www.imdb.com/chart/toptv/")
            with self.assertRaisesRegex(ValueError, "Tipo di fonte non valido"):
                add_source_inventory_item(
                    {
                        "name": "Top TV",
                        "source_value": "https://www.imdb.com/chart/toptv/",
                    },
                    origin="manual",
                )

        self.assertIsNone(detected)
        self.assertEqual([], backend.key_values.get("collections.source_inventory", []))

    def test_source_inventory_hides_existing_imdb_entries(self):
        backend = _CollectionStorage()
        backend.key_values["collections.source_inventory"] = [
            {
                "id": "source-1",
                "name": "Old IMDb",
                "source_type": "imdb_mdblist",
                "source_value": "https://www.imdb.com/chart/toptv/",
            },
            {
                "id": "source-2",
                "name": "TMDB",
                "source_type": "tmdb_list",
                "source_value": "123",
            },
        ]

        with patch("emby_collections.source_inventory._ensure_db_backend", return_value=backend):
            items = list_source_inventory()

        self.assertEqual(["source-2"], [item["id"] for item in items])

    def test_source_inventory_adds_deduplicates_and_removes_saved_links(self):
        backend = _CollectionStorage()

        with patch("emby_collections.source_inventory._ensure_db_backend", return_value=backend):
            first = add_source_inventory_item(
                {
                    "name": "Festival",
                    "source_type": "trakt_list",
                    "source_value": "https://trakt.tv/users/RedPrimrose/lists/festival-list?sort=rank,asc",
                },
                origin="manual",
            )
            updated = add_source_inventory_item(
                {
                    "name": "Festival aggiornata",
                    "source_type": "trakt_list",
                    "source_value": "redprimrose/festival-list?sort=rank,asc",
                },
                origin="manual",
            )
            items = list_source_inventory()
            remove_source_inventory_item(first["id"])
            empty = list_source_inventory()

        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(1, len(items))
        self.assertEqual("Festival aggiornata", items[0]["name"])
        self.assertEqual([], empty)

    def test_source_inventory_list_normalizes_existing_trakt_links(self):
        backend = _CollectionStorage()
        backend.key_values["collections.source_inventory"] = [
            {
                "id": "source-1",
                "name": "Festival",
                "source_type": "trakt_list",
                "source_value": "RedPrimrose/festival-list",
                "source_link": "https://trakt.tv/users/RedPrimrose/lists/festival-list",
            }
        ]

        with patch("emby_collections.source_inventory._ensure_db_backend", return_value=backend):
            items = list_source_inventory()

        self.assertEqual("https://trakt.tv/users/redprimrose/lists/festival-list", items[0]["source_link"])

    def test_save_collection_definition_rejects_imdb_sources(self):
        backend = _CollectionStorage()

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ):
            with self.assertRaisesRegex(ValueError, "Tipo di fonte non valido"):
                save_collection_definition(
                    {
                        "name": "Top TV",
                        "source_type": "imdb_list",
                        "source_value": "ls123456789",
                        "server_ids": ["server-a"],
                    }
                )

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
                    "name": "TMDB List",
                    "source_type": "tmdb_list",
                    "source_value": "123",
                    "server_ids": ["server-a"],
                }
            )
            items = list_source_inventory()

        self.assertEqual(1, len(items))
        self.assertEqual("TMDB List", items[0]["name"])
        self.assertEqual("tmdb_list", items[0]["source_type"])
        self.assertEqual("auto", items[0]["origin"])

    def test_save_collection_definition_skips_personal_service_sources_in_inventory(self):
        backend = _CollectionStorage()

        with patch("emby_collections.collection_store._ensure_db_backend", return_value=backend), patch(
            "emby_collections.collection_store._server_map",
            return_value=_servers(),
        ), patch(
            "emby_collections.source_inventory._ensure_db_backend",
            return_value=backend,
        ):
            saved = save_collection_definition(
                {
                    "name": "Festival",
                    "source_type": "trakt_list",
                    "source_value": "RedPrimrose/festival-list",
                    "source_origin": "personal",
                    "server_ids": ["server-a"],
                }
            )
            items = list_source_inventory()

        self.assertEqual("personal", saved["source_origin"])
        self.assertEqual([], items)

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
        self.assertEqual(
            [{"id": "server-b", "name": "Beta", "icon": "fa-film", "icon_color": "#8B5CF6", "icon_style": "regular"}],
            saved["servers"],
        )
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


class CollectionRoutesTests(unittest.IsolatedAsyncioTestCase):
    class _Request:
        def __init__(self, params):
            self.query_params = params

    class _JsonRequest:
        query_params = {}

        def __init__(self, payload):
            self.payload = payload

        async def json(self):
            return self.payload

    async def test_saving_a_collection_publishes_a_scoped_realtime_update(self):
        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

        with patch(
            "emby_collections.routes._logger_dep",
            return_value=_Logger(),
        ), patch(
            "emby_collections.routes.save_collection_definition",
            return_value={"id": "collection-1", "name": "Film"},
        ), patch("emby_collections.routes.publish_application_event") as publish:
            response = await api_emby_collections_save(
                self._JsonRequest(
                    {
                        "name": "Film",
                        "source_type": "trakt",
                        "source_value": "popular",
                        "server_ids": ["server-1"],
                    }
                ),
                user={"username": "tester"},
            )

        self.assertEqual({"success": True, "collection": {"id": "collection-1", "name": "Film"}}, response)
        publish.assert_called_once_with(
            "OctoHubsCollectionsUpdated",
            {"scope": "definitions", "collection_id": "collection-1"},
        )

    async def test_collection_poster_requires_authenticated_route_context(self):
        poster = _test_image_bytes("PNG")
        with patch(
            "emby_collections.routes.get_collection_poster_blob",
            return_value={"mime_type": "image/png", "data": poster},
        ) as getter:
            response = await api_emby_collections_get_poster(
                "collection-1",
                user={"username": "tester"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("image/png", response.headers["content-type"])
        with Image.open(BytesIO(response.body)) as decoded:
            self.assertEqual((2, 2), decoded.size)
        getter.assert_called_once_with("collection-1")

    async def test_collection_backdrop_requires_authenticated_route_context(self):
        backdrop = _test_image_bytes("JPEG")
        with patch(
            "emby_collections.routes.get_collection_backdrop_blob",
            return_value={"mime_type": "image/jpeg", "data": backdrop},
        ) as getter:
            response = await api_emby_collections_get_backdrop(
                "collection-1",
                user={"username": "tester"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("image/jpeg", response.headers["content-type"])
        with Image.open(BytesIO(response.body)) as decoded:
            self.assertEqual((2, 2), decoded.size)
        getter.assert_called_once_with("collection-1")

    async def test_trakt_lists_can_start_background_operation(self):
        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

        with patch(
            "emby_collections.routes._logger_dep",
            return_value=_Logger(),
        ), patch(
            "emby_collections.routes.start_source_list_operation",
            return_value={"id": "operation-1", "title": "Aggiornamento Liste Trakt"},
        ) as starter, patch("emby_collections.routes.list_trakt_lists") as sync_fetch:
            response = await api_emby_collections_trakt_lists(
                self._Request({"background": "1"}),
                user={"username": "tester"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(202, response.status_code)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["background"])
        self.assertEqual("operation-1", payload["operation_id"])
        starter.assert_called_once()
        sync_fetch.assert_not_called()

    async def test_mdblist_lists_can_start_background_operation(self):
        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

        with patch(
            "emby_collections.routes._logger_dep",
            return_value=_Logger(),
        ), patch(
            "emby_collections.routes.start_source_list_operation",
            return_value={"id": "operation-2", "title": "Aggiornamento Liste MDBList"},
        ) as starter, patch("emby_collections.routes.list_mdblist_user_lists") as sync_fetch:
            response = await api_emby_collections_mdblist_lists(
                self._Request({"background": "1"}),
                user={"username": "tester"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(202, response.status_code)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["background"])
        self.assertEqual("operation-2", payload["operation_id"])
        starter.assert_called_once()
        sync_fetch.assert_not_called()

    async def test_collection_sync_can_start_background_operation(self):
        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

        with patch(
            "emby_collections.routes._logger_dep",
            return_value=_Logger(),
        ), patch(
            "emby_collections.routes.start_collection_sync_operation",
            return_value={"id": "operation-3", "title": "Sincronizzazione collezione"},
        ) as starter, patch("emby_collections.routes.run_collection_sync") as sync_now, patch(
            "emby_collections.routes.publish_application_event",
        ) as publish:
            response = await api_emby_collections_sync(
                "collection-1",
                self._Request({"background": "1"}),
                user={"username": "tester"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(202, response.status_code)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["background"])
        self.assertEqual("operation-3", payload["operation_id"])
        starter.assert_called_once()
        sync_now.assert_not_called()
        publish.assert_called_once_with(
            "OctoHubsCollectionsUpdated",
            {"scope": "sync", "collection_id": "collection-1"},
        )

    async def test_collection_sync_all_can_start_background_operation(self):
        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

        with patch(
            "emby_collections.routes._logger_dep",
            return_value=_Logger(),
        ), patch(
            "emby_collections.routes.start_collection_sync_all_operation",
            return_value={"id": "operation-4", "title": "Sincronizzazione collezioni"},
        ) as starter, patch("emby_collections.routes.sync_all_collections") as sync_now:
            response = await api_emby_collections_sync_all(
                self._Request({"background": "1"}),
                user={"username": "tester"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(202, response.status_code)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["background"])
        self.assertEqual("operation-4", payload["operation_id"])
        starter.assert_called_once()
        sync_now.assert_not_called()


if __name__ == "__main__":
    unittest.main()
