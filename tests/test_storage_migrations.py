"""Tests for the unified Alembic database lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text


_MIGRATED_IDENTIFIER_LENGTHS = {
    ("emby_user_links", "server_id"): (36, 128),
    ("emby_user_links", "user_id"): (36, 128),
    ("emby_user_backups", "server_id"): (36, 128),
    ("emby_user_backups", "user_id"): (36, 128),
    ("emby_user_creation_journal", "server_id"): (36, 128),
    ("emby_icon_bindings", "target_id"): (255, 257),
    ("emby_group_passwords", "group_id"): (255, 266),
    ("library_associations", "server_id"): (36, 128),
    ("library_associations", "library_id"): (36, 128),
    ("emby_latest_cache_items", "item_id"): (36, 128),
    ("emby_latest_cache_items", "library_id"): (36, 128),
    ("emby_latest_cache_changes", "media_source_id"): (100, 128),
    ("emby_probe_blacklist", "item_id"): (36, 128),
    ("emby_probe_blacklist", "library_id"): (36, 128),
    ("emby_probe_blacklist", "media_source_id"): (36, 128),
    ("emby_probe_queue", "item_id"): (36, 128),
    ("emby_probe_queue", "library_id"): (36, 128),
    ("emby_probe_queue", "media_source_id"): (36, 128),
    ("emby_probe_history", "item_id"): (36, 128),
    ("emby_probe_history", "media_source_id"): (36, 128),
    ("emby_probe_recent_scans", "library_id"): (36, 128),
}


def _assert_migrated_identifier_lengths(engine, *, upgraded: bool) -> None:
    schema = inspect(engine)
    for (table_name, column_name), lengths in _MIGRATED_IDENTIFIER_LENGTHS.items():
        columns = {
            column["name"]: column for column in schema.get_columns(table_name)
        }
        assert columns[column_name]["type"].length == lengths[int(upgraded)]


def _create_sqlite_remote_identifier_tables(engine) -> None:
    """Bootstrap storage-only tables absent from the SQLite migration baseline."""
    definitions = {
        "emby_latest_cache_items": "item_id VARCHAR(128), library_id VARCHAR(128)",
        "emby_latest_cache_changes": "media_source_id VARCHAR(128)",
        "emby_probe_blacklist": (
            "item_id VARCHAR(128), library_id VARCHAR(128), media_source_id VARCHAR(128)"
        ),
        "emby_probe_queue": (
            "item_id VARCHAR(128), library_id VARCHAR(128), media_source_id VARCHAR(128)"
        ),
        "emby_probe_history": "item_id VARCHAR(128), media_source_id VARCHAR(128)",
        "emby_probe_recent_scans": "library_id VARCHAR(128)",
    }
    with engine.begin() as connection:
        for table_name, columns in definitions.items():
            connection.execute(
                text(
                    f'CREATE TABLE IF NOT EXISTS "{table_name}" '
                    f'(id INTEGER PRIMARY KEY, {columns})'
                )
            )


def test_postgresql_version_floor_is_enforced_before_migrations():
    from core.database_migrations import DatabaseMigrationError, ensure_supported_database

    class _Result:
        def __init__(self, version):
            self.version = version

        def scalar_one(self):
            return self.version

    class _Connection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def __init__(self, version):
            self.version = version

        def execute(self, _statement):
            return _Result(self.version)

    with pytest.raises(DatabaseMigrationError, match="PostgreSQL 16"):
        ensure_supported_database(_Connection(150_999))

    ensure_supported_database(_Connection(160_000))


def test_alembic_config_preserves_percent_encoded_database_urls():
    from core.database_migrations import alembic_config

    database_url = "postgresql://user:p%40ss@localhost/db?options=-csearch_path%3Dlegacy"

    assert alembic_config(database_url).get_main_option("sqlalchemy.url") == database_url


def test_identifier_downgrade_refuses_to_truncate_new_values(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config, upgrade_database
    from core.emby_identifiers import EMBY_IDENTIFIER_MAX_LENGTH
    from core.storage.storage_models import (
        EmbyIconBinding,
        EmbyIconProfile,
        EmbyGroupPassword,
        EmbyUserBackup,
        EmbyUserLink,
        LibraryAssociation,
    )

    database_url = f"sqlite:///{tmp_path / 'identifier-downgrade.db'}"
    upgrade_database(database_url)
    target_id = f"{'s' * EMBY_IDENTIFIER_MAX_LENGTH}:{'u' * EMBY_IDENTIFIER_MAX_LENGTH}"
    engine = create_engine(database_url, future=True)
    try:
        for table in (
            EmbyUserLink,
            EmbyUserBackup,
            EmbyIconProfile,
            EmbyIconBinding,
            EmbyGroupPassword,
            LibraryAssociation,
        ):
            table.__table__.create(engine, checkfirst=True)
        _create_sqlite_remote_identifier_tables(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO emby_icon_profiles "
                    "(id, label, is_group_profile) VALUES ('profile', 'Profile', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO emby_icon_bindings "
                    "(target_type, target_id, profile_id) "
                    "VALUES ('user', :target_id, 'profile')"
                ),
                {"target_id": target_id},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade.*target_id"):
            command.downgrade(alembic_config(database_url), "20260906_20")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT target_id FROM emby_icon_bindings")
            ).scalar_one() == target_id
        inspector = inspect(engine)
        binding_columns = {
            column["name"]: column for column in inspector.get_columns("emby_icon_bindings")
        }
        journal_columns = {
            column["name"]: column
            for column in inspector.get_columns("emby_user_creation_journal")
        }
        assert binding_columns["target_id"]["type"].length == 257
        assert journal_columns["server_id"]["type"].length == 128
        _assert_migrated_identifier_lengths(engine, upgraded=True)
    finally:
        engine.dispose()


def test_identifier_downgrade_refuses_oversize_synthetic_group_atomically(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config, upgrade_database
    from core.storage.storage_models import EmbyGroupPassword

    database_url = f"sqlite:///{tmp_path / 'synthetic-group-downgrade.db'}"
    upgrade_database(database_url)
    engine = create_engine(database_url, future=True)
    synthetic_id = f"unlinked_{'s' * 128}_{'u' * 128}"
    try:
        EmbyGroupPassword.__table__.create(engine, checkfirst=True)
        _create_sqlite_remote_identifier_tables(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO emby_group_passwords (group_id, password_enc) "
                    "VALUES (:group_id, 'encrypted')"
                ),
                {"group_id": synthetic_id},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade.*group_id"):
            command.downgrade(alembic_config(database_url), "20260906_20")

        group_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_group_passwords")
        }
        assert group_columns["group_id"]["type"].length == 266
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "20260908_21"
    finally:
        engine.dispose()


def test_identifier_migration_round_trips_when_values_fit_old_contract(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config, upgrade_database
    from core.storage.storage_models import (
        EmbyIconBinding,
        EmbyIconProfile,
        EmbyGroupPassword,
        EmbyUserBackup,
        EmbyUserLink,
        LibraryAssociation,
    )

    database_url = f"sqlite:///{tmp_path / 'identifier-roundtrip.db'}"
    upgrade_database(database_url)
    config = alembic_config(database_url)
    bootstrap_engine = create_engine(database_url, future=True)
    try:
        for table in (
            EmbyUserLink,
            EmbyUserBackup,
            EmbyIconProfile,
            EmbyIconBinding,
            EmbyGroupPassword,
            LibraryAssociation,
        ):
            table.__table__.create(bootstrap_engine, checkfirst=True)
        _create_sqlite_remote_identifier_tables(bootstrap_engine)
    finally:
        bootstrap_engine.dispose()

    command.downgrade(config, "20260906_20")
    engine = create_engine(database_url, future=True)
    try:
        downgraded_links = {
            column["name"]: column for column in inspect(engine).get_columns("emby_user_links")
        }
        downgraded_bindings = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_icon_bindings")
        }
        assert downgraded_links["server_id"]["type"].length == 36
        assert downgraded_links["user_id"]["type"].length == 36
        assert downgraded_bindings["target_id"]["type"].length == 255
        downgraded_associations = {
            column["name"]: column
            for column in inspect(engine).get_columns("library_associations")
        }
        assert downgraded_associations["server_id"]["type"].length == 36
        assert downgraded_associations["library_id"]["type"].length == 36
        latest_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_latest_cache_items")
        }
        assert latest_columns["item_id"]["type"].length == 36
        assert latest_columns["library_id"]["type"].length == 36
        probe_queue_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_probe_queue")
        }
        assert probe_queue_columns["item_id"]["type"].length == 36
        assert probe_queue_columns["library_id"]["type"].length == 36
        assert probe_queue_columns["media_source_id"]["type"].length == 36
        _assert_migrated_identifier_lengths(engine, upgraded=False)

        command.upgrade(config, "head")
        upgraded_links = {
            column["name"]: column for column in inspect(engine).get_columns("emby_user_links")
        }
        upgraded_bindings = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_icon_bindings")
        }
        assert upgraded_links["server_id"]["type"].length == 128
        assert upgraded_links["user_id"]["type"].length == 128
        assert upgraded_bindings["target_id"]["type"].length == 257
        upgraded_associations = {
            column["name"]: column
            for column in inspect(engine).get_columns("library_associations")
        }
        assert upgraded_associations["server_id"]["type"].length == 128
        assert upgraded_associations["library_id"]["type"].length == 128
        latest_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_latest_cache_items")
        }
        assert latest_columns["item_id"]["type"].length == 128
        assert latest_columns["library_id"]["type"].length == 128
        probe_queue_columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("emby_probe_queue")
        }
        assert probe_queue_columns["item_id"]["type"].length == 128
        assert probe_queue_columns["library_id"]["type"].length == 128
        assert probe_queue_columns["media_source_id"]["type"].length == 128
        _assert_migrated_identifier_lengths(engine, upgraded=True)
    finally:
        engine.dispose()


def test_dry_run_reports_uninitialized_database_without_writing(tmp_path):
    from core.database_migrations import upgrade_database

    database_url = f"sqlite:///{tmp_path / 'dry-run.db'}"

    result = upgrade_database(database_url, dry_run=True)

    assert result["dry_run"] is True
    assert result["pending"] == [
        "20260829_01",
        "20260829_02",
        "20260829_03",
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
        "20260908_23",
    ]
    engine = create_engine(database_url, future=True)
    try:
        assert inspect(engine).has_table("alembic_version") is False
    finally:
        engine.dispose()


def test_upgrade_records_the_unified_alembic_baseline(tmp_path):
    from core.database_migrations import get_migration_status, upgrade_database, validate_migrations

    database_url = f"sqlite:///{tmp_path / 'schema.db'}"

    result = upgrade_database(database_url)
    status = get_migration_status(database_url)
    validation = validate_migrations(database_url)

    assert result["applied"] == [
        "20260829_01",
        "20260829_02",
        "20260829_03",
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
        "20260908_23",
    ]
    assert status.applied == [
        "20260829_01",
        "20260829_02",
        "20260829_03",
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
        "20260908_23",
    ]
    assert status.pending == []
    assert validation["ok"] is True

    engine = create_engine(database_url, future=True)
    try:
        names = set(inspect(engine).get_table_names())
        assert {
            "alembic_version",
            "users",
            "api_tokens",
            "audit_logs",
            "emby_latest_notification_deliveries",
            "emby_user_creation_journal",
        }.issubset(names)
        assert "schema_migrations" not in names
    finally:
        engine.dispose()


def test_latest_legacy_projection_is_materialized_once_then_dropped(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config
    from core.storage import DatabaseStorage

    database_url = f"sqlite:///{tmp_path / 'latest-forward-only.db'}"
    command.upgrade(alembic_config(database_url), "20260905_18")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM emby_latest_state_document"))
            connection.execute(
                text(
                    "CREATE TABLE emby_latest_state_movies ("
                    "server_id VARCHAR(36) NOT NULL, state_key VARCHAR(255) NOT NULL, "
                    "item_id VARCHAR(36), signature VARCHAR(255), title VARCHAR(500), "
                    "year INTEGER, last_seen_at DATETIME, media_source_keys JSON, "
                    "notified BOOLEAN, notified_at DATETIME, "
                    "PRIMARY KEY (server_id, state_key))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO emby_latest_state_movies "
                    "(server_id, state_key, item_id, title, year, notified) "
                    "VALUES ('server-1', 'movie-1', 'item-1', 'Film', 2026, 0)"
                )
            )
        command.upgrade(alembic_config(database_url), "head")
        inspector = inspect(engine)
        assert inspector.has_table("emby_latest_state_document")
        for table in (
            "emby_latest_state_movies",
            "emby_latest_state_series",
            "emby_latest_state_episodes",
            "emby_latest_state_series_groups",
            "emby_latest_state_series_changes",
        ):
            assert not inspector.has_table(table)
    finally:
        engine.dispose()

    storage = DatabaseStorage({"URL": database_url})
    try:
        state = storage.load_latest_state()
        assert state["server-1"]["movies"]["items"]["movie-1"]["title"] == "Film"
    finally:
        storage.close()


def test_baseline_revision_does_not_create_later_auth_columns(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'baseline.db'}"
    command.upgrade(alembic_config(database_url), "20260829_01")

    engine = create_engine(database_url, future=True)
    try:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("users")
        }
    finally:
        engine.dispose()

    assert "auth_epoch" not in columns


def test_latest_image_url_migration_removes_persisted_credentials(tmp_path):
    from alembic import command

    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'tainted-images.db'}"
    config = alembic_config(database_url)
    command.upgrade(config, "20260830_06")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE emby_latest_cache_items (
                        id INTEGER PRIMARY KEY,
                        cache_kind VARCHAR(20) NOT NULL,
                        server_id VARCHAR(36),
                        item_id VARCHAR(36),
                        image_url TEXT,
                        poster_url TEXT,
                        backdrop_url TEXT,
                        banner_url TEXT,
                        thumb_url TEXT,
                        logo_url TEXT
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO emby_latest_cache_items (
                        cache_kind, server_id, item_id, image_url,
                        poster_url, backdrop_url
                    ) VALUES (
                        'batch', 'server-a', 'movie-1',
                        'https://emby.test/image?X-Emby-Token=secret',
                        'https://emby.test/image?api_key=secret',
                        'https://images.example.test/backdrop.jpg'
                    )
                    """
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT image_url, poster_url, backdrop_url "
                    "FROM emby_latest_cache_items"
                )
            ).one()
        assert row == (None, None, "https://images.example.test/backdrop.jpg")
    finally:
        engine.dispose()


