"""Versioned storage migration tests."""

from __future__ import annotations

import unittest

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

    def test_default_migration_catalog_contains_legacy_baseline(self):
        from core.storage.migrations import default_migrations

        migrations = default_migrations()

        self.assertEqual(
            [migration.id for migration in migrations],
            ["0001_legacy_schema_alignment", "0002_main_schema_bridge"],
        )

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


if __name__ == "__main__":
    unittest.main()
