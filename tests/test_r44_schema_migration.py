"""Schema and migration regressors for the R44 composed-identifier contract."""

from __future__ import annotations

from pathlib import Path
import runpy

import pytest
from sqlalchemy import create_engine, inspect, text

from core.storage.field_limits import (
    EMBY_USER_LINK_KEY_MAX_LENGTH,
    JUSTWATCH_CACHE_KEY_MAX_LENGTH,
    KEY_VALUE_KEY_MAX_LENGTH,
    TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
)
from core.storage.storage_justwatch import StorageJustWatchMixin
from core.storage.storage_models import (
    EmbyLatestNotificationDelivery,
    EmbyUserLink,
    JustWatchCache,
    KeyValueEntry,
)


class _NoSessionJustWatchStorage(StorageJustWatchMixin):
    def _get_session(self):
        raise AssertionError("validation must happen before opening a DB session")


def _retirement_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260909_25_retire_fastapi_sources.py"
    )
    return runpy.run_path(str(path))


def _column_length(engine, table_name: str, column_name: str) -> int | None:
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(table_name)
    }
    return columns[column_name]["type"].length


def test_composed_identifier_models_share_the_canonical_schema_limits():
    assert KeyValueEntry.__table__.c.key.type.length == KEY_VALUE_KEY_MAX_LENGTH == 512
    assert (
        EmbyLatestNotificationDelivery.__table__.c.destination_key.type.length
        == TELEGRAM_DESTINATION_KEY_MAX_LENGTH
        == 257
    )
    assert (
        EmbyUserLink.__table__.c.link_key.type.length
        == EMBY_USER_LINK_KEY_MAX_LENGTH
        == 257
    )
    assert JustWatchCache.__table__.c.show_name.type.length == JUSTWATCH_CACHE_KEY_MAX_LENGTH == 512


@pytest.mark.parametrize("operation", ["get", "save", "clear"])
def test_justwatch_writer_rejects_oversized_keys_before_database_effects(operation):
    storage = _NoSessionJustWatchStorage()
    key = "x" * (JUSTWATCH_CACHE_KEY_MAX_LENGTH + 1)

    with pytest.raises(ValueError, match="show_name exceeds"):
        if operation == "get":
            storage.get_justwatch_cache(key, 1, 1)
        elif operation == "save":
            storage.save_justwatch_cache(key, 1, 1, False)
        else:
            storage.clear_justwatch_cache(key)


def test_composed_identifier_migration_is_self_contained():
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260908_22_align_composed_identifier_lengths.py"
    ).read_text(encoding="utf-8")

    assert '"key_value": {"key": (100, 512)}' in source
    assert '"destination_key": (255, 257)' in source
    assert '"link_key": (255, 257)' in source
    assert '"show_name": (500, 512)' in source
    assert "from core." not in source


_RETIRED_COLUMN_CONTRACT = {
    "emby_collection_backdrops": {"image_data"},
    "emby_collection_definitions": {"collection_id"},
    "emby_collection_posters": {"image_data"},
    "emby_icon_profiles": {"name", "profile_id"},
    "emby_icon_rules": {"excluded_terms", "label", "required_terms", "rule_id", "rule_type"},
    "emby_image_cache": {
        "content_type",
        "data",
        "image_type",
        "item_id",
        "max_height",
        "max_width",
        "scope",
        "server_id",
        "size",
        "tag",
    },
    "emby_latest_cache_errors": {"error"},
    "emby_latest_cache_items": {
        "cast",
        "critic_rating",
        "jellyseerr_request_id",
        "jellyseerr_request_status",
        "jellyseerr_request_status_label",
        "jellyseerr_requested_by",
        "letterboxd_rating",
        "rt_audience",
        "rt_tomatometer",
        "tmdb_logo_url",
    },
    "emby_probe_blacklist": {"error_message"},
    "emby_probe_history": {"error_message", "item_name"},
    "emby_probe_queue": {"item_name"},
    "emby_user_links": {"referral_admin"},
    "justwatch_cache": {"id"},
    "library_group_order": {"order_index"},
}


