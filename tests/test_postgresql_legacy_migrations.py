"""PostgreSQL integration coverage for pre-Alembic storage upgrades."""

from __future__ import annotations

import os
import multiprocessing
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import BigInteger, create_engine, inspect, text
from sqlalchemy.exc import DataError
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _latest_state_for_postgresql_test():
    return {
        "server-a": {
            "movies": {
                "items": {
                    "tmdb:1": {
                        "item_id": "movie-1",
                        "title": "Original",
                        "notified": False,
                        "notified_at": "",
                    }
                }
            },
            "series": {"items": {}},
        }
    }


def _latest_publication_payload(marker: str):
    return {
        "movies": [],
        "series": [],
        "errors": [{"server_id": marker, "message": marker}],
    }


def _postgresql_latest_state_worker(database_url, barrier, result_queue, operation):
    from core.storage import DatabaseStorage
    from emby_latest import db_state

    storage = DatabaseStorage({"URL": database_url})
    try:
        repository = db_state.bind(storage)
        barrier.wait(timeout=10)

        def update(current):
            entry = current["server-a"]["movies"]["items"]["tmdb:1"]
            if operation == "title":
                entry["title"] = "Fresh"
            else:
                entry["notified"] = True
                entry["notified_at"] = "2026-08-30T10:00:00+00:00"
            time.sleep(0.25)
            return current

        repository.update_state(update)
        result_queue.put("")
    except Exception as exc:  # pragma: no cover - asserted in parent
        result_queue.put(f"{type(exc).__name__}: {exc}")
    finally:
        if storage._engine is not None:
            storage._engine.dispose()


def _postgresql_migration_worker(database_url, barrier, result_queue):
    from core.database_migrations import upgrade_database

    try:
        barrier.wait(timeout=10)
        upgrade_database(database_url)
        result_queue.put("")
    except Exception as exc:  # pragma: no cover - asserted in parent
        result_queue.put(f"{type(exc).__name__}: {exc}")


@pytest.fixture
def postgresql_schema_url():
    base_url = os.getenv("OCTOHUBS_TEST_POSTGRES_URL")
    if not base_url:
        if os.getenv("OCTOHUBS_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail(
                "OCTOHUBS_TEST_POSTGRES_URL is required by the PostgreSQL release gate"
            )
        pytest.skip("set OCTOHUBS_TEST_POSTGRES_URL to run PostgreSQL migration tests")

    schema = f"octohubs_migration_{uuid4().hex}"
    admin_engine = create_engine(base_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = make_url(base_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    try:
        yield schema_url
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_documented_manage_users_list_works_with_external_postgresql(
    postgresql_schema_url,
):
    environment = os.environ.copy()
    environment["OCTOHUBS_DB_URL"] = postgresql_schema_url
    result = subprocess.run(
        [sys.executable, "scripts/manage_users.py", "list"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_postgresql_concurrent_migrations_are_serialized(postgresql_schema_url):
    from core.database_migrations import validate_migrations

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_postgresql_migration_worker,
            args=(postgresql_schema_url, barrier, result_queue),
        )
        for _index in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
        assert all(not worker.is_alive() for worker in workers)
        assert [result_queue.get(timeout=3) for _worker in workers] == ["", ""]
        assert validate_migrations(postgresql_schema_url)["ok"] is True
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)


def test_postgresql_library_group_name_columns_enforce_canonical_budget(
    postgresql_schema_url,
):
    from core.database_migrations import upgrade_database
    from core.library_group_names import MAX_LIBRARY_GROUP_NAME_LENGTH

    upgrade_database(postgresql_schema_url)
    engine = create_engine(postgresql_schema_url, future=True)
    maximum = "x" * MAX_LIBRARY_GROUP_NAME_LENGTH
    oversized = maximum + "x"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO library_associations "
                    "(server_id, library_id, group_name) "
                    "VALUES ('server', 'library', :group_name)"
                ),
                {"group_name": maximum},
            )
            connection.execute(
                text(
                    "INSERT INTO library_group_order "
                    "(collection_type, group_name, position) "
                    "VALUES ('movies', :group_name, 0)"
                ),
                {"group_name": maximum},
            )

        for statement in (
            "INSERT INTO library_associations "
            "(server_id, library_id, group_name) "
            "VALUES ('other-server', 'other-library', :group_name)",
            "INSERT INTO library_group_order "
            "(collection_type, group_name, position) "
            "VALUES ('tvshows', :group_name, 0)",
        ):
            with pytest.raises(DataError):
                with engine.begin() as connection:
                    connection.execute(text(statement), {"group_name": oversized})
    finally:
        engine.dispose()


def test_postgresql_baseline_contract_excludes_later_revision_objects(
    postgresql_schema_url,
):
    from alembic import command

    from core.database_migrations import alembic_config

    command.upgrade(alembic_config(postgresql_schema_url), "20260829_01")
    engine = create_engine(postgresql_schema_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        workflow_columns = {
            column["name"]
            for column in inspector.get_columns("workflow_executions")
        }
        queue_columns = {
            column["name"]
            for column in inspector.get_columns("emby_probe_queue")
        }
        users_columns = {
            column["name"]
            for column in inspector.get_columns("users")
        }
    finally:
        engine.dispose()

    assert "emby_latest_notification_deliveries" not in tables
    assert "emby_latest_state_document" not in tables
    assert {"active_slot", "heartbeat_at", "owner_id", "stop_requested"}.isdisjoint(
        workflow_columns
    )
    assert {"claim_token", "claimed_at"}.isdisjoint(queue_columns)
    assert "auth_epoch" not in users_columns


def test_schema_validation_rejects_missing_probe_queue_identity_unique(
    postgresql_schema_url,
):
    from core.database_migrations import validate_migrations
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_emby_probe_queue_identity"))

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert any(
        "missing critical index on emby_probe_queue: "
        "(server_id, item_id, scope, media_source_id)" in error
        for error in validation["errors"]
    )
    engine.dispose()


def test_schema_validation_rejects_probe_queue_unique_with_distinct_nulls(
    postgresql_schema_url,
):
    from core.database_migrations import validate_migrations
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_emby_probe_queue_identity"))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_emby_probe_queue_identity "
            "ON emby_probe_queue (server_id, item_id, scope, media_source_id)"
        ))

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert any(
        "requires NULLS NOT DISTINCT" in error
        for error in validation["errors"]
    )
    engine.dispose()


