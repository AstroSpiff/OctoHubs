"""Regression and class-level canaries for R43-L-03 and R43-L-04."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import ValidationError

from core.storage.field_limits import (
    EMBY_USER_NAME_MAX_LENGTH,
    EMBY_STORED_IDENTIFIER_MAX_LENGTH,
    EMBY_GROUP_ID_MAX_LENGTH,
    SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH,
    ICON_BINDING_TARGET_ID_MAX_LENGTH,
    ICON_BINDING_TARGET_TYPE_MAX_LENGTH,
    ICON_PROFILE_ID_MAX_LENGTH,
    ICON_PROFILE_LABEL_MAX_LENGTH,
    ICON_RULE_COLUMN_KEY_MAX_LENGTH,
)
from core.storage.storage_models import (
    EmbyLatestCacheChange,
    EmbyLatestCacheItem,
    EmbyProbeBlacklist,
    EmbyProbeHistory,
    EmbyProbeQueue,
    EmbyProbeRecentScan,
    EmbyIconBinding,
    EmbyGroupPassword,
    EmbyIconProfile,
    EmbyIconRule,
    EmbyUserBackup,
    EmbyUserCreationJournal,
    EmbyUserLink,
    LibraryAssociation as StoredLibraryAssociation,
)
from core.storage.storage_collections import StorageCollectionsMixin
from core.storage.storage_latest import StorageLatestMixin
from core.storage.storage_probe import StorageProbeMixin
from core.storage.storage_users import StorageUsersMixin
from emby_users.api_models import CheckUserRequest, CreateUserTarget, ServerUserTarget
from emby_users.icon_api_models import (
    IconBindingRequest,
    IconProfileDeleteRequest,
    IconProfileRequest,
    IconRuleCoordinates,
    IconRuleDeleteRequest,
)
from emby_users.icon_manager import (
    IconManager,
    IconTargetBusyError,
    IconTargetNotFoundError,
)
from emby_users.group_user_resolver import GroupUserResolver
from emby_users.password_manager import PasswordManager
from emby_users.icon_routes import (
    api_emby_icons_binding_save,
    api_emby_icons_rule_save,
    init_emby_icon_routes,
    router as icon_router,
)
from emby_users.mutation_coordinator import (
    UserMutationCoordinator,
    group_sync_key,
    user_mutation_keys,
)
from emby_libraries.manager import EmbyLibrariesManager
from emby_libraries.scan_api_models import LibraryAssociation as ApiLibraryAssociation


@pytest.mark.parametrize(
    ("factory", "field", "maximum"),
    [
        (lambda value: IconProfileRequest(label=value), "label", ICON_PROFILE_LABEL_MAX_LENGTH),
        (
            lambda value: IconProfileRequest(profile_id=value, label="Profile"),
            "profile_id",
            ICON_PROFILE_ID_MAX_LENGTH,
        ),
        (
            lambda value: IconProfileDeleteRequest(profile_id=value),
            "profile_id",
            ICON_PROFILE_ID_MAX_LENGTH,
        ),
        (
            lambda value: IconBindingRequest(
                target_type="group", target_id=value, profile_id=""
            ),
            "target_id",
            EMBY_GROUP_ID_MAX_LENGTH,
        ),
        (
            lambda value: IconBindingRequest(
                target_type="user", target_id="server:user", profile_id=value
            ),
            "profile_id",
            ICON_PROFILE_ID_MAX_LENGTH,
        ),
        (
            lambda value: IconRuleCoordinates(profile_id="profile", column_key=value),
            "column_key",
            ICON_RULE_COLUMN_KEY_MAX_LENGTH,
        ),
        (
            lambda value: IconRuleDeleteRequest(profile_id="profile", column_key=value),
            "column_key",
            ICON_RULE_COLUMN_KEY_MAX_LENGTH,
        ),
        (lambda value: CheckUserRequest(server_id="server", username=value), "username", EMBY_USER_NAME_MAX_LENGTH),
        (lambda value: CreateUserTarget(server_id="server", username=value), "username", EMBY_USER_NAME_MAX_LENGTH),
    ],
)
def test_bounded_api_contracts_accept_max_and_reject_max_plus_one(
    factory,
    field,
    maximum,
):
    assert len(getattr(factory("x" * maximum), field)) == maximum
    with pytest.raises(ValidationError):
        factory("x" * (maximum + 1))


def test_icon_binding_target_type_is_a_closed_api_contract():
    for target_type, target_id in (("user", "server:user"), ("group", "target")):
        assert IconBindingRequest(
            target_type=target_type,
            target_id=target_id,
        ).target_type == target_type

    with pytest.raises(ValidationError):
        IconBindingRequest.model_validate(
            {"target_type": "future-kind", "target_id": "ghost"}
        )


@pytest.mark.parametrize(
    "target_id",
    [
        "missing-separator",
        ":user",
        "server:",
        "server:user:extra",
        "server/user:user",
        "server:user/name",
        "server :user",
        "server: user",
        "sérver:user",
        "server:usér",
        f"{'s' * (EMBY_STORED_IDENTIFIER_MAX_LENGTH + 1)}:user",
        f"server:{'u' * (EMBY_STORED_IDENTIFIER_MAX_LENGTH + 1)}",
    ],
)
def test_user_icon_target_contract_rejects_unaddressable_identifiers(target_id):
    with pytest.raises(ValidationError):
        IconBindingRequest(target_type="user", target_id=target_id)


@pytest.mark.parametrize("factory", [CheckUserRequest, CreateUserTarget])
def test_username_casefold_expansion_cannot_overflow_creation_journal(factory):
    with pytest.raises(ValidationError):
        factory(server_id="server", username="ß" * 128)


def test_stored_emby_identifier_contract_matches_varchar_boundary():
    maximum = "s" * EMBY_STORED_IDENTIFIER_MAX_LENGTH
    assert ServerUserTarget(server_id=maximum, user_id=maximum).server_id == maximum
    with pytest.raises(ValidationError):
        ServerUserTarget(
            server_id="s" * (EMBY_STORED_IDENTIFIER_MAX_LENGTH + 1),
            user_id="user",
        )


@pytest.mark.parametrize(
    "target_id",
    [
        f"{'s' * EMBY_STORED_IDENTIFIER_MAX_LENGTH}:{'u' * EMBY_STORED_IDENTIFIER_MAX_LENGTH}",
    ],
)
def test_user_icon_target_accepts_each_identifier_max_at_varchar_boundary(target_id):
    request = IconBindingRequest(target_type="user", target_id=target_id)
    assert request.target_id == target_id


def test_group_icon_target_uses_group_identifier_boundary():
    maximum = "g" * EMBY_GROUP_ID_MAX_LENGTH
    assert IconBindingRequest(target_type="group", target_id=maximum).target_id == maximum
    with pytest.raises(ValidationError):
        IconBindingRequest(
            target_type="group",
            target_id="g" * (EMBY_GROUP_ID_MAX_LENGTH + 1),
        )


def test_icon_rule_multipart_rejects_oversize_before_manager_or_file_processing():
    calls: list[tuple[object, ...]] = []
    manager = type(
        "Manager",
        (),
        {
            "icon_manager": type(
                "Icons",
                (),
                {"save_icon_rule": lambda _self, *args: calls.append(args)},
            )()
        },
    )()
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            api_emby_icons_rule_save(
                profile_id="p",
                column_key="x" * (ICON_RULE_COLUMN_KEY_MAX_LENGTH + 1),
                file=UploadFile(file=BytesIO(b"not-read"), filename="icon.png"),
                _csrf=None,
                user=True,
            )
        )

    assert caught.value.status_code == 422
    assert calls == []


class _IconStorage:
    def __init__(self):
        self.saved: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def icon_profile_exists(self, _profile_id):
        return True

    def save_icon_binding(self, target_type, target_id, profile_id):
        self.saved.append((target_type, target_id, profile_id))

    def delete_icon_binding(self, target_type, target_id):
        self.deleted.append((target_type, target_id))


def _manager(groups, storage=None, coordinator=None):
    storage = storage or _IconStorage()
    manager = IconManager(
        storage,
        get_users_dashboard_data=lambda: {"groups": groups},
        get_server_by_id=lambda _server_id: None,
        mutation_coordinator=coordinator,
    )
    manager._sync_icons_for_binding = lambda target_type, target_id: None  # pyright: ignore[reportAttributeAccessIssue]
    return manager, storage


@pytest.mark.parametrize(
    ("target_type", "target_id"),
    [("user", "server:ghost"), ("group", "ghost")],
)
def test_icon_manager_rejects_missing_target_without_persistence(
    target_type,
    target_id,
):
    manager, storage = _manager([])

    with pytest.raises(IconTargetNotFoundError):
        manager.save_icon_binding(target_type, target_id, "profile")

    assert storage.saved == []


def test_icon_manager_can_remove_stale_binding_after_target_disappears():
    manager, storage = _manager([])

    manager.save_icon_binding("user", "server:removed", "")

    assert storage.saved == []
    assert storage.deleted == [("user", "server:removed")]


def test_icon_binding_route_removes_stale_target_idempotently():
    icon_manager, storage = _manager([])
    manager = type("Manager", (), {"icon_manager": icon_manager})()
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )

    response = asyncio.run(
        api_emby_icons_binding_save(
            payload=IconBindingRequest(
                target_type="user",
                target_id="server:removed",
                profile_id="",
            ),
            _csrf=None,
            user=True,
        )
    )

    assert response == {"ok": True}
    assert storage.deleted == [("user", "server:removed")]


def test_icon_binding_route_maps_missing_target_to_not_found():
    icon_manager, storage = _manager([])
    manager = type("Manager", (), {"icon_manager": icon_manager})()
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )

    response = asyncio.run(
        api_emby_icons_binding_save(
            payload=IconBindingRequest(
                target_type="user",
                target_id="server:ghost",
                profile_id="profile",
            ),
            _csrf=None,
            user=True,
        )
    )

    assert response.status_code == 404
    assert json.loads(response.body) == {
        "ok": False,
        "error": "Icon target not found",
    }
    assert storage.saved == []


def test_icon_binding_busy_response_matches_documented_openapi_contract():
    class BusyIcons:
        def save_icon_binding(self, *_args):
            raise IconTargetBusyError("busy")

    manager = type("Manager", (), {"icon_manager": BusyIcons()})()
    init_emby_icon_routes(
        require_user=lambda _request: True,
        get_emby_user_manager=lambda: manager,
        validate_csrf=lambda _request, _token: True,
    )

    response = asyncio.run(
        api_emby_icons_binding_save(
            payload=IconBindingRequest(
                target_type="group",
                target_id="group",
                profile_id="profile",
            ),
            _csrf=None,
            user=True,
        )
    )
    app = FastAPI()
    app.include_router(icon_router)
    documented = app.openapi()["paths"]["/api/emby/icons/binding"]["post"]["responses"]

    assert response.status_code == 409
    assert json.loads(response.body) == {"ok": False, "error": "Icon target busy"}
    assert set(documented) >= {"200", "404", "409", "422"}


@pytest.mark.parametrize(
    ("target_type", "target_id"),
    [("user", "server:user"), ("group", "group")],
)
def test_icon_manager_persists_only_targets_in_the_current_snapshot(
    target_type,
    target_id,
):
    groups = [
        {
            "id": "group",
            "users": [{"server_id": "server", "user_id": "user"}],
        }
    ]
    manager, storage = _manager(groups)

    manager.save_icon_binding(target_type, target_id, "profile")

    assert storage.saved == [(target_type, target_id, "profile")]


@pytest.mark.parametrize(
    ("target_type", "target_id", "keys"),
    [
        ("user", "server:user", user_mutation_keys("server", "user")),
        ("group", "group", (group_sync_key("group"),)),
    ],
)
def test_icon_binding_cannot_race_a_target_lifecycle_owner(
    target_type,
    target_id,
    keys,
):
    storage = _IconStorage()
    coordinator = UserMutationCoordinator(storage)
    entered = Event()
    release = Event()

    def own_target_lifecycle():
        with coordinator.guard(keys) as acquired:
            assert acquired is True
            entered.set()
            assert release.wait(timeout=5)

    owner = Thread(target=own_target_lifecycle)
    owner.start()
    assert entered.wait(timeout=5)
    manager, _ = _manager(
        [{"id": "group", "users": [{"server_id": "server", "user_id": "user"}]}],
        storage,
        coordinator,
    )
    try:
        with pytest.raises(IconTargetBusyError):
            manager.save_icon_binding(target_type, target_id, "profile")
        assert storage.saved == []
    finally:
        release.set()
        owner.join(timeout=5)
    assert not owner.is_alive()


class _NoSessionStorage(StorageUsersMixin):
    def _get_session(self):
        raise AssertionError("validation must happen before opening a DB session")


@pytest.mark.parametrize(
    "operation",
    [
        lambda storage: storage.save_icon_profile("p", "x" * (ICON_PROFILE_LABEL_MAX_LENGTH + 1), False),
        lambda storage: storage.save_icon_rule("p", "x" * (ICON_RULE_COLUMN_KEY_MAX_LENGTH + 1), "/icon"),
        lambda storage: storage.save_icon_binding("future-kind", "target", "profile"),
        lambda storage: storage.save_icon_binding("user", "x" * (ICON_BINDING_TARGET_ID_MAX_LENGTH + 1), "profile"),
        lambda storage: storage.save_icon_binding("user", "server:user:extra", "profile"),
        lambda storage: storage.save_icon_binding("group", "g" * (EMBY_GROUP_ID_MAX_LENGTH + 1), "profile"),
        lambda storage: storage.save_icon_binding("user", "server/user:user", "profile"),
        lambda storage: storage.save_icon_binding("user", "server: user", "profile"),
        lambda storage: storage.save_icon_binding("user", "server:usér", "profile"),
        lambda storage: storage.reserve_emby_user_creation("server", "x" * (EMBY_USER_NAME_MAX_LENGTH + 1)),
        lambda storage: storage.mutate_user_links(
            group_passwords={
                "g" * (SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH + 1): "encrypted"
            }
        ),
    ],
)
def test_storage_rejects_bounded_values_before_database_effects(operation):
    with pytest.raises(ValueError):
        operation(_NoSessionStorage())


def test_synthetic_unlinked_group_boundary_is_canonical_and_persistable():
    maximum = "i" * EMBY_STORED_IDENTIFIER_MAX_LENGTH
    synthetic_id = GroupUserResolver(object()).get_unlinked_group_id(maximum, maximum)

    assert len(synthetic_id) == SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH == 266
    assert EmbyGroupPassword.__table__.c.group_id.type.length == len(synthetic_id)
    with pytest.raises(AssertionError, match="before opening"):
        _NoSessionStorage().save_group_password(synthetic_id, "encrypted")
    with pytest.raises(ValueError):
        _NoSessionStorage().save_group_password(
            "g" * (SYNTHETIC_GROUP_PASSWORD_ID_MAX_LENGTH + 1),
            "encrypted",
        )


def test_user_password_rejects_unpersistable_synthetic_id_before_remote_effect():
    remote_calls: list[object] = []
    manager = PasswordManager(
        storage=object(),
        get_server_by_id=lambda _server_id: {"id": "server"},
        get_group_users=lambda _group_id: [],
        get_unlinked_group_id=lambda _server_id, _user_id: "x" * 267,
        update_user_password=lambda *args: remote_calls.append(args) or (True, None),
    )

    with pytest.raises(ValueError):
        manager._update_user_password_guarded("server", "user", "password")

    assert remote_calls == []


def test_icon_and_creation_schema_lengths_share_the_canonical_contract():
    assert EmbyIconProfile.__table__.c.id.type.length == ICON_PROFILE_ID_MAX_LENGTH
    assert EmbyIconProfile.__table__.c.label.type.length == ICON_PROFILE_LABEL_MAX_LENGTH
    assert EmbyIconRule.__table__.c.profile_id.type.length == ICON_PROFILE_ID_MAX_LENGTH
    assert EmbyIconRule.__table__.c.column_key.type.length == ICON_RULE_COLUMN_KEY_MAX_LENGTH
    assert EmbyIconBinding.__table__.c.target_type.type.length == ICON_BINDING_TARGET_TYPE_MAX_LENGTH
    assert EmbyIconBinding.__table__.c.target_id.type.length == ICON_BINDING_TARGET_ID_MAX_LENGTH
    assert EmbyIconBinding.__table__.c.profile_id.type.length == ICON_PROFILE_ID_MAX_LENGTH
    assert EmbyUserCreationJournal.__table__.c.username.type.length == EMBY_USER_NAME_MAX_LENGTH
    assert EmbyUserCreationJournal.__table__.c.normalized_username.type.length == EMBY_USER_NAME_MAX_LENGTH
    for model in (EmbyUserLink, EmbyUserBackup):
        assert model.__table__.c.server_id.type.length == EMBY_STORED_IDENTIFIER_MAX_LENGTH
        assert model.__table__.c.user_id.type.length == EMBY_STORED_IDENTIFIER_MAX_LENGTH
    assert EmbyUserCreationJournal.__table__.c.server_id.type.length == EMBY_STORED_IDENTIFIER_MAX_LENGTH


def test_identifier_migration_is_immutable_and_matches_runtime_contract():
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260908_21_widen_emby_user_identifiers.py"
    ).read_text(encoding="utf-8")
    assert "_OPAQUE_IDENTIFIER_LENGTH = 128" in source
    assert "_COMPOSITE_ICON_TARGET_LENGTH = 257" in source
    assert "_SYNTHETIC_GROUP_PASSWORD_LENGTH = 266" in source
    assert "from core." not in source
    assert EMBY_STORED_IDENTIFIER_MAX_LENGTH == 128
    assert ICON_BINDING_TARGET_ID_MAX_LENGTH == 257


def test_library_association_api_uses_canonical_opaque_identifier_boundary():
    maximum = "i" * EMBY_STORED_IDENTIFIER_MAX_LENGTH
    accepted = ApiLibraryAssociation(
        server_id=maximum,
        library_id=maximum,
        group_name="Group",
    )
    assert accepted.server_id == maximum
    assert accepted.library_id == maximum
    for field in ("server_id", "library_id"):
        payload = {
            "server_id": "server",
            "library_id": "library",
            "group_name": "Group",
        }
        payload[field] = "i" * (EMBY_STORED_IDENTIFIER_MAX_LENGTH + 1)
        with pytest.raises(ValidationError):
            ApiLibraryAssociation.model_validate(payload)


def test_library_association_manager_rejects_invalid_id_before_storage():
    calls: list[object] = []

    def ensure_storage():
        calls.append("storage")
        raise AssertionError("storage must not be resolved for invalid input")

    manager = EmbyLibrariesManager(
        load_config=lambda: ({}, True),
        ensure_db_backend=ensure_storage,
        json_error=lambda message, status: ({"error": message}, status),
        storage_error_cls=RuntimeError,
    )

    result = manager.build_associations_post_snapshot(
        [{"server_id": "server/invalid", "library_id": "library", "group_name": "Group"}]
    )

    assert result == ({"error": "Associazione libreria non valida"}, 400)
    assert calls == []


class _NoCollectionSessionStorage(StorageCollectionsMixin):
    _app_settings_cipher = None

    def _get_session(self):
        raise AssertionError("validation must happen before opening a DB session")


@pytest.mark.parametrize(
    "identity",
    [
        "i" * (EMBY_STORED_IDENTIFIER_MAX_LENGTH + 1),
        "invalid/id",
        "invalid id",
        "inválid",
    ],
)
def test_library_association_storage_rejects_invalid_id_before_session(identity):
    storage = _NoCollectionSessionStorage()
    with pytest.raises(ValueError):
        storage.save_library_associations({(identity, "library"): "Group"})
    with pytest.raises(ValueError):
        storage.save_library_associations({("server", identity): "Group"})


def test_library_association_schema_uses_canonical_identifier_boundary():
    assert StoredLibraryAssociation.__table__.c.server_id.type.length == EMBY_STORED_IDENTIFIER_MAX_LENGTH
    assert StoredLibraryAssociation.__table__.c.library_id.type.length == EMBY_STORED_IDENTIFIER_MAX_LENGTH


def test_all_persisted_remote_emby_id_columns_share_canonical_boundary():
    columns = (
        EmbyLatestCacheItem.__table__.c.item_id,
        EmbyLatestCacheItem.__table__.c.library_id,
        EmbyLatestCacheChange.__table__.c.media_source_id,
        EmbyProbeBlacklist.__table__.c.item_id,
        EmbyProbeBlacklist.__table__.c.library_id,
        EmbyProbeBlacklist.__table__.c.media_source_id,
        EmbyProbeQueue.__table__.c.item_id,
        EmbyProbeQueue.__table__.c.library_id,
        EmbyProbeQueue.__table__.c.media_source_id,
        EmbyProbeHistory.__table__.c.item_id,
        EmbyProbeHistory.__table__.c.media_source_id,
        EmbyProbeRecentScan.__table__.c.library_id,
    )
    assert {column.type.length for column in columns} == {
        EMBY_STORED_IDENTIFIER_MAX_LENGTH
    }
    for model in (
        EmbyLatestCacheItem,
        EmbyProbeBlacklist,
        EmbyProbeQueue,
        EmbyProbeHistory,
        EmbyProbeRecentScan,
    ):
        assert model.__table__.c.server_id.type.length == 36


class _NoLatestSessionStorage(StorageLatestMixin):
    def _get_session(self):
        raise AssertionError("validation must happen before opening a DB session")


class _NoProbeSessionStorage(StorageProbeMixin):
    _app_settings_cipher = None

    def _get_session(self):
        raise AssertionError("validation must happen before opening a DB session")


@pytest.mark.parametrize(
    "payload",
    [
        {"movies": [{"item_id": "invalid/item"}]},
        {"movies": [{"item_id": "item", "library_id": "x" * 129}]},
        {
            "movies": [
                {"item_id": "item", "changes": [{"media_source_id": "inválid"}]}
            ]
        },
    ],
)
def test_latest_writer_rejects_remote_ids_before_session(payload):
    with pytest.raises(ValueError):
        _NoLatestSessionStorage().save_latest_cache("feed", payload, 1, 1)


@pytest.mark.parametrize(
    "operation",
    [
        lambda storage: storage.add_to_probe_queue(
            [{"server_id": "server", "item_id": "invalid/item"}]
        ),
        lambda storage: storage.add_to_probe_queue(
            [{"server_id": "server", "item_id": "item", "library_id": "x" * 129}]
        ),
        lambda storage: storage.update_probe_blacklist(
            "server", "item", "name", "reason", media_source_id="inválid"
        ),
        lambda storage: storage.add_probe_history(
            {"server_id": "server", "item_id": "x" * 129}
        ),
        lambda storage: storage.save_recent_scan_timestamp(
            "server", None, "library/invalid"
        ),
    ],
)
def test_probe_writers_reject_remote_ids_before_session(operation):
    with pytest.raises(ValueError):
        operation(_NoProbeSessionStorage())


def test_latest_and_probe_writers_accept_remote_id_max_before_session_gate():
    maximum = "i" * EMBY_STORED_IDENTIFIER_MAX_LENGTH
    latest = _NoLatestSessionStorage()
    with pytest.raises(AssertionError, match="before opening"):
        latest.save_latest_cache(
            "feed",
            {
                "movies": [
                    {
                        "item_id": maximum,
                        "library_id": maximum,
                        "changes": [{"media_source_id": maximum}],
                    }
                ]
            },
            1,
            1,
        )
    probe = _NoProbeSessionStorage()
    with pytest.raises(AssertionError, match="before opening"):
        probe.add_to_probe_queue(
            [
                {
                    "server_id": "server",
                    "item_id": maximum,
                    "library_id": maximum,
                    "media_source_id": maximum,
                }
            ]
        )
