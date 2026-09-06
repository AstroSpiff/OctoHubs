"""Tests for the unified Alembic database lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text


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