def test_schema_validation_rejects_missing_probe_blacklist_identity_unique(
    postgresql_schema_url,
):
    from core.database_migrations import validate_migrations
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_emby_probe_blacklist_identity"))

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert any(
        "missing critical index on emby_probe_blacklist: "
        "(server_id, item_id, scope, media_source_id)" in error
        for error in validation["errors"]
    )
    engine.dispose()


def test_schema_validation_rejects_probe_blacklist_unique_with_distinct_nulls(
    postgresql_schema_url,
):
    from core.database_migrations import validate_migrations
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.close()
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_emby_probe_blacklist_identity"))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_emby_probe_blacklist_identity "
            "ON emby_probe_blacklist (server_id, item_id, scope, media_source_id)"
        ))

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert any(
        "uq_emby_probe_blacklist_identity requires NULLS NOT DISTINCT" in error
        for error in validation["errors"]
    )
    engine.dispose()


def test_postgresql_latest_reset_waits_for_inflight_state_writer(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage
    from emby_latest import db_state

    writer_storage = DatabaseStorage({"URL": postgresql_schema_url})
    reset_storage = DatabaseStorage({"URL": postgresql_schema_url})
    writer_storage.ensure_ready()
    writer_storage.save_latest_state(_latest_state_for_postgresql_test())
    updater_started = threading.Event()
    release_updater = threading.Event()

    def write() -> None:
        def mutate(current):
            updater_started.set()
            assert release_updater.wait(timeout=5)
            current["server-a"]["movies"]["items"]["tmdb:1"]["title"] = "Fresh"

        db_state.update_state(mutate, db_storage=writer_storage)

    writer = threading.Thread(target=write)
    reset = threading.Thread(
        target=db_state.clear_state,
        kwargs={"db_storage": reset_storage},
    )
    writer.start()
    assert updater_started.wait(timeout=3)
    reset.start()
    time.sleep(0.1)
    assert reset.is_alive()

    release_updater.set()
    writer.join(timeout=5)
    reset.join(timeout=5)

    assert not writer.is_alive()
    assert not reset.is_alive()
    assert reset_storage.load_latest_state() == {}
    writer_storage.close()
    reset_storage.close()


def test_postgresql_transcode_guard_mutations_are_cross_worker_safe(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage
    from emby_runtime.transcode_guard import (
        TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY,
        TRANSCODE_GUARD_SETTINGS_KEY,
        TranscodeGuardService,
    )

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _index in range(2)]
    storages[0].ensure_ready()
    services = [
        TranscodeGuardService(storage_provider=lambda storage=storage: storage)
        for storage in storages
    ]
    services[0].save_settings(
        {
            "enabled": False,
            "rules": [
                {
                    "id": "server-a-monitor",
                    "name": "Server A monitor",
                    "enabled": False,
                    "server_ids": ["server-a"],
                }
            ],
        }
    )
    event_barrier = threading.Barrier(2)

    def record(service, session_id):
        event_barrier.wait(timeout=3)
        service._record_playback_event_row({
            "server_id": "server-a",
            "session_id": session_id,
            "action": "start",
            "event_name": "PlaybackStart",
        })

    event_workers = [
        threading.Thread(target=record, args=(services[0], "session-a")),
        threading.Thread(target=record, args=(services[1], "session-b")),
    ]
    for worker in event_workers:
        worker.start()
    for worker in event_workers:
        worker.join(timeout=5)

    settings_barrier = threading.Barrier(2)

    def save(service, update):
        settings_barrier.wait(timeout=3)
        service.save_settings(update)

    settings_workers = [
        threading.Thread(
            target=save,
            args=(services[0], {"enabled": False, "poll_interval_seconds": 9}),
        ),
        threading.Thread(
            target=save,
            args=(services[1], {"enabled": False, "stream_history_retention_days": 31}),
        ),
    ]
    for worker in settings_workers:
        worker.start()
    for worker in settings_workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in [*event_workers, *settings_workers])
    events = storages[0].get_key_value(TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY)
    assert {row["session_id"] for row in events} == {"session-a", "session-b"}
    settings = storages[0].get_key_value(TRANSCODE_GUARD_SETTINGS_KEY)
    assert settings["poll_interval_seconds"] == 9
    assert settings["stream_history_retention_days"] == 31
    for storage in storages:
        storage.close()


def test_postgresql_latest_state_round_trip_is_lossless(postgresql_schema_url):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    state = {
        "server-a": {
            "history": {
                "movies": {
                    "movie-1": {
                        "mediainfo_complete": True,
                        "mediainfo_source_keys": ["source-a"],
                        "notified_destinations": {"telegram:1": "2026-08-31T10:00:00+00:00"},
                    }
                }
            },
            "movies": {
                "items": {
                    "tmdb:1": {
                        "item_id": "movie-1",
                        "title": "Movie",
                        "media_source_keys": ["source-a"],
                        "mediainfo_complete": True,
                        "mediainfo_source_keys": ["source-a"],
                        "notified_destinations": {"telegram:1": True},
                        "notified_publications": {
                            "publication-a": {
                                "notified": True,
                                "notified_destinations": {"telegram:1": True},
                            }
                        },
                    }
                }
            },
            "series": {"items": {}},
        }
    }

    storage.save_latest_state(state)

    assert storage.load_latest_state() == state
    storage.close()


