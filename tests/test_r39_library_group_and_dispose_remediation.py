"""R39 regressors for bounded library group names and engine cleanup."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from core.library_group_names import (
    LIBRARY_GROUP_NAME_PATTERN,
    MAX_LIBRARY_GROUP_NAME_LENGTH,
)
from emby_libraries.scan_api_models import (
    LibraryAssociation,
    LibraryGroupOrderEntry,
    TrackedGroupScanRequest,
    TrackedScanLibraryRequest,
)
from services.workflow_api_models import WorkflowContextRequest


def _group_request_payload(group_name: str) -> dict:
    return {
        "group_name": group_name,
        "libraries": [{"server_id": "server-a", "library_id": "library-a"}],
    }


@pytest.mark.parametrize(
    "model_factory",
    [
        pytest.param(
            lambda name: TrackedScanLibraryRequest(
                server_id="server-a", library_ids=["library-a"], group_name=name
            ),
            id="tracked-library",
        ),
        pytest.param(
            lambda name: TrackedGroupScanRequest(**_group_request_payload(name)),
            id="tracked-group",
        ),
        pytest.param(
            lambda name: LibraryAssociation(
                server_id="server-a", library_id="library-a", group_name=name
            ),
            id="association",
        ),
        pytest.param(
            lambda name: LibraryGroupOrderEntry(
                collection_type="movies", group_name=name, position=0
            ),
            id="order",
        ),
        pytest.param(
            lambda name: WorkflowContextRequest(group_name=name),
            id="workflow",
        ),
    ],
)
def test_library_group_name_boundaries_are_shared_by_every_mutating_model(
    model_factory,
):
    with pytest.raises(ValidationError):
        model_factory("")
    assert model_factory(" x ").group_name == "x"
    assert len(model_factory("x" * MAX_LIBRARY_GROUP_NAME_LENGTH).group_name) == 500
    with pytest.raises(ValidationError):
        model_factory("x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 1))


@pytest.mark.parametrize(
    "control",
    ["\x00", "\r", "\n", "\t", "\x7f", "\x85", "\u2028", "\u2029", "\u200b", "\u202e", "\u2066"],
)
def test_library_group_name_rejects_every_control_character(control: str):
    from emby_libraries.scan_api_models import TrackedGroupScanRequest

    with pytest.raises(ValidationError):
        TrackedGroupScanRequest(**_group_request_payload(f"Cinema{control}forged"))


def test_library_group_name_normalizer_rejects_unicode_controls_before_stripping():
    from core.library_group_names import normalize_library_group_name

    for value in ("Cinema\x85", "\u2028Cinema", "Cinema\u200b", "Cinema\u202eRTL"):
        with pytest.raises(ValueError, match="controllo o invisibili"):
            normalize_library_group_name(value)


def _max_lengths(schema: object) -> set[int]:
    if isinstance(schema, dict):
        values = {
            value
            for key, value in schema.items()
            if key == "maxLength" and isinstance(value, int)
        }
        return values.union(*(_max_lengths(value) for value in schema.values()))
    if isinstance(schema, list):
        return set().union(*(_max_lengths(value) for value in schema))
    return set()


def _patterns(schema: object) -> set[str]:
    if isinstance(schema, dict):
        values = {
            value
            for key, value in schema.items()
            if key == "pattern" and isinstance(value, str)
        }
        return values.union(*(_patterns(value) for value in schema.values()))
    if isinstance(schema, list):
        return set().union(*(_patterns(value) for value in schema))
    return set()


def test_library_group_name_contract_matches_every_model_and_storage_column():
    from core.storage.storage_models import LibraryAssociation as StoredAssociation
    from core.storage.storage_models import LibraryGroupOrder as StoredOrder
    from emby_libraries import scan_api_models
    from services.workflow_api_models import WorkflowContextRequest

    models = (
        scan_api_models.ScanGroupSession,
        scan_api_models.ScanJob,
        scan_api_models.ActiveScanJob,
        scan_api_models.TrackedScanLibraryRequest,
        scan_api_models.TrackedGroupScanRequest,
        scan_api_models.LibraryScanActionResponse,
        scan_api_models.LibraryGroup,
        scan_api_models.LibraryAssociation,
        scan_api_models.LibraryAssociationResponseEntry,
        scan_api_models.LibraryGroupOrderEntry,
        scan_api_models.LibraryGroupOrderResponseEntry,
        WorkflowContextRequest,
    )
    for model in models:
        group_schema = model.model_json_schema()["properties"]["group_name"]
        assert _max_lengths(group_schema) == {MAX_LIBRARY_GROUP_NAME_LENGTH}
        assert _patterns(group_schema) == {LIBRARY_GROUP_NAME_PATTERN}

    assert StoredAssociation.__table__.c.group_name.type.length == MAX_LIBRARY_GROUP_NAME_LENGTH
    assert StoredOrder.__table__.c.group_name.type.length == MAX_LIBRARY_GROUP_NAME_LENGTH

    # The grouped-libraries response historically permits its empty fallback.
    assert scan_api_models.LibraryGroup(
        group_name="", collection_type="movies"
    ).group_name == ""


def test_automatic_group_names_are_bounded_before_group_identity_and_response():
    from emby_libraries.grouping import group_libraries

    oversized = "x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 1)
    groups = group_libraries(
        {
            "server": {
                "libraries": [
                    {"id": "library", "name": oversized, "collection_type": "movies"}
                ]
            }
        }
    )

    assert groups[0]["group_name"] == oversized[:MAX_LIBRARY_GROUP_NAME_LENGTH]


@pytest.mark.anyio
async def test_oversized_group_name_is_a_422_validation_error_before_dispatch():
    from emby_libraries.scan_api_models import TrackedGroupScanRequest
    from web.request_validation import validated_json_payload

    class Request:
        async def json(self):
            return _group_request_payload("x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 1))

    with pytest.raises(RequestValidationError):
        await validated_json_payload(Request(), TrackedGroupScanRequest)


def _scan_manager(*, load_config, tracker):
    from emby_libraries.scan_manager import EmbyLibraryScanManager

    return EmbyLibraryScanManager(
        load_config=load_config,
        json_error=lambda message, status_code=400, **extra: (
            {"success": False, "message": message, **extra},
            status_code,
        ),
        json_success=lambda message=None, status_code=200, **extra: (
            {"success": True, "message": message, **extra},
            status_code,
        ),
        scan_tracker=tracker,
        trigger_library_scan=lambda *_args: (False, "rejected"),
        fetch_libraries=lambda _server: ([{"id": "library"}], None),
        get_app_event_loop=lambda: None,
        emby_api_client_cls=lambda _server: object(),
        log_flush=lambda _message: None,
        tracked_scan_guard=lambda: nullcontext(True),
    )


def test_oversized_group_name_reaches_no_scan_side_effect():
    manager = _scan_manager(
        load_config=lambda: pytest.fail("configuration read after invalid group_name"),
        tracker=pytest.fail,
    )

    payload, status = manager.build_scan_group_tracked_snapshot(
        {
            "group_name": "x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 1),
            "libraries": [{"server_id": "server-a", "library_id": "library"}],
        }
    )

    assert status == 400
    assert payload["success"] is False


@pytest.mark.parametrize("operation", ["associations", "order"])
def test_storage_rejects_group_name_before_opening_a_session(operation: str):
    from core.storage.storage_collections import StorageCollectionsMixin

    class Storage(StorageCollectionsMixin):
        def _get_session(self):
            pytest.fail("session opened for an invalid group_name")

    oversized = "x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 1)
    with pytest.raises(ValueError, match="supera 500"):
        if operation == "associations":
            Storage().save_library_associations({("server", "library"): oversized})
        else:
            Storage().save_library_group_order({("movies", oversized): 0})


def test_one_hundred_server_fanout_keeps_the_total_group_snapshot_bounded():
    from emby_libraries.tracker import LibraryScanTracker

    servers = [
        {"id": f"server-{index}", "enabled": True}
        for index in range(100)
    ]
    tracker = LibraryScanTracker(lambda: None, lambda _message: None)
    manager = _scan_manager(
        load_config=lambda: ({"EMBY": {"SERVERS": servers}}, True),
        tracker=tracker,
    )
    group_name = "x" * MAX_LIBRARY_GROUP_NAME_LENGTH

    _payload, status = manager.build_scan_group_tracked_snapshot(
        {
            "group_name": group_name,
            "libraries": [
                {"server_id": server["id"], "library_id": "library"}
                for server in servers
            ],
        }
    )

    jobs = tracker.get_all_jobs()
    assert status == 503
    assert len(jobs) == 100
    assert sum(len(job["group_name"]) for job in jobs) == (
        100 * MAX_LIBRARY_GROUP_NAME_LENGTH
    )


class _ConnectFailure:
    def __init__(self, error: BaseException):
        self.error = error

    def __enter__(self):
        raise self.error

    def __exit__(self, *_args):
        return False


class _MigrationEngine:
    def __init__(self, primary: BaseException, cleanup: BaseException):
        self.primary = primary
        self.cleanup = cleanup
        self.dispose_calls = 0

    def connect(self):
        return _ConnectFailure(self.primary)

    def dispose(self):
        self.dispose_calls += 1
        raise self.cleanup


@pytest.mark.parametrize("helper", ["status", "validate"])
@pytest.mark.parametrize(
    "primary",
    [
        OperationalError("PRIMARY_CONNECT", {}, RuntimeError("driver")),
        KeyboardInterrupt("PRIMARY_INTERRUPT"),
    ],
)
def test_migration_primary_survives_dispose_failure(
    monkeypatch: pytest.MonkeyPatch,
    helper: str,
    primary: BaseException,
):
    from core import database_migrations

    cleanup = GeneratorExit("CLEANUP_DISPOSE")
    engine = _MigrationEngine(primary, cleanup)
    monkeypatch.setattr(database_migrations, "create_engine", lambda *_a, **_k: engine)
    if helper == "status":
        monkeypatch.setattr(
            database_migrations.ScriptDirectory,
            "from_config",
            lambda _config: SimpleNamespace(walk_revisions=lambda **_kwargs: []),
        )
        operation = database_migrations.get_migration_status
    else:
        monkeypatch.setattr(
            database_migrations,
            "get_migration_status",
            lambda _url: database_migrations.AlembicMigrationStatus(
                False, [], [], [], []
            ),
        )
        operation = database_migrations.validate_migrations

    expected = (
        database_migrations.DatabaseMigrationError
        if isinstance(primary, Exception)
        else type(primary)
    )
    with pytest.raises(expected) as raised:
        operation("sqlite://")

    if isinstance(primary, Exception):
        assert "PRIMARY_CONNECT" in str(raised.value)
    else:
        assert raised.value is primary
    assert engine.dispose_calls == 1


@pytest.mark.parametrize("helper", ["status", "validate"])
def test_each_migration_helper_types_a_standalone_dispose_failure(
    monkeypatch: pytest.MonkeyPatch,
    helper: str,
):
    from core import database_migrations

    connection = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    engine = SimpleNamespace(
        connect=lambda: nullcontext(connection),
        dispose=lambda: (_ for _ in ()).throw(RuntimeError("CLEANUP_DISPOSE")),
    )
    monkeypatch.setattr(database_migrations, "create_engine", lambda *_a, **_k: engine)
    if helper == "status":
        monkeypatch.setattr(
            database_migrations.ScriptDirectory,
            "from_config",
            lambda _config: SimpleNamespace(walk_revisions=lambda **_kwargs: []),
        )
        monkeypatch.setattr(
            database_migrations,
            "inspect",
            lambda _connection: SimpleNamespace(has_table=lambda _table: False),
        )
        operation = database_migrations.get_migration_status
    else:
        monkeypatch.setattr(
            database_migrations,
            "get_migration_status",
            lambda _url: database_migrations.AlembicMigrationStatus(
                False, [], [], [], []
            ),
        )
        operation = database_migrations.validate_migrations

    with pytest.raises(
        database_migrations.DatabaseMigrationError,
        match="Errore chiusura pool",
    ) as raised:
        operation("sqlite://")

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "CLEANUP_DISPOSE"


def test_standalone_migration_dispose_failure_is_typed():
    from core.database_migrations import DatabaseMigrationError, _dispose_migration_engine

    engine = SimpleNamespace(
        dispose=lambda: (_ for _ in ()).throw(RuntimeError("CLEANUP_DISPOSE"))
    )

    with pytest.raises(DatabaseMigrationError, match="Errore chiusura pool") as raised:
        _dispose_migration_engine(engine, context="R39 canary")

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "CLEANUP_DISPOSE"


@pytest.mark.parametrize("process_signal", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_standalone_migration_dispose_preserves_process_control(process_signal):
    from core.database_migrations import _dispose_migration_engine

    signal = process_signal("PROCESS_CONTROL")
    engine = SimpleNamespace(
        dispose=lambda: (_ for _ in ()).throw(signal)
    )

    with pytest.raises(process_signal) as raised:
        _dispose_migration_engine(engine, context="R39 process-control canary")

    assert raised.value is signal


def test_migration_dispose_base_exception_cannot_mask_primary_error():
    from core.database_migrations import _dispose_migration_engine

    primary = RuntimeError("PRIMARY")
    engine = SimpleNamespace(
        dispose=lambda: (_ for _ in ()).throw(KeyboardInterrupt("SECONDARY"))
    )

    with pytest.raises(RuntimeError) as raised:
        try:
            raise primary
        finally:
            _dispose_migration_engine(engine, context="R39 primary canary")

    assert raised.value is primary


def test_storage_retains_engine_after_dispose_failure_and_allows_retry():
    from core.storage.storage_core import StorageCoreMixin

    class Engine:
        calls = 0

        def dispose(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("CLEANUP_DISPOSE")

    storage = object.__new__(StorageCoreMixin)
    storage._lock = threading.Lock()
    storage._engine = Engine()
    storage._Session = object()

    with pytest.raises(RuntimeError, match="CLEANUP_DISPOSE"):
        storage.close()
    assert storage._engine is not None
    assert storage._Session is not None

    storage.close()
    assert storage._engine is None
    assert storage._Session is None


def test_storage_dispose_cannot_mask_active_primary_and_retains_owner():
    from core.storage.storage_core import StorageCoreMixin

    class Engine:
        def dispose(self):
            raise GeneratorExit("CLEANUP_DISPOSE")

    storage = object.__new__(StorageCoreMixin)
    storage._lock = threading.Lock()
    storage._engine = Engine()
    storage._Session = object()
    primary = KeyboardInterrupt("PRIMARY")

    with pytest.raises(KeyboardInterrupt) as raised:
        try:
            raise primary
        finally:
            storage.close()

    assert raised.value is primary
    assert storage._engine is not None
    assert storage._Session is not None


def test_auth_shutdown_closes_admission_but_retains_failed_engine_for_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    from core import auth

    events: list[str] = []

    class Engine:
        dispose_calls = 0

        def dispose(self):
            self.dispose_calls += 1
            events.append(f"dispose:{self.dispose_calls}")
            if self.dispose_calls == 1:
                raise RuntimeError("CLEANUP_DISPOSE")

    class Registry:
        session_factory = SimpleNamespace(kw={"bind": Engine()})

        def close_all(self):
            events.append("close_all")
            return True

    registry = Registry()
    monkeypatch.setattr(auth, "db_session", registry)
    monkeypatch.setattr(auth, "_auth_cleanup_pending", None)

    assert auth.shutdown_auth() is False
    assert auth.db_session is None
    assert auth._auth_cleanup_pending is registry

    assert auth.shutdown_auth() is True
    assert auth.db_session is None
    assert auth._auth_cleanup_pending is None
    assert events == ["close_all", "dispose:1", "close_all", "dispose:2"]


def test_auth_init_fails_closed_until_pending_cleanup_is_retried(
    monkeypatch: pytest.MonkeyPatch,
):
    from core import auth

    class OldEngine:
        calls = 0

        def dispose(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("CLEANUP_DISPOSE")

    class OldRegistry:
        session_factory = SimpleNamespace(kw={"bind": OldEngine()})

        def close_all(self):
            return True

    created: list[object] = []
    new_registry = SimpleNamespace(session_factory=SimpleNamespace(kw={"bind": object()}))
    monkeypatch.setattr(auth, "db_session", OldRegistry())
    monkeypatch.setattr(auth, "_auth_cleanup_pending", None)
    monkeypatch.setattr("core.database_migrations.upgrade_database", lambda _url: created.append("upgrade"))
    monkeypatch.setattr(auth, "create_engine", lambda *_args, **_kwargs: created.append("engine") or object())
    monkeypatch.setattr(auth, "sessionmaker", lambda **_kwargs: object())
    monkeypatch.setattr(auth, "RequestAwareSessionRegistry", lambda _factory: new_registry)

    assert auth.shutdown_auth() is False
    with pytest.raises(RuntimeError, match="Cleanup autenticazione incompleto"):
        auth.init_auth(database_url="sqlite://", allow_sqlite_for_tests=True)
    assert created == []
    assert auth.db_session is None

    assert auth.shutdown_auth() is True
    assert auth.init_auth(database_url="sqlite://", allow_sqlite_for_tests=True) is True
    assert created == ["upgrade", "engine"]
    assert auth.db_session is new_registry


def test_auth_init_and_shutdown_are_serialized_by_one_lifecycle_lock(
    monkeypatch: pytest.MonkeyPatch,
):
    from core import auth

    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    init_entered = threading.Event()
    results: list[object] = []

    class OldEngine:
        def dispose(self):
            return None

    class OldRegistry:
        session_factory = SimpleNamespace(kw={"bind": OldEngine()})

        def close_all(self):
            cleanup_entered.set()
            assert release_cleanup.wait(1)
            return True

    new_registry = SimpleNamespace(session_factory=SimpleNamespace(kw={"bind": object()}))
    monkeypatch.setattr(auth, "db_session", OldRegistry())
    monkeypatch.setattr(auth, "_auth_cleanup_pending", None)
    monkeypatch.setattr("core.database_migrations.upgrade_database", lambda _url: init_entered.set())
    monkeypatch.setattr(auth, "create_engine", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(auth, "sessionmaker", lambda **_kwargs: object())
    monkeypatch.setattr(auth, "RequestAwareSessionRegistry", lambda _factory: new_registry)

    shutdown_thread = threading.Thread(target=lambda: results.append(auth.shutdown_auth()))
    init_thread = threading.Thread(
        target=lambda: results.append(
            auth.init_auth(database_url="sqlite://", allow_sqlite_for_tests=True)
        )
    )
    shutdown_thread.start()
    assert cleanup_entered.wait(1)
    init_thread.start()
    assert not init_entered.wait(0.05)
    release_cleanup.set()
    shutdown_thread.join(1)
    init_thread.join(1)

    assert not shutdown_thread.is_alive()
    assert not init_thread.is_alive()
    assert init_entered.is_set()
    assert results == [True, True]
    assert auth.db_session is new_registry


def test_legacy_association_and_order_get_snapshots_project_group_names(
    monkeypatch: pytest.MonkeyPatch,
):
    from core.library_group_names import (
        MAX_LIBRARY_GROUP_NAME_LENGTH,
        project_library_group_name,
    )
    from emby_libraries.manager import EmbyLibrariesManager
    from emby_libraries import order_snapshots
    from emby_libraries.scan_api_models import (
        LibraryAssociationsResponse,
        LibraryGroupOrderResponse,
    )

    legacy_name = "Cinema\u2028\u202e" + "x" * (MAX_LIBRARY_GROUP_NAME_LENGTH + 20)
    expected = project_library_group_name(legacy_name)

    class Backend:
        def load_library_associations(self):
            return {
                ("server", "library"): legacy_name,
                ("server", "all-control"): "\u202e",
            }

        def load_library_group_order(self):
            return {("movies", legacy_name): 1, ("movies", "\u202e"): 2}

    backend = Backend()
    manager = EmbyLibrariesManager(
        load_config=lambda: ({}, True),
        ensure_db_backend=lambda: backend,
        json_error=lambda message, status: ({"success": False, "message": message}, status),
        storage_error_cls=RuntimeError,
    )
    associations, association_status = manager.build_associations_get_snapshot()
    monkeypatch.setattr(order_snapshots, "_ensure_db_backend", lambda: backend)
    order, order_status = order_snapshots._build_group_order_get_snapshot()

    assert association_status == order_status == 200
    assert associations["associations"][0]["group_name"] == expected
    assert order["order"][0]["group_name"] == expected
    assert len(associations["associations"]) == len(order["order"]) == 1
    assert len(expected) <= MAX_LIBRARY_GROUP_NAME_LENGTH
    assert "\u2028" not in expected and "\u202e" not in expected
    LibraryAssociationsResponse.model_validate(associations)
    LibraryGroupOrderResponse.model_validate(order)