@pytest.mark.parametrize(
    ("table_name", "expected_columns"),
    sorted(_RETIRED_COLUMN_CONTRACT.items()),
)
def test_fastapi_retired_column_manifest_is_complete(table_name, expected_columns):
    from core.database_migrations import RETIRED_DATABASE_COLUMNS

    migration = _retirement_migration()
    migration_columns = set(migration["_OBSOLETE_COLUMNS"].get(table_name, ()))
    if table_name == "emby_image_cache":
        migration_columns.update(migration["_OBSOLETE_IMAGE_CACHE_COLUMNS"])

    assert expected_columns <= migration_columns
    assert expected_columns <= RETIRED_DATABASE_COLUMNS[table_name]


def test_fastapi_retired_table_manifest_is_complete_and_locked():
    from core.database_migrations import (
        RETIRED_DATABASE_COLUMNS,
        RETIRED_DATABASE_SEQUENCES,
        RETIRED_DATABASE_TABLES,
    )

    migration = _retirement_migration()
    migration_tables = (
        set(migration["_EMPTY_OBSOLETE_TABLES"])
        | set(migration["_METADATA_OBSOLETE_TABLES"])
        | {
            "emby_probe_recent_scan",
            "key_value_store",
            "legacy_auth_imports",
            "request_overview",
            "request_rules",
        }
    )
    migration_columns = {
        table_name: frozenset(columns)
        for table_name, columns in migration["_OBSOLETE_COLUMNS"].items()
    }
    migration_columns["emby_image_cache"] = frozenset(
        migration["_OBSOLETE_IMAGE_CACHE_COLUMNS"]
    )

    assert migration_tables == RETIRED_DATABASE_TABLES
    assert migration_columns == RETIRED_DATABASE_COLUMNS
    assert RETIRED_DATABASE_SEQUENCES == {"rss_items_id_seq"}
    for table_name, mappings in migration["_RENAMED_COLUMNS"].items():
        retired = migration_columns[table_name]
        assert {source for source, _target in mappings} <= retired
    source = Path(migration["__file__"]).read_text(encoding="utf-8")
    assert "IN ACCESS EXCLUSIVE MODE" in source
    upgrade_source = source[source.index("def upgrade()") :]
    assert upgrade_source.index("_lock_migration_tables(bind)") < upgrade_source.index(
        "_assert_empty_obsolete_tables(bind)"
    )


@pytest.mark.parametrize(
    ("table_name", "source_column", "target_column"),
    [
        (table_name, source, target)
        for table_name, mappings in _retirement_migration()["_RENAMED_COLUMNS"].items()
        for source, target in mappings
    ],
)
def test_every_renamed_column_copies_null_targets_and_rejects_conflicts(
    table_name,
    source_column,
    target_column,
):
    migration = _retirement_migration()
    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f'CREATE TABLE "{table_name}" ('
                    '_row_id INTEGER PRIMARY KEY, '
                    f'"{source_column}" TEXT, "{target_column}" TEXT)'
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{table_name}" '
                    f'(_row_id, "{source_column}", "{target_column}") '
                    "VALUES (1, 'legacy-value', NULL)"
                )
            )
            migration["_validate_renamed_columns"](connection, {table_name})
            migration["_copy_renamed_columns"](connection, {table_name})
            assert connection.execute(
                text(
                    f'SELECT "{target_column}" FROM "{table_name}" WHERE _row_id=1'
                )
            ).scalar_one() == "legacy-value"

            connection.execute(
                text(
                    f'UPDATE "{table_name}" SET "{source_column}"=:source, '
                    f'"{target_column}"=:target WHERE _row_id=1'
                ),
                {"source": "legacy-conflict", "target": "current-conflict"},
            )
            with pytest.raises(RuntimeError, match="conflicting"):
                migration["_validate_renamed_columns"](connection, {table_name})
    finally:
        engine.dispose()


