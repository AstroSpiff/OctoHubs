"""Versioned storage migration tests."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, text


class StorageMigrationTests(unittest.TestCase):
    def test_dry_run_reports_pending_without_writing_registry(self):
        from core.storage.migrations import Migration, apply_pending_migrations

        engine = create_engine("sqlite:///:memory:", future=True)
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

    def test_upgrade_records_applied_migration_and_status(self):
        from core.storage.migrations import (
            Migration,
            apply_pending_migrations,
            get_migration_status,
            validate_migrations,
        )

        engine = create_engine("sqlite:///:memory:", future=True)
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

    def test_default_migration_catalog_contains_legacy_baseline(self):
        from core.storage.migrations import default_migrations

        migrations = default_migrations()

        self.assertEqual(
            [migration.id for migration in migrations],
            ["0001_legacy_schema_alignment"],
        )

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


if __name__ == "__main__":
    unittest.main()
