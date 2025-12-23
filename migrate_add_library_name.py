#!/usr/bin/env python3
"""
Migration script to add library_name column to emby_probe_queue and emby_probe_history tables.
"""

import sys
import json
from storage import DatabaseStorage
from sqlalchemy import text

def main():
    print("=== Database Migration: Add library_name column ===\n")

    # Load config manually
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load config.json: {e}")
        return 1

    db_config = config.get("DATABASE", {})
    if not db_config:
        print("ERROR: No database configuration found")
        return 1

    # Initialize database
    try:
        db = DatabaseStorage(db_config)
        db.ensure_ready()
        print("✓ Database connection established\n")
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        return 1

    # Add library_name column to emby_probe_queue
    print("Adding library_name column to emby_probe_queue...")
    try:
        with db._engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='emby_probe_queue'
                AND column_name='library_name'
            """))

            if result.fetchone():
                print("  → Column already exists, skipping")
            else:
                conn.execute(text("ALTER TABLE emby_probe_queue ADD COLUMN library_name VARCHAR(500)"))
                conn.commit()
                print("  ✓ Column added successfully")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return 1

    # Add library_name column to emby_probe_history
    print("\nAdding library_name column to emby_probe_history...")
    try:
        with db._engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='emby_probe_history'
                AND column_name='library_name'
            """))

            if result.fetchone():
                print("  → Column already exists, skipping")
            else:
                conn.execute(text("ALTER TABLE emby_probe_history ADD COLUMN library_name VARCHAR(500)"))
                conn.commit()
                print("  ✓ Column added successfully")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return 1

    print("\n=== Migration completed successfully ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
