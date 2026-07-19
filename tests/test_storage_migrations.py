"""Versioned storage migration tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine, text


class StorageMigrationTests(unittest.TestCase):
    def test_dry_run_reports_pending_without_writing_registry(self):
        from core.storage.migrations import Migration, apply_pending_migrations

        engine = create_engine("sqlite:///:memory:", future=True)
        try:
            migration = Migration(
                "9999_test",
                "test migration",
                lambda conn, url: conn.execute(text("CREATE TABLE sample (id INTEGER)")),
            )

            result = apply_pending_migrations(
                engine,
                "sqlite:///:memory:",
                migrations=[migration],
                dry_run=True,
            )

            self.assertEqual(result["pending"], ["9999_test"])
            with engine.connect() as conn:
                names = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            self.assertNotIn(("schema_migrations",), names)
            self.assertNotIn(("sample",), names)
        finally:
            engine.dispose()

    def test_upgrade_records_applied_migration_and_status(self):
        from core.storage.migrations import (
            Migration,
            apply_pending_migrations,
            get_migration_status,
            validate_migrations,
        )

        engine = create_engine("sqlite:///:memory:", future=True)
        try:
            migration = Migration(
                "9999_test",
                "test migration",
                lambda conn, url: conn.execute(text("CREATE TABLE sample (id INTEGER)")),
            )

            result = apply_pending_migrations(
                engine,
                "sqlite:///:memory:",
                migrations=[migration],
            )
            status = get_migration_status(
                engine,
                "sqlite:///:memory:",
                migrations=[migration],
            )
            validation = validate_migrations(
                engine,
                "sqlite:///:memory:",
                migrations=[migration],
            )

            self.assertEqual(result["applied"], ["9999_test"])
            self.assertEqual(result["pending"], ["9999_test"])
            self.assertEqual(status.applied, ["9999_test"])
            self.assertEqual(status.pending, [])
            self.assertIs(validation["ok"], True)
        finally:
            engine.dispose()

    def test_backup_runs_before_schema_changes_when_migrations_are_pending(self):
        from core.storage.migrations import Migration, apply_pending_migrations

        engine = create_engine("sqlite:///:memory:", future=True)
        events = []
        try:
            migration = Migration(
                "9999_test",
                "test migration",
                lambda conn, url: events.append("migration"),
            )

            def backup(status, pending):
                events.append("backup")
                self.assertEqual(status.pending, ["9999_test"])
                self.assertEqual([migration.id for migration in pending], ["9999_test"])
                with engine.connect() as conn:
                    names = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    ).fetchall()
                self.assertNotIn(("sample",), names)
                return {"path": "/tmp/pre-migration.dump"}

            def create_schema_table():
                events.append("create_all")
                with engine.begin() as conn:
                    conn.execute(text("CREATE TABLE sample (id INTEGER)"))

            result = apply_pending_migrations(
                engine,
                "sqlite:///:memory:",
                migrations=[migration],
                backup_before_apply=backup,
                before_apply=create_schema_table,
            )

            self.assertEqual(events, ["backup", "create_all", "migration"])
            self.assertEqual(result["backup"], {"path": "/tmp/pre-migration.dump"})
        finally:
            engine.dispose()

    def test_backup_failure_blocks_pending_migrations(self):
        from core.storage.migrations import Migration, apply_pending_migrations
        from core.storage.storage_errors import StorageError

        engine = create_engine("sqlite:///:memory:", future=True)
        events = []
        try:
            migration = Migration(
                "9999_test",
                "test migration",
                lambda conn, url: events.append("migration"),
            )

            def backup(status, pending):
                events.append("backup")
                raise StorageError("backup failed")

            with self.assertRaises(StorageError):
                apply_pending_migrations(
                    engine,
                    "sqlite:///:memory:",
                    migrations=[migration],
                    backup_before_apply=backup,
                    before_apply=lambda: events.append("create_all"),
                )

            self.assertEqual(events, ["backup"])
        finally:
            engine.dispose()

    def test_default_migration_catalog_contains_legacy_baseline(self):
        from core.storage.migrations import default_migrations

        migrations = default_migrations()

        self.assertEqual(
            [migration.id for migration in migrations],
            [
                "0001_legacy_schema_alignment",
                "0002_main_schema_bridge",
                "0003_manual_search_history",
            ],
        )

    def test_manual_search_history_migration_repairs_already_migrated_database(self):
        from core.storage.migrations import apply_pending_migrations, default_migrations

        engine = create_engine("sqlite:///:memory:", future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE schema_migrations (
                            id VARCHAR(255) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO schema_migrations (id, name)
                        VALUES (:id, :name)
                        """
                    ),
                    [
                        {"id": "0001_legacy_schema_alignment", "name": "Legacy schema alignment"},
                        {"id": "0002_main_schema_bridge", "name": "Bridge legacy GitHub main schema table names"},
                    ],
                )

            result = apply_pending_migrations(
                engine,
                "sqlite:///:memory:",
                migrations=default_migrations(lambda conn, url: None),
            )

            self.assertEqual(result["applied"], ["0003_manual_search_history"])
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM sqlite_master
                        WHERE type = 'table' AND name = 'manual_search_history'
                        LIMIT 1
                        """
                    )
                ).first()
            self.assertIsNotNone(row)
        finally:
            engine.dispose()

    def test_request_rule_entry_exposes_data_attribute_for_rules_column(self):
        from core.storage.storage_models import RequestRuleEntry

        self.assertEqual(RequestRuleEntry.data.property.columns[0].name, "rules")

    def test_main_schema_bridge_copies_legacy_main_tables(self):
        from core.storage.migrations import apply_main_schema_bridge

        engine = create_engine("sqlite:///:memory:", future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE request_rules (request_id VARCHAR(32) PRIMARY KEY, data TEXT NOT NULL, updated_at DATETIME)"))
                conn.execute(text("INSERT INTO request_rules (request_id, data, updated_at) VALUES ('42', '{\"enabled\": true}', '2026-01-01 10:00:00')"))
                conn.execute(text("CREATE TABLE request_rule_entries (request_id VARCHAR(50) PRIMARY KEY, rules TEXT NOT NULL, updated_at DATETIME)"))

                conn.execute(text("CREATE TABLE request_overview (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated_at DATETIME)"))
                conn.execute(text("INSERT INTO request_overview (id, payload, updated_at) VALUES (1, '{\"items\": [1]}', '2026-01-02 10:00:00')"))
                conn.execute(text("CREATE TABLE request_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id VARCHAR(50), payload TEXT NOT NULL, updated_at DATETIME)"))

                conn.execute(text("CREATE TABLE emby_probe_recent_scan (server_id VARCHAR(36) PRIMARY KEY, oldest_scanned_timestamp DATETIME, last_scan_at DATETIME)"))
                conn.execute(text("INSERT INTO emby_probe_recent_scan (server_id, oldest_scanned_timestamp, last_scan_at) VALUES ('server-a', '2026-01-03 10:00:00', '2026-01-04 10:00:00')"))
                conn.execute(text("CREATE TABLE emby_probe_recent_scans (server_id VARCHAR(36), library_id VARCHAR(36), oldest_scanned_timestamp DATETIME, last_scan_at DATETIME, payload TEXT, PRIMARY KEY (server_id, library_id))"))

                apply_main_schema_bridge(conn, "sqlite:///:memory:")

                rules = conn.execute(text("SELECT request_id, rules FROM request_rule_entries")).fetchall()
                overview = conn.execute(text("SELECT id, payload FROM request_cache")).fetchall()
                recent = conn.execute(text("SELECT server_id, library_id, oldest_scanned_timestamp FROM emby_probe_recent_scans")).fetchall()

            self.assertEqual(rules, [("42", '{"enabled": true}')])
            self.assertEqual(overview, [(1, '{"items": [1]}')])
            self.assertEqual(recent, [("server-a", "__all__", "2026-01-03 10:00:00")])
        finally:
            engine.dispose()

    def test_parse_db_status_args(self):
        from cli import parse_args

        args = parse_args(["db", "status"])

        self.assertEqual(args.command, "db")
        self.assertEqual(args.db_command, "status")

    def test_parse_db_upgrade_dry_run_args(self):
        from cli import parse_args

        args = parse_args(["db", "upgrade", "--dry-run"])

        self.assertEqual(args.command, "db")
        self.assertEqual(args.db_command, "upgrade")
        self.assertIs(args.dry_run, True)


class StorageBackupTests(unittest.TestCase):
    def test_sqlite_backup_copies_database_and_writes_manifest(self):
        from core.storage.backups import create_database_backup

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "source.db"
            backup_root = Path(tmpdir) / "backups"
            engine = create_engine(f"sqlite:///{db_path}", future=True)
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)"))
                    conn.execute(text("INSERT INTO sample (name) VALUES ('before')"))
            finally:
                engine.dispose()

            result = create_database_backup(
                {"URL": f"sqlite:///{db_path}"},
                ["0001_legacy_schema_alignment"],
                backup_root=backup_root,
            )

            dump_path = Path(result["path"])
            manifest_path = Path(result["manifest_path"])
            self.assertTrue(dump_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertEqual(result["pending_migrations"], ["0001_legacy_schema_alignment"])

            copied = create_engine(f"sqlite:///{dump_path}", future=True)
            try:
                with copied.connect() as conn:
                    rows = conn.execute(text("SELECT name FROM sample")).fetchall()
                self.assertEqual(rows, [("before",)])
            finally:
                copied.dispose()

    def test_postgres_backup_uses_configured_pg_dump_path(self):
        from core.storage.backups import create_database_backup

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_pg_dump = root / "pg_dump"
            fake_pg_dump.write_text(
                "#!/bin/sh\n"
                "while [ \"$1\" != \"\" ]; do\n"
                "  if [ \"$1\" = \"--file\" ]; then shift; echo dump > \"$1\"; exit 0; fi\n"
                "  shift\n"
                "done\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_pg_dump.chmod(0o755)

            settings = {
                "DRIVER": "postgresql+psycopg2",
                "HOST": "localhost",
                "PORT": 5432,
                "NAME": "jellychecker",
                "USER": "jellychecker",
                "PASSWORD": "secret",
            }
            with patch.dict("os.environ", {"OCTOHUB_PG_DUMP": str(fake_pg_dump)}):
                result = create_database_backup(
                    settings,
                    ["0001_legacy_schema_alignment"],
                    backup_root=root / "backups",
                )

            self.assertTrue(Path(result["path"]).exists())
            self.assertEqual(Path(result["path"]).read_text(encoding="utf-8").strip(), "dump")
            self.assertTrue(Path(result["manifest_path"]).exists())


if __name__ == "__main__":
    unittest.main()
