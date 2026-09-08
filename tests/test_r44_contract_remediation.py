"""R44 regressors for composed storage identities and bounded contracts."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import ValidationError
import pytest

from core.storage.field_limits import (
    COLLECTION_DEFINITION_ID_MAX_LENGTH,
    EMBY_GROUP_ID_MAX_LENGTH,
    EMBY_STORED_IDENTIFIER_MAX_LENGTH,
    KEY_VALUE_KEY_MAX_LENGTH,
    LIBRARY_COLLECTION_TYPE_MAX_LENGTH,
    SETTINGS_PRESET_ID_MAX_LENGTH,
)


class _NoSessionStorage:
    def _get_session(self):
        pytest.fail("a database session was opened before input validation")


@pytest.mark.parametrize(
    "operation",
    ["set", "update", "compare-and-set", "get", "prefix", "delete"],
)
def test_key_value_operations_reject_an_oversized_key_before_session(operation: str):
    from core.storage.storage_collections import StorageCollectionsMixin

    storage = type("Storage", (StorageCollectionsMixin, _NoSessionStorage), {})()
    invalid_key = "k" * (KEY_VALUE_KEY_MAX_LENGTH + 1)

    with pytest.raises(ValueError, match=str(KEY_VALUE_KEY_MAX_LENGTH)):
        if operation == "set":
            storage.set_key_value(invalid_key, {})
        elif operation == "update":
            storage.update_key_value(invalid_key, lambda _current: {})
        elif operation == "compare-and-set":
            storage.compare_and_set_key_values(
                {
                    "valid": (None, {}),
                    invalid_key: (None, {}),
                }
            )
        elif operation == "get":
            storage.get_key_value(invalid_key)
        elif operation == "prefix":
            storage.get_keys_by_prefix(invalid_key)
        else:
            storage.delete_key(invalid_key)


def test_every_emby_user_key_builder_fits_the_canonical_kv_contract():
    from emby_users.settings_storage import SettingsStorageMixin
    from emby_users.state_tracker import UserSyncStateTracker

    settings = SettingsStorageMixin()
    opaque = "x" * EMBY_STORED_IDENTIFIER_MAX_LENGTH
    group = "g" * EMBY_GROUP_ID_MAX_LENGTH
    keys = {
        settings.settings_group_key(group),
        settings.settings_user_key(opaque, opaque),
    }
    tracker = object.__new__(UserSyncStateTracker)
    keys.update(
        tracker.key(domain, opaque, opaque)
        for domain in ("settings", "playstate", "favorites", "playlists")
    )

    assert max(map(len, keys)) <= KEY_VALUE_KEY_MAX_LENGTH


def test_preset_key_boundary_matches_the_public_request_contract():
    from emby_users.api_models import SettingsPresetRequest
    from emby_users.settings_presets import SettingsPresetManager

    preset_id = "p" * SETTINGS_PRESET_ID_MAX_LENGTH
    assert SettingsPresetRequest(id=preset_id).id == preset_id
    manager = object.__new__(SettingsPresetManager)
    assert len(manager._key(preset_id)) <= KEY_VALUE_KEY_MAX_LENGTH

    with pytest.raises(ValidationError):
        SettingsPresetRequest(id=preset_id + "p")
    with pytest.raises(ValueError, match="preset_id"):
        manager._key(preset_id + "p")


def test_user_settings_reject_an_unpersistable_key_before_remote_effects():
    from emby_users.settings_manager import SettingsManager

    effects: list[str] = []
    manager = SettingsManager(
        storage=object(),
        config={},
        get_server_by_id=lambda _server_id: effects.append("server") or {},
        get_group_users=lambda _group_id: [],
        fetch_user_details=lambda _server, _user_id: (
            effects.append("fetch") or ({}, None)
        ),
        update_user_policy=lambda *_args: effects.append("policy") or (True, None),
        update_user_config=lambda *_args: effects.append("config") or (True, None),
    )

    oversized_component = "x" * KEY_VALUE_KEY_MAX_LENGTH
    with pytest.raises(ValueError, match=str(KEY_VALUE_KEY_MAX_LENGTH)):
        manager.update_user_settings(
            oversized_component,
            oversized_component,
            {},
        )

    assert effects == []


def test_bulk_user_settings_preflights_every_key_before_remote_effects():
    from emby_users.settings_manager import SettingsManager

    effects: list[str] = []
    manager = SettingsManager(
        storage=object(),
        config={},
        get_server_by_id=lambda _server_id: effects.append("server") or {},
        get_group_users=lambda _group_id: [],
        fetch_user_details=lambda _server, _user_id: (
            effects.append("fetch") or ({}, None)
        ),
        update_user_policy=lambda *_args: effects.append("policy") or (True, None),
        update_user_config=lambda *_args: effects.append("config") or (True, None),
    )
    oversized_component = "x" * KEY_VALUE_KEY_MAX_LENGTH

    with pytest.raises(ValueError, match=str(KEY_VALUE_KEY_MAX_LENGTH)):
        manager.apply_settings_to_users(
            [
                {"server_id": "server", "user_id": "user"},
                {
                    "server_id": oversized_component,
                    "user_id": oversized_component,
                },
            ],
            {},
        )

    assert effects == []


def test_collection_definition_request_enforces_the_storage_identity_boundary():
    from emby_collections.api_models import CollectionDefinitionRequest

    payload = {
        "name": "Collection",
        "source_type": "tmdb_list",
        "source_value": "123",
        "server_ids": ["server"],
    }
    maximum = "c" * COLLECTION_DEFINITION_ID_MAX_LENGTH
    assert CollectionDefinitionRequest(id=maximum, **payload).id == maximum
    with pytest.raises(ValidationError):
        CollectionDefinitionRequest(id=maximum + "c", **payload)


def test_collection_path_contracts_share_the_definition_id_limit():
    from emby_collections.routes import router

    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    paths = {
        path: operation
        for path, operations in schema["paths"].items()
        if "{collection_id}" in path
        for operation in operations.values()
        if isinstance(operation, dict) and "parameters" in operation
    }

    assert paths
    for operation in paths.values():
        parameter = next(
            item for item in operation["parameters"] if item["name"] == "collection_id"
        )
        assert parameter["schema"]["maxLength"] == COLLECTION_DEFINITION_ID_MAX_LENGTH


def test_collection_manager_rejects_an_oversized_id_before_backend_or_remote_effects(
    monkeypatch,
):
    from emby_collections import collection_store

    monkeypatch.setattr(
        collection_store,
        "_ensure_db_backend",
        lambda: pytest.fail("backend resolved before collection id validation"),
    )

    with pytest.raises(ValueError, match=str(COLLECTION_DEFINITION_ID_MAX_LENGTH)):
        collection_store.save_collection_definition(
            {
                "id": "c" * (COLLECTION_DEFINITION_ID_MAX_LENGTH + 1),
                "name": "Collection",
                "source_type": "tmdb_list",
                "source_value": "123",
                "server_ids": ["server"],
            }
        )


@pytest.mark.parametrize(
    "operation",
    [
        "get",
        "save",
        "mutate",
        "delete",
        "bundle",
        "get-poster",
        "save-poster",
        "delete-poster",
        "get-backdrop",
        "save-backdrop",
        "delete-backdrop",
    ],
)
def test_collection_writers_reject_an_oversized_id_before_session(operation: str):
    from core.storage.storage_collections import StorageCollectionsMixin

    storage = type("Storage", (StorageCollectionsMixin, _NoSessionStorage), {})()
    invalid_id = "c" * (COLLECTION_DEFINITION_ID_MAX_LENGTH + 1)

    operations = {
        "get": lambda: storage.get_emby_collection_definition(invalid_id),
        "save": lambda: storage.save_emby_collection_definition({"id": invalid_id}),
        "mutate": lambda: storage.mutate_emby_collection_definition(
            invalid_id, lambda value: value
        ),
        "delete": lambda: storage.delete_emby_collection_definition(invalid_id),
        "bundle": lambda: storage.delete_emby_collection_bundle(invalid_id),
        "get-poster": lambda: storage.get_emby_collection_poster(invalid_id),
        "save-poster": lambda: storage.save_emby_collection_poster(
            invalid_id, "image/png", b"poster"
        ),
        "delete-poster": lambda: storage.delete_emby_collection_poster(invalid_id),
        "get-backdrop": lambda: storage.get_emby_collection_backdrop(invalid_id),
        "save-backdrop": lambda: storage.save_emby_collection_backdrop(
            invalid_id, "image/png", b"backdrop"
        ),
        "delete-backdrop": lambda: storage.delete_emby_collection_backdrop(invalid_id),
    }

    with pytest.raises(ValueError, match=str(COLLECTION_DEFINITION_ID_MAX_LENGTH)):
        operations[operation]()


@pytest.mark.parametrize("operation", ["sync", "background"])
def test_collection_sync_paths_validate_identity_before_side_effects(
    operation: str,
    monkeypatch,
):
    invalid_id = "c" * (COLLECTION_DEFINITION_ID_MAX_LENGTH + 1)
    if operation == "sync":
        from emby_collections import collection_sync

        monkeypatch.setattr(
            collection_sync,
            "_ensure_db_backend",
            lambda: pytest.fail("backend resolved before collection id validation"),
        )
        def callback(value):
            return collection_sync.run_collection_sync(value)
    else:
        from emby_collections import operations

        monkeypatch.setattr(
            operations,
            "start_tracked_background_job",
            lambda **_kwargs: pytest.fail(
                "background operation started before collection id validation"
            ),
        )

        def callback(value):
            return operations.start_collection_sync_operation(
                collection_id=value,
                runner=lambda _collection_id: {},
            )

    with pytest.raises(ValueError, match=str(COLLECTION_DEFINITION_ID_MAX_LENGTH)):
        callback(invalid_id)


def test_library_collection_type_boundary_is_shared_by_request_and_storage():
    from core.storage.storage_models import LibraryAssociation, LibraryGroupOrder
    from emby_libraries.scan_api_models import LibraryGroupOrderEntry

    maximum = "t" * LIBRARY_COLLECTION_TYPE_MAX_LENGTH
    assert (
        LibraryGroupOrderEntry(
            collection_type=maximum,
            group_name="Group",
            position=0,
        ).collection_type
        == maximum
    )
    with pytest.raises(ValidationError):
        LibraryGroupOrderEntry(
            collection_type=maximum + "t",
            group_name="Group",
            position=0,
        )

    assert LibraryAssociation.__table__.c.collection_type.type.length == (
        LIBRARY_COLLECTION_TYPE_MAX_LENGTH
    )
    assert LibraryGroupOrder.__table__.c.collection_type.type.length == (
        LIBRARY_COLLECTION_TYPE_MAX_LENGTH
    )


def test_library_order_rejects_an_oversized_type_before_backend(monkeypatch):
    from emby_libraries import order_snapshots

    monkeypatch.setattr(
        order_snapshots,
        "_ensure_db_backend",
        lambda: pytest.fail("backend resolved before collection_type validation"),
    )
    payload, status = order_snapshots._build_group_order_post_snapshot(
        [
            {
                "collection_type": "t" * (LIBRARY_COLLECTION_TYPE_MAX_LENGTH + 1),
                "group_name": "Group",
                "position": 0,
            }
        ]
    )

    assert status == 400
    assert payload["success"] is False


def test_library_order_writer_preflights_every_type_before_session():
    from core.storage.storage_collections import StorageCollectionsMixin

    storage = type("Storage", (StorageCollectionsMixin, _NoSessionStorage), {})()
    with pytest.raises(ValueError, match=str(LIBRARY_COLLECTION_TYPE_MAX_LENGTH)):
        storage.save_library_group_order(
            {
                ("movies", "Valid"): 0,
                (
                    "t" * (LIBRARY_COLLECTION_TYPE_MAX_LENGTH + 1),
                    "Invalid",
                ): 1,
            }
        )