def test_baseline_bridges_existing_auth_preferences_schema(tmp_path):
    from core.database_migrations import upgrade_database

    database_url = f"sqlite:///{tmp_path / 'legacy-auth.db'}"
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE user_interface_preferences (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE,
                    primary_navigation VARCHAR(20) NOT NULL,
                    secondary_navigation VARCHAR(20) NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """))
        upgrade_database(database_url)
        columns = {column["name"] for column in inspect(engine).get_columns("user_interface_preferences")}
        assert "navigation_order" in columns
    finally:
        engine.dispose()


def test_reconciliation_repairs_probe_columns_and_preserves_legacy_rows(tmp_path):
    from core.database_migrations import upgrade_database

    database_url = f"sqlite:///{tmp_path / 'legacy-probe.db'}"
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE emby_probe_queue (
                    id INTEGER PRIMARY KEY,
                    item_id VARCHAR(36),
                    server_id VARCHAR(36),
                    item_name VARCHAR(500),
                    added_at DATETIME
                )
            """))
            connection.execute(text("""
                INSERT INTO emby_probe_queue (id, item_id, server_id, item_name, added_at)
                VALUES (1, 'item-1', 'green', 'Legacy title', CURRENT_TIMESTAMP)
            """))

        upgrade_database(database_url)

        columns = {column["name"] for column in inspect(engine).get_columns("emby_probe_queue")}
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT name, scope FROM emby_probe_queue WHERE id=1")
            ).one()
        assert {"name", "scope", "media_source_id", "library_id"}.issubset(columns)
        assert row == ("Legacy title", "libraries")
    finally:
        engine.dispose()