def test_postgresql_probe_cursor_does_not_skip_after_concurrent_delete(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.add_to_probe_queue(
        [
            {
                "server_id": "green",
                "item_id": f"item-{index}",
                "scope": "libraries",
                "name": f"Item {index}",
            }
            for index in range(1, 4)
        ]
    )

    first_page = storage.get_probe_queue(
        "green",
        scope="libraries",
        limit=2,
        cursor_id=0,
    )
    storage.remove_from_probe_queue("green", "item-1", scope="libraries")
    storage.add_to_probe_queue(
        [{"server_id": "green", "item_id": "item-4", "scope": "libraries"}]
    )
    second_page = storage.get_probe_queue(
        "green",
        scope="libraries",
        limit=2,
        cursor_id=first_page[-1]["id"],
    )

    assert [item["item_id"] for item in first_page] == ["item-1", "item-2"]
    assert [item["item_id"] for item in second_page] == ["item-3", "item-4"]
    storage.close()


def test_postgresql_latest_cache_publication_is_not_merged(postgresql_schema_url):
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(2)]
    storages[0].ensure_ready()
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            prefix = f"writer-{index}"
            payload = {
                "movies": [
                    {
                        "item_type": "movie",
                        "server_id": prefix,
                        "item_id": f"{prefix}-{item_index}",
                        "title": f"Movie {item_index}",
                    }
                    for item_index in range(100)
                ],
                "series": [],
                "errors": [],
            }
            storages[index].save_latest_cache("feed", payload, 100, 100)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert failures == []
    movies = storages[0].load_latest_cache("feed")["payload"]["movies"]
    assert len(movies) == 100
    assert len({movie["server_id"] for movie in movies}) == 1
    for storage in storages:
        storage.close()


