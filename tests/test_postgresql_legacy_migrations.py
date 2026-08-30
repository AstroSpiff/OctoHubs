"""PostgreSQL integration coverage for pre-Alembic storage upgrades."""

from __future__ import annotations

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import BigInteger, create_engine, inspect, text
from sqlalchemy.engine import make_url


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
    assert result["applied"] == ["20260829_04", "20260829_05", "20260830_06"]
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
        for table_name in (
            "emby_latest_cache_changes",
            "emby_latest_state_series_changes",
        ):
            columns = {
                column["name"]: column for column in inspector.get_columns(table_name)
            }
            assert isinstance(columns["size"]["type"], BigInteger)

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
            connection.execute(
                text(
                    "INSERT INTO emby_latest_state_series_changes (size) "
                    "VALUES (3000000000)"
                )
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
            connection.execute(text("DROP INDEX uq_emby_probe_blacklist_identity"))
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
        assert result["applied"] == ["20260829_05", "20260830_06"]

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