def test_composed_identifier_migration_round_trip_and_global_downgrade_preflight(
    tmp_path,
):
    from alembic import command

    from core.database_migrations import alembic_config

    database_url = f"sqlite:///{tmp_path / 'r44-composed.db'}"
    config = alembic_config(database_url)
    command.upgrade(config, "20260908_21")
    engine = create_engine(database_url, future=True)
    try:
        # SQLite is a migration-test adapter only; its frozen baseline creates
        # auth tables, so provide the four historical storage shapes explicitly.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS key_value ("
                    "key VARCHAR(100) PRIMARY KEY, value JSON NOT NULL, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS emby_latest_notification_deliveries ("
                    "delivery_key VARCHAR(64) PRIMARY KEY, destination_key VARCHAR(255))"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS emby_user_links ("
                    "server_id VARCHAR(128), user_id VARCHAR(128), "
                    "link_key VARCHAR(255), PRIMARY KEY (server_id, user_id))"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_emby_user_links_link_key "
                    "ON emby_user_links (link_key)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS justwatch_cache ("
                    "show_name VARCHAR(500), season INTEGER, episode INTEGER, "
                    "is_available BOOLEAN, last_checked DATETIME NOT NULL, "
                    "PRIMARY KEY (show_name, season, episode))"
                )
            )
        command.upgrade(config, "head")

        assert _column_length(engine, "key_value", "key") == 512
        assert (
            _column_length(
                engine,
                "emby_latest_notification_deliveries",
                "destination_key",
            )
            == 257
        )
        assert _column_length(engine, "emby_user_links", "link_key") == 257
        assert _column_length(engine, "justwatch_cache", "show_name") == 512

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO key_value (key, value) "
                    "VALUES (:key, '{}')"
                ),
                {"key": "k" * 101},
            )
            connection.execute(
                text(
                    "INSERT INTO emby_latest_notification_deliveries "
                    "(delivery_key, server_id, publication_key, destination_key, "
                    "status, claim_token, claimed_at, created_at, updated_at) "
                    "VALUES ('delivery', 'server', 'publication', :destination, "
                    "'claimed', 'token', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                ),
                {"destination": "d" * 256},
            )
            connection.execute(
                text(
                    "INSERT INTO emby_user_links (server_id, user_id, link_key) "
                    "VALUES ('server', 'user', :link_key)"
                ),
                {"link_key": "l" * 256},
            )
            connection.execute(
                text(
                    "INSERT INTO justwatch_cache "
                    "(show_name, season, episode, is_available, last_checked) "
                    "VALUES (:show_name, 1, 1, 0, CURRENT_TIMESTAMP)"
                ),
                {"show_name": "j" * 501},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade composed identifiers") as error:
            command.downgrade(config, "20260908_21")
        message = str(error.value)
        assert "key_value.key: 1 value(s) exceed 100 characters" in message
        assert (
            "emby_latest_notification_deliveries.destination_key: "
            "1 value(s) exceed 255 characters"
        ) in message
        assert "emby_user_links.link_key: 1 value(s) exceed 255 characters" in message
        assert "justwatch_cache.show_name: 1 value(s) exceed 500 characters" in message

        # The global preflight runs before every ALTER, so all widths and the
        # revision remain untouched when any old contract would be violated.
        assert _column_length(engine, "key_value", "key") == 512
        assert (
            _column_length(
                engine,
                "emby_latest_notification_deliveries",
                "destination_key",
            )
            == 257
        )
        assert _column_length(engine, "emby_user_links", "link_key") == 257
        assert _column_length(engine, "justwatch_cache", "show_name") == 512
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "20260908_22"

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM key_value WHERE length(key) > 100"))
            connection.execute(
                text(
                    "DELETE FROM emby_latest_notification_deliveries "
                    "WHERE length(destination_key) > 255"
                )
            )
            connection.execute(
                text("DELETE FROM emby_user_links WHERE length(link_key) > 255")
            )
            connection.execute(
                text("DELETE FROM justwatch_cache WHERE length(show_name) > 500")
            )
        command.downgrade(config, "20260908_21")
        assert _column_length(engine, "key_value", "key") == 100
        assert _column_length(engine, "emby_user_links", "link_key") == 255
        assert _column_length(engine, "justwatch_cache", "show_name") == 500

        command.upgrade(config, "head")
        assert _column_length(engine, "key_value", "key") == 512
        assert _column_length(engine, "emby_user_links", "link_key") == 257
        assert _column_length(engine, "justwatch_cache", "show_name") == 512
    finally:
        engine.dispose()