def test_postgresql_first_app_settings_writes_are_serialized(postgresql_schema_url):
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(2)]
    storages[0].ensure_ready()
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            storages[index].update_app_settings_section(
                f"SECTION_{index}",
                lambda _current: {"writer": index},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert failures == []
    assert storages[0].load_app_settings() == {
        "SECTION_0": {"writer": 0},
        "SECTION_1": {"writer": 1},
    }
    for storage in storages:
        storage.close()


def test_postgresql_app_settings_seed_merge_preserves_concurrent_section(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    seed = DatabaseStorage({"URL": postgresql_schema_url})
    writer = DatabaseStorage({"URL": postgresql_schema_url})
    seed.ensure_ready()
    seed.save_app_settings({"BASE": {"value": 1}})
    original = dict(seed.load_app_settings() or {})
    writer.update_app_settings_section("CONCURRENT", lambda _value: {"saved": True})
    submitted = {**original, "LEGACY_SEED": {"enabled": True}}

    seed.save_app_settings_changes(original, submitted)

    assert seed.load_app_settings() == {
        "BASE": {"value": 1},
        "CONCURRENT": {"saved": True},
        "LEGACY_SEED": {"enabled": True},
    }
    seed.close()
    writer.close()


def test_postgresql_seed_cannot_replace_a_concurrent_first_section_write(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    seed = DatabaseStorage({"URL": postgresql_schema_url})
    writer = DatabaseStorage({"URL": postgresql_schema_url})
    seed.ensure_ready()
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def seed_defaults():
        try:
            barrier.wait(timeout=5)
            seed.seed_app_settings(
                {"AUTO_TASKS": {"job": {"enabled": False, "interval_minutes": 60}}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def save_user_value():
        try:
            barrier.wait(timeout=5)
            writer.update_app_settings_section(
                "AUTO_TASKS",
                lambda _current: {
                    "job": {"enabled": True, "interval_minutes": 7},
                },
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [
        threading.Thread(target=seed_defaults),
        threading.Thread(target=save_user_value),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert seed.load_app_settings() == {
        "AUTO_TASKS": {"job": {"enabled": True, "interval_minutes": 7}},
    }
    seed.close()
    writer.close()


def test_postgresql_concurrent_request_rule_patches_preserve_both_ids(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(2)]
    storages[0].ensure_ready()
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            request_id = f"request-{index}"
            storages[index].patch_request_rules(
                {request_id: {"enabled": True, "query_terms": [request_id]}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert set(storages[0].load_request_rules()) == {"request-0", "request-1"}
    for storage in storages:
        storage.close()


def test_postgresql_concurrent_first_justwatch_writes_are_upserted(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(8)]
    for storage in storages:
        storage.ensure_ready()
    barrier = threading.Barrier(len(storages))
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            storages[index].save_justwatch_cache(
                "Concurrent Show",
                1,
                2,
                index % 2 == 0,
                [f"provider-{index}"],
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(len(storages))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.connect() as connection:
        count = connection.execute(text(
            "SELECT COUNT(*) FROM justwatch_cache "
            "WHERE show_name='Concurrent Show' AND season=1 AND episode=2"
        )).scalar_one()
    engine.dispose()
    assert count == 1
    for storage in storages:
        storage.close()


def test_postgresql_user_backup_retention_is_serialized(postgresql_schema_url):
    from core.storage import DatabaseStorage
    from core.storage.storage_models import EmbyUserBackup

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(4)]
    for storage in storages:
        storage.ensure_ready()
    for index in range(29):
        storages[0].create_user_backup(
            "green", "user-a", "User A", "settings", {"revision": index}
        )
    barrier = threading.Barrier(len(storages))
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            storages[index].create_user_backup(
                "green", "user-a", "User A", "settings", {"revision": 29 + index}
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(len(storages))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    session = storages[0]._get_session()
    try:
        count = session.query(EmbyUserBackup).filter_by(
            server_id="green",
            user_id="user-a",
            backup_type="settings",
        ).count()
    finally:
        session.close()
    assert count == storages[0]._USER_BACKUP_MAX_PER_TYPE
    for storage in storages:
        storage.close()


def test_postgresql_recent_probe_checkpoint_is_one_atomic_row(postgresql_schema_url):
    from datetime import datetime, timezone
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _ in range(2)]
    storages[0].ensure_ready()
    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            storages[index].save_recent_scan_timestamp(
                "server-a",
                datetime(2026, 8, 30 + index, tzinfo=timezone.utc),
                "library-a",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert failures == []
    with storages[0]._engine.connect() as connection:
        count = connection.execute(
            text(
                "SELECT COUNT(*) FROM emby_probe_recent_scans "
                "WHERE server_id='server-a' AND library_id='library-a'"
            )
        ).scalar_one()
    assert count == 1
    for storage in storages:
        storage.close()


def test_postgresql_schema_validation_detects_drift(postgresql_schema_url):
    from core.database_migrations import upgrade_database, validate_migrations

    upgrade_database(postgresql_schema_url)
    engine = create_engine(postgresql_schema_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE emby_probe_history"))
    engine.dispose()

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert "missing table: emby_probe_history" in validation["errors"]


def test_postgresql_schema_validation_rejects_missing_username_uniqueness(
    postgresql_schema_url,
):
    from core.database_migrations import upgrade_database, validate_migrations

    upgrade_database(postgresql_schema_url)
    engine = create_engine(postgresql_schema_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_users_username"))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX ix_users_username "
                    "ON users (username) WHERE is_active"
                )
            )
    finally:
        engine.dispose()

    validation = validate_migrations(postgresql_schema_url)

    assert validation["ok"] is False
    assert any(
        "missing unique constraint on users: (username)" in error
        for error in validation["errors"]
    )


def test_postgresql_key_value_transform_serializes_first_write(postgresql_schema_url):
    from core.storage import DatabaseStorage

    first_storage = DatabaseStorage({"URL": postgresql_schema_url})
    second_storage = DatabaseStorage({"URL": postgresql_schema_url})
    first_storage.ensure_ready()
    second_storage.ensure_ready()
    barrier = threading.Barrier(2)
    errors = []

    def add_value(storage, name):
        try:
            barrier.wait(timeout=3)

            def update(current):
                values = dict(current) if isinstance(current, dict) else {}
                values[name] = True
                return values

            storage.update_key_value("operation-race", update)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=add_value, args=(first_storage, "first"))
    second = threading.Thread(target=add_value, args=(second_storage, "second"))
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert first_storage.get_key_value("operation-race") == {
        "first": True,
        "second": True,
    }


def test_postgresql_user_group_mutations_keep_exactly_one_leader(postgresql_schema_url):
    from core.storage import DatabaseStorage

    first_storage = DatabaseStorage({"URL": postgresql_schema_url})
    second_storage = DatabaseStorage({"URL": postgresql_schema_url})
    members = [
        {
            "server_id": "server-a",
            "user_id": "user-a",
            "username": "Viewer",
            "group_id": "shared-group",
        },
        {
            "server_id": "server-b",
            "user_id": "user-b",
            "username": "Viewer",
            "group_id": "shared-group",
        },
    ]
    first_storage.mutate_user_links(
        upserts=members,
        preferred_leaders={"shared-group": ("server-a", "user-a")},
    )
    barrier = threading.Barrier(2)
    errors = []

    def choose_leader(storage, identity):
        try:
            barrier.wait(timeout=3)
            storage.mutate_user_links(
                preferred_leaders={"shared-group": identity},
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(
        target=choose_leader,
        args=(first_storage, ("server-a", "user-a")),
    )
    second = threading.Thread(
        target=choose_leader,
        args=(second_storage, ("server-b", "user-b")),
    )
    try:
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        links = first_storage.get_user_links(group_id="shared-group")
        assert len(links) == 2
        assert sum(bool(link["is_leader"]) for link in links) == 1
    finally:
        first_storage.close()
        second_storage.close()


def test_postgresql_active_admin_mutations_are_serialized(postgresql_schema_url):
    from core import auth

    previous_session = auth.db_session
    auth.init_auth(database_url=postgresql_schema_url)
    try:
        assert auth.create_user("admin-a", "password-a", role="admin") is not None
        assert auth.create_user("admin-b", "password-b", role="admin") is not None
        barrier = threading.Barrier(2)
        results = []

        def demote(username):
            try:
                account = auth.get_user_by_username(username)
                assert account is not None
                barrier.wait(timeout=3)
                results.append(auth.update_user_details(account, role="viewer"))
            finally:
                auth.db_session.remove()

        first = threading.Thread(target=demote, args=("admin-a",))
        second = threading.Thread(target=demote, args=("admin-b",))
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        assert not first.is_alive() and not second.is_alive()
        assert sorted(results) == [False, True]
        assert auth.db_session.query(auth.User).filter(
            auth.User.is_active.is_(True),
            auth.User.is_admin.is_(True),
        ).count() == 1
    finally:
        auth.shutdown_auth()
        auth.db_session = previous_session


def test_postgresql_latest_state_updates_are_serialized_across_processes(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.save_latest_state(_latest_state_for_postgresql_test())

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_postgresql_latest_state_worker,
            args=(postgresql_schema_url, barrier, result_queue, operation),
        )
        for operation in ("title", "notification")
    ]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
        assert all(not worker.is_alive() for worker in workers)
        assert [result_queue.get(timeout=3) for _worker in workers] == ["", ""]

        entry = storage.load_latest_state()["server-a"]["movies"]["items"]["tmdb:1"]
        assert entry["title"] == "Fresh"
        assert entry["notified"] is True
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=3)
        if storage._engine is not None:
            storage._engine.dispose()


def test_postgresql_probe_blacklist_retry_increment_is_atomic(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage

    storages = [DatabaseStorage({"URL": postgresql_schema_url}) for _index in range(2)]
    storages[0].ensure_ready()
    assert storages[0].update_probe_blacklist(
        "server-a",
        "item-a",
        "Item",
        "Initial failure",
        increment_retry=True,
        scope="libraries",
    ) == 1
    barrier = threading.Barrier(2)
    results: list[int] = []

    def increment(storage, reason):
        barrier.wait(timeout=3)
        results.append(storage.update_probe_blacklist(
            "server-a",
            "item-a",
            "Item",
            reason,
            increment_retry=True,
            scope="libraries",
        ))

    workers = [
        threading.Thread(target=increment, args=(storages[0], "Failure A")),
        threading.Thread(target=increment, args=(storages[1], "Failure B")),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == [2, 3]
    row = storages[0].get_probe_blacklist("server-a", scope="libraries")[0]
    assert row["retry_count"] == 3
    for storage in storages:
        storage.close()


def _create_legacy_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE emby_collection_definitions (
                    collection_id VARCHAR(50) PRIMARY KEY,
                    data JSON NOT NULL,
                    updated_at TIMESTAMP
                )
            """))
            connection.execute(text("""
                INSERT INTO emby_collection_definitions
                    (collection_id, data, updated_at)
                VALUES ('legacy-collection', '{"id":"legacy-collection"}'::json, NOW())
            """))
            connection.execute(text("""
                CREATE TABLE emby_probe_blacklist (
                    server_id VARCHAR(36) NOT NULL,
                    item_id VARCHAR(36) NOT NULL,
                    item_name VARCHAR(255) NOT NULL,
                    reason VARCHAR(500) NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    failed_at TIMESTAMP,
                    PRIMARY KEY (server_id, item_id)
                )
            """))
            connection.execute(text("""
                INSERT INTO emby_probe_blacklist
                    (server_id, item_id, item_name, reason, retry_count, failed_at)
                VALUES ('green', 'legacy-item', 'Legacy item', 'Legacy error', 1, NOW())
            """))
            connection.execute(text("""
                CREATE TABLE emby_latest_cache_changes (
                    id SERIAL PRIMARY KEY,
                    size INTEGER
                )
            """))
            connection.execute(text("""
                CREATE TABLE emby_latest_state_series_changes (
                    id SERIAL PRIMARY KEY,
                    size INTEGER
                )
            """))
            connection.execute(text("""
                CREATE TABLE justwatch_cache (
                    id SERIAL PRIMARY KEY,
                    show_name VARCHAR(500) NOT NULL,
                    season INTEGER NOT NULL,
                    episode INTEGER NOT NULL,
                    is_available BOOLEAN NOT NULL DEFAULT FALSE,
                    providers JSON,
                    last_checked TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            connection.execute(text("""
                INSERT INTO justwatch_cache
                    (show_name, season, episode, is_available)
                VALUES ('Legacy show', 1, 2, TRUE)
            """))
            connection.execute(text("""
                CREATE TABLE key_value_store (
                    key VARCHAR(255) PRIMARY KEY,
                    value JSON NOT NULL,
                    updated_at TIMESTAMP
                )
            """))
            connection.execute(text("""
                INSERT INTO key_value_store (key, value, updated_at)
                VALUES ('legacy-key', '{"visible": true}'::json, NOW())
            """))
            connection.execute(text("""
                CREATE TABLE request_overview (
                    id INTEGER PRIMARY KEY,
                    payload JSON NOT NULL,
                    updated_at TIMESTAMP
                )
            """))
            connection.execute(text("""
                INSERT INTO request_overview (id, payload, updated_at)
                VALUES (7, '{"items":[7]}'::json, NOW())
            """))
    finally:
        engine.dispose()


def test_postgresql_legacy_upgrade_matches_runtime_contract(postgresql_schema_url):
    from alembic import command

    from core.database_migrations import (
        alembic_config,
        upgrade_database,
        validate_migrations,
    )
    from core.storage import DatabaseStorage

    _create_legacy_schema(postgresql_schema_url)
    command.upgrade(alembic_config(postgresql_schema_url), "20260829_03")

    result = upgrade_database(postgresql_schema_url)

    assert result["pending"] == []
    assert result["applied"] == [
        "20260829_04",
        "20260829_05",
        "20260830_06",
        "20260830_07",
        "20260831_08",
        "20260831_09",
        "20260831_10",
        "20260831_11",
        "20260831_12",
        "20260901_13",
        "20260901_14",
        "20260902_15",
        "20260902_16",
        "20260902_17",
        "20260905_18",
        "20260906_19",
        "20260906_20",
        "20260908_21",
        "20260908_22",
    ]
    assert validate_migrations(postgresql_schema_url)["ok"] is True

    engine = create_engine(postgresql_schema_url, future=True)
    try:
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("emby_collection_definitions")[
            "constrained_columns"
        ] == ["id"]
        definition_columns = {
            column["name"]: column
            for column in inspector.get_columns("emby_collection_definitions")
        }
        assert definition_columns["id"]["nullable"] is False
        assert definition_columns["collection_id"]["nullable"] is True

        assert inspector.get_pk_constraint("emby_probe_blacklist")[
            "constrained_columns"
        ] == ["id"]
        blacklist_columns = {
            column["name"]: column
            for column in inspector.get_columns("emby_probe_blacklist")
        }
        assert blacklist_columns["id"]["default"] is not None
        blacklist_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("emby_probe_blacklist")
        }
        identity_index = blacklist_indexes["uq_emby_probe_blacklist_identity"]
        assert identity_index["unique"] is True
        assert identity_index["column_names"] == [
            "server_id",
            "item_id",
            "scope",
            "media_source_id",
        ]
        assert identity_index["dialect_options"]["postgresql_nulls_not_distinct"] is True

        assert inspector.get_pk_constraint("justwatch_cache")[
            "constrained_columns"
        ] == ["show_name", "season", "episode"]
        columns = {
            column["name"]: column
            for column in inspector.get_columns("emby_latest_cache_changes")
        }
        assert isinstance(columns["size"]["type"], BigInteger)
        assert not inspector.has_table("emby_latest_state_series_changes")

        with engine.begin() as connection:
            legacy_key = connection.execute(
                text("SELECT value FROM key_value WHERE key='legacy-key'")
            ).scalar_one()
            request_cache = connection.execute(
                text("SELECT payload FROM request_cache WHERE id=1")
            ).scalar_one()
            connection.execute(
                text("INSERT INTO emby_latest_cache_changes (size) VALUES (3000000000)")
            )
        assert legacy_key == {"visible": True}
        assert request_cache == {"items": [7]}
    finally:
        engine.dispose()

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    try:
        storage.save_emby_collection_definition(
            {"id": "new-collection", "name": "New collection"}
        )
        assert storage.get_emby_collection_definition("new-collection") == {
            "id": "new-collection",
            "name": "New collection",
        }
        retry_count = storage.update_probe_blacklist(
            "blue",
            "new-item",
            "New item",
            "Test error",
        )
        assert retry_count == 1
        assert storage.update_probe_blacklist(
            "blue", "composite-item", "Composite", "Source A", "src-a", scope="libraries"
        ) == 1
        assert storage.update_probe_blacklist(
            "blue", "composite-item", "Composite", "Source B", "src-b", scope="libraries"
        ) == 1
        assert storage.update_probe_blacklist(
            "blue", "composite-item", "Composite", "Recent A", "src-a", scope="recent"
        ) == 1
        storage.remove_from_probe_blacklist(
            "blue", "composite-item", "src-a", scope="libraries"
        )
        remaining_identities = {
            (entry["scope"], entry["media_source_id"])
            for entry in storage.get_probe_blacklist("blue")
            if entry["item_id"] == "composite-item"
        }
        assert remaining_identities == {("libraries", "src-b"), ("recent", "src-a")}
        assert storage.get_key_value("legacy-key") == {"visible": True}
        assert storage.load_request_overview()[0] == {"items": [7]}
    finally:
        if storage._engine is not None:
            storage._engine.dispose()


def test_postgresql_legacy_upgrade_refuses_ambiguous_primary_key_data(
    postgresql_schema_url,
):
    from core.database_migrations import (
        DatabaseMigrationError,
        get_migration_status,
        upgrade_database,
    )

    engine = create_engine(postgresql_schema_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE justwatch_cache (
                    id SERIAL PRIMARY KEY,
                    show_name VARCHAR(500) NOT NULL,
                    season INTEGER NOT NULL,
                    episode INTEGER NOT NULL,
                    is_available BOOLEAN NOT NULL DEFAULT FALSE,
                    providers JSON,
                    last_checked TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            connection.execute(text("""
                INSERT INTO justwatch_cache
                    (show_name, season, episode, is_available)
                VALUES
                    ('Duplicate show', 1, 1, TRUE),
                    ('Duplicate show', 1, 1, FALSE)
            """))
    finally:
        engine.dispose()

    with pytest.raises(DatabaseMigrationError, match="duplicate rows"):
        upgrade_database(postgresql_schema_url)

    status = get_migration_status(postgresql_schema_url)
    assert "20260829_04" not in status.applied
    assert "20260829_04" in status.pending
    assert "20260829_05" in status.pending
    assert "20260830_06" in status.pending
    assert "20260830_07" in status.pending


def test_postgresql_probe_blacklist_identity_migration_merges_existing_duplicates(
    postgresql_schema_url,
):
    from alembic import command

    from core.database_migrations import alembic_config, upgrade_database

    _create_legacy_schema(postgresql_schema_url)
    command.upgrade(alembic_config(postgresql_schema_url), "20260829_04")

    engine = create_engine(postgresql_schema_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO emby_probe_blacklist (
                        server_id, item_id, scope, media_source_id,
                        item_name, reason, retry_count, failed_at
                    ) VALUES
                        ('green', 'duplicate-item', 'libraries', NULL,
                         'Old title', 'Old error', 5, '2026-08-28 10:00:00'),
                        ('green', 'duplicate-item', 'libraries', NULL,
                         'New title', 'New error', 2, '2026-08-29 10:00:00')
                    """
                )
            )

        result = upgrade_database(postgresql_schema_url)
        assert result["applied"] == [
            "20260829_05",
            "20260830_06",
            "20260830_07",
            "20260831_08",
            "20260831_09",
            "20260831_10",
            "20260831_11",
            "20260831_12",
            "20260901_13",
            "20260901_14",
            "20260902_15",
            "20260902_16",
            "20260902_17",
            "20260905_18",
            "20260906_19",
            "20260906_20",
            "20260908_21",
            "20260908_22",
        ]

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT item_name, reason, retry_count
                    FROM emby_probe_blacklist
                    WHERE server_id='green' AND item_id='duplicate-item'
                    """
                )
            ).all()
        assert rows == [("New title", "New error", 5)]
    finally:
        engine.dispose()


def test_postgresql_latest_zero_server_refresh_publishes_one_atomic_snapshot(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage
    from emby_latest.manager import EmbyLatestManager

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    storage.publish_latest_refresh(_latest_publication_payload("stale"), 5, 2)
    manager = EmbyLatestManager(
        {"DATABASE": {"ENABLED": True}, "EMBY": {"SERVERS": []}},
        storage,
    )

    payload, error = manager.refresh_full(10, 4, enrich=False)

    assert error is None
    assert payload == {"movies": [], "series": [], "errors": []}
    batch = storage.load_latest_cache("batch")
    feed = storage.load_latest_cache("feed")
    assert batch["payload"] == feed["payload"] == payload
    assert batch["params"] == feed["params"] == {
        "limit": 10,
        "per_server_limit": 4,
    }
    assert batch["updated_at"] == feed["updated_at"]


@pytest.mark.parametrize("failure_stage", ["feed", "state"])
def test_postgresql_latest_publication_rolls_back_all_writers(
    postgresql_schema_url,
    failure_stage,
):
    from core.storage import DatabaseStorage

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    old_payload = _latest_publication_payload("old")
    old_state = _latest_state_for_postgresql_test()
    old_state["server-a"]["movies"]["items"]["tmdb:1"].update(
        {
            "notified": True,
            "notified_at": "2026-09-03T10:00:00+00:00",
        }
    )
    storage.publish_latest_refresh(old_payload, 5, 2, latest_state=old_state)

    if failure_stage == "feed":
        original_cache_writer = storage._replace_latest_cache_in_session

        def fail_feed(session, kind, *args, **kwargs):
            if kind == "feed":
                raise RuntimeError("feed writer failed")
            return original_cache_writer(session, kind, *args, **kwargs)

        failure = patch.object(
            storage,
            "_replace_latest_cache_in_session",
            side_effect=fail_feed,
        )
    else:
        failure = patch.object(
            storage,
            "_replace_latest_state_in_session",
            side_effect=RuntimeError("state writer failed"),
        )

    new_state = _latest_state_for_postgresql_test()
    new_state["server-a"]["movies"]["items"]["tmdb:1"]["title"] = "Fresh"
    with failure, pytest.raises(RuntimeError, match="writer failed"):
        storage.publish_latest_refresh(
            _latest_publication_payload("new"),
            10,
            4,
            latest_state=new_state,
        )

    assert storage.load_latest_cache("batch")["payload"] == old_payload
    assert storage.load_latest_cache("feed")["payload"] == old_payload
    assert storage.load_latest_state() == old_state


def test_postgresql_latest_atomic_publication_preserves_notification_checkpoint(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage
    from emby_latest import db_state

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    storage.ensure_ready()
    repository = db_state.bind(storage)
    collector_snapshot = _latest_state_for_postgresql_test()
    storage.publish_latest_refresh(
        _latest_publication_payload("old"),
        5,
        2,
        latest_state=collector_snapshot,
    )

    def mark_notified(current):
        current["server-a"]["movies"]["items"]["tmdb:1"].update(
            {
                "notified": True,
                "notified_at": "2026-09-03T10:00:00+00:00",
            }
        )
        return current

    repository.update_state(mark_notified)
    collector_snapshot["server-a"]["movies"]["items"]["tmdb:1"]["title"] = "Fresh"

    storage.publish_latest_refresh(
        _latest_publication_payload("new"),
        10,
        4,
        latest_state=collector_snapshot,
    )

    entry = storage.load_latest_state()["server-a"]["movies"]["items"]["tmdb:1"]
    assert entry["title"] == "Fresh"
    assert entry["notified"] is True
    assert entry["notified_at"] == "2026-09-03T10:00:00+00:00"


def test_postgresql_app_settings_stale_edit_cannot_resurrect_deleted_key(
    postgresql_schema_url,
):
    from core.storage import DatabaseStorage, StorageError
    from emby_users.password_crypto import PasswordCipher

    cipher = PasswordCipher("postgres-settings-secret-with-enough-entropy")
    seed = DatabaseStorage({"URL": postgresql_schema_url}, app_settings_cipher=cipher)
    deleter = DatabaseStorage({"URL": postgresql_schema_url}, app_settings_cipher=cipher)
    stale_writer = DatabaseStorage(
        {"URL": postgresql_schema_url},
        app_settings_cipher=cipher,
    )
    try:
        seed.ensure_ready()
        seed.save_app_settings(
            {"KEEP": 1, "TRAKT": {"ACCESS_TOKEN": "old-token"}}
        )
        deletion = deleter.load_app_settings()
        stale_edit = stale_writer.load_app_settings()
        assert deletion is not None and stale_edit is not None

        del deletion["TRAKT"]
        deleter.save_app_settings(deletion)
        stale_edit["TRAKT"]["ACCESS_TOKEN"] = "new-token"

        with pytest.raises(StorageError, match="Conflitto"):
            stale_writer.save_app_settings(stale_edit)
        assert seed.load_app_settings() == {"KEEP": 1}
    finally:
        for storage in (seed, deleter, stale_writer):
            storage.close()


def test_postgresql_app_settings_plaintext_migration_is_atomic_and_idempotent(
    postgresql_schema_url,
):
    import json

    from core.storage import AppSettings, DatabaseStorage
    from emby_users.password_crypto import PasswordCipher

    cipher = PasswordCipher("postgres-migration-secret-with-enough-entropy")
    storage = DatabaseStorage(
        {"URL": postgresql_schema_url},
        app_settings_cipher=cipher,
    )
    try:
        storage.ensure_ready()
        legacy = {
            "JELLYSEERR_API_KEY": "postgres-api-canary",
            "EMBY": {
                "SERVERS": [
                    {"id": "green", "api_key": "postgres-emby-canary"},
                ]
            },
            "TELEGRAM": {"BOTS": [{"token": "postgres-bot-canary"}]},
        }
        session = storage._get_session()
        session.add(AppSettings(id=1, data=legacy))
        session.commit()
        session.close()

        assert storage.load_app_settings() == legacy
        session = storage._get_session()
        first_envelope = session.get(AppSettings, 1).data
        session.close()
        serialized = json.dumps(first_envelope, sort_keys=True)
        assert "postgres-api-canary" not in serialized
        assert "postgres-emby-canary" not in serialized
        assert "postgres-bot-canary" not in serialized

        assert storage.load_app_settings() == legacy
        session = storage._get_session()
        assert session.get(AppSettings, 1).data == first_envelope
        session.close()
    finally:
        storage.close()


def test_postgresql_probe_retry_preserves_diagnostics_for_claimed_duplicate(
    postgresql_schema_url,
):
    from datetime import datetime, timezone

    from core.storage import (
        DatabaseStorage,
        EmbyProbeBlacklist,
        EmbyProbeHistory,
        EmbyProbeQueue,
        StorageError,
    )

    storage = DatabaseStorage({"URL": postgresql_schema_url})
    try:
        storage.ensure_ready()
        session = storage._get_session()
        try:
            session.add(
                EmbyProbeQueue(
                    server_id="r35-server",
                    item_id="r35-movie",
                    scope="libraries",
                    media_source_id="r35-source",
                    name="Movie",
                    media_type="Movie",
                    claim_token="active-claim",
                    claimed_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                EmbyProbeBlacklist(
                    server_id="r35-server",
                    item_id="r35-movie",
                    scope="libraries",
                    media_source_id="r35-source",
                    item_name="Movie",
                    retry_count=3,
                )
            )
            session.add(
                EmbyProbeHistory(
                    server_id="r35-server",
                    item_id="r35-movie",
                    scope="libraries",
                    media_source_id="r35-source",
                    name="Movie",
                    status="error",
                )
            )
            session.commit()
        finally:
            session.close()

        item = {
            "server_id": "r35-server",
            "item_id": "r35-movie",
            "scope": "libraries",
            "media_source_id": "r35-source",
            "name": "Movie",
            "media_type": "Movie",
        }
        with pytest.raises(StorageError, match="Nessuna sorgente"):
            storage.retry_probe_items(
                [item],
                server_id="r35-server",
                item_id="r35-movie",
                media_source_id="r35-source",
                scope="libraries",
            )

        session = storage._get_session()
        try:
            assert session.query(EmbyProbeQueue).count() == 1
            assert session.query(EmbyProbeBlacklist).count() == 1
            assert session.query(EmbyProbeHistory).count() == 1
            assert session.query(EmbyProbeQueue).one().claim_token == "active-claim"
        finally:
            session.close()
    finally:
        storage.close()


def test_postgresql_composed_identifier_widths_accept_canonical_maxima(
    postgresql_schema_url,
):
    """Exercise every revision-22 width against PostgreSQL's real indexes."""
    from core.database_migrations import upgrade_database
    from core.storage.field_limits import (
        EMBY_USER_LINK_KEY_MAX_LENGTH,
        JUSTWATCH_CACHE_KEY_MAX_LENGTH,
        KEY_VALUE_KEY_MAX_LENGTH,
        TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
    )

    upgrade_database(postgresql_schema_url)
    engine = create_engine(postgresql_schema_url, future=True)
    try:
        inspector = inspect(engine)
        expected = {
            ("key_value", "key"): KEY_VALUE_KEY_MAX_LENGTH,
            (
                "emby_latest_notification_deliveries",
                "destination_key",
            ): TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
            ("emby_user_links", "link_key"): EMBY_USER_LINK_KEY_MAX_LENGTH,
            ("justwatch_cache", "show_name"): JUSTWATCH_CACHE_KEY_MAX_LENGTH,
        }
        for (table_name, column_name), maximum in expected.items():
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            assert columns[column_name]["type"].length == maximum

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO key_value (key, value) "
                    "VALUES (:key, '{}'::json)"
                ),
                {"key": "😀" * KEY_VALUE_KEY_MAX_LENGTH},
            )
            connection.execute(
                text(
                    "INSERT INTO emby_user_links "
                    "(server_id, user_id, group_id, username, link_key) "
                    "VALUES ('server', 'user', 'group', 'User', :link_key)"
                ),
                {"link_key": "a" * EMBY_USER_LINK_KEY_MAX_LENGTH},
            )
            connection.execute(
                text(
                    "INSERT INTO emby_latest_notification_deliveries "
                    "(delivery_key, server_id, publication_key, destination_key, "
                    "status, claim_token, claimed_at, created_at, updated_at) "
                    "VALUES ('delivery', 'server', 'publication', :destination, "
                    "'claimed', 'token', NOW(), NOW(), NOW())"
                ),
                {
                    "destination": "😀" * TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO justwatch_cache "
                    "(show_name, season, episode, is_available, last_checked) "
                    "VALUES (:show_name, 1, 1, FALSE, NOW())"
                ),
                {"show_name": "😀" * JUSTWATCH_CACHE_KEY_MAX_LENGTH},
            )

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM key_value")).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM emby_user_links")).scalar_one() == 1
            assert connection.execute(
                text("SELECT COUNT(*) FROM emby_latest_notification_deliveries")
            ).scalar_one() == 1
            assert connection.execute(text("SELECT COUNT(*) FROM justwatch_cache")).scalar_one() == 1
    finally:
        engine.dispose()