def test_reconciliation_bridges_legacy_table_names_without_hiding_data(tmp_path):
    from core.database_migrations import upgrade_database

    database_url = f"sqlite:///{tmp_path / 'legacy-data.db'}"
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE request_rules (request_id VARCHAR(50) PRIMARY KEY, data TEXT NOT NULL, updated_at DATETIME)"))
            connection.execute(text("INSERT INTO request_rules VALUES ('42', '{\"enabled\": true}', CURRENT_TIMESTAMP)"))
            connection.execute(text("CREATE TABLE request_rule_entries (request_id VARCHAR(50) PRIMARY KEY, rules TEXT NOT NULL, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE request_overview (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated_at DATETIME)"))
            connection.execute(text("INSERT INTO request_overview VALUES (7, '{\"items\": [1]}', CURRENT_TIMESTAMP)"))
            connection.execute(text("CREATE TABLE request_cache (id INTEGER PRIMARY KEY, request_id VARCHAR(50), payload TEXT NOT NULL, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE emby_probe_recent_scan (server_id VARCHAR(36) PRIMARY KEY, oldest_scanned_timestamp DATETIME, last_scan_at DATETIME)"))
            connection.execute(text("INSERT INTO emby_probe_recent_scan VALUES ('green', '2026-01-01', '2026-01-02')"))
            connection.execute(text("""
                CREATE TABLE emby_probe_recent_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id VARCHAR(36), library_id VARCHAR(36),
                    oldest_scanned_timestamp DATETIME, last_scan_at DATETIME,
                    payload TEXT NOT NULL
                )
            """))

        upgrade_database(database_url)

        with engine.connect() as connection:
            rules = connection.execute(text("SELECT request_id, rules FROM request_rule_entries")).all()
            cache = connection.execute(text("SELECT id, payload FROM request_cache")).all()
            recent = connection.execute(text("SELECT server_id, library_id FROM emby_probe_recent_scans")).all()
        assert rules == [("42", '{"enabled": true}')]
        assert cache == [(7, '{"items": [1]}')]
        assert recent == [("green", "__all__")]
    finally:
        engine.dispose()


def test_reconciliation_runs_for_database_already_marked_at_broken_baseline(tmp_path):
    from core.database_migrations import upgrade_database

    database_url = f"sqlite:///{tmp_path / 'already-baselined.db'}"
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('20260829_02')"))
            connection.execute(text("""
                CREATE TABLE emby_probe_history (
                    id INTEGER PRIMARY KEY,
                    item_id VARCHAR(36),
                    server_id VARCHAR(36),
                    item_name VARCHAR(500),
                    processed_at DATETIME
                )
            """))

        result = upgrade_database(database_url)

        columns = {column["name"] for column in inspect(engine).get_columns("emby_probe_history")}
        assert result["applied"] == [
            "20260829_03",
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
            "20260908_23",
        ]
        assert {"name", "scope", "error_details"}.issubset(columns)
    finally:
        engine.dispose()


def test_parse_db_upgrade_dry_run_args():
    from cli import parse_args

    args = parse_args(["db", "upgrade", "--dry-run"])

    assert args.command == "db"
    assert args.db_command == "upgrade"
    assert args.dry_run is True
