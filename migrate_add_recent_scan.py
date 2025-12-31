#!/usr/bin/env python3
"""
Migration script to add emby_probe_recent_scan table.
This table tracks timestamp scanning for the hybrid discovery algorithm.
"""

import json
import sys
from pathlib import Path
from sqlalchemy import text

def load_config():
    """Load database configuration from config.json"""
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        print("ERROR: config.json not found")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    db_config = config.get("DATABASE", {})
    if not db_config.get("ENABLED"):
        print("ERROR: Database not enabled in config")
        sys.exit(1)

    return db_config

def main():
    print("=" * 60)
    print("Migration: Add emby_probe_recent_scan table")
    print("=" * 60)
    print()

    # Load config
    db_config = load_config()
    print(f"✓ Configuration loaded")
    print(f"  Database: {db_config.get('NAME')}")
    print()

    # Initialize database
    try:
        from storage import DatabaseStorage
        db = DatabaseStorage(db_config)
        db.ensure_ready()
        print("✓ Database connection established\n")
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        sys.exit(1)

    # Check if table exists and needs migration
    print("Checking if table exists...")
    try:
        with db._engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'emby_probe_recent_scan'
            """))
            existing_columns = [row[0] for row in result.fetchall()]

            if not existing_columns:
                # Table doesn't exist, create it
                print("Creating new emby_probe_recent_scan table...")
                create_table_sql = """
                CREATE TABLE emby_probe_recent_scan (
                    server_id VARCHAR(36) NOT NULL,
                    library_id VARCHAR(36) NOT NULL DEFAULT '__all__',
                    oldest_scanned_timestamp TIMESTAMP,
                    last_scan_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (server_id, library_id)
                );

                CREATE INDEX idx_emby_probe_recent_scan_oldest_timestamp
                ON emby_probe_recent_scan(oldest_scanned_timestamp);
                """
                conn.execute(text(create_table_sql))
                conn.commit()
                print("✓ Table created successfully")
            elif 'library_id' not in existing_columns:
                # Table exists but needs migration
                print("Migrating existing table to add library_id column...")

                # Drop old primary key
                print("  - Dropping old primary key...")
                conn.execute(text('ALTER TABLE emby_probe_recent_scan DROP CONSTRAINT IF EXISTS emby_probe_recent_scan_pkey'))

                # Add library_id column
                print("  - Adding library_id column...")
                conn.execute(text("ALTER TABLE emby_probe_recent_scan ADD COLUMN library_id VARCHAR(36) NOT NULL DEFAULT '__all__'"))

                # Add new composite primary key
                print("  - Adding composite primary key...")
                conn.execute(text('ALTER TABLE emby_probe_recent_scan ADD PRIMARY KEY (server_id, library_id)'))

                # Add index on oldest_scanned_timestamp
                print("  - Creating index...")
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_emby_probe_recent_scan_oldest_timestamp ON emby_probe_recent_scan(oldest_scanned_timestamp)'))

                conn.commit()
                print("✓ Table migrated successfully")
            else:
                print("✓ Table already exists with correct schema")
    except Exception as e:
        print(f"ERROR: Failed to create/migrate table: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
