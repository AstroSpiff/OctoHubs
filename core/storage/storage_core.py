"""Core storage plumbing for database setup and migrations."""

from __future__ import annotations

import threading
from typing import Any, Optional

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    SQLAlchemyError,
    Base,
    create_engine,
    text,
    sessionmaker,
)


class StorageCoreMixin:
    _engine: Any
    _Session: Any
    _lock: threading.Lock
    url: str

    def ensure_ready(self) -> None:
        with self._lock:
            if self._engine is None:
                self._engine = create_engine(self.url, future=True, echo=False)
                self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)
                if Base is not None:
                    Base.metadata.create_all(self._engine)
                    self._apply_migrations()

    def _apply_migrations(self) -> None:
        if self._engine is None:
            return
        try:
            with self._engine.begin() as conn:
                def _sqlite_has_column(table: str, column: str) -> bool:
                    if "postgresql" in self.url:
                        return False
                    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    return any(row[1] == column for row in rows)

                # Probe migrations
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS scope VARCHAR(20)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS library_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS library_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS error_type VARCHAR(20)"
                ))
                # Probe queue/history schema alignment
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS library_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS library_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS series_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS season_number INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS episode_number INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS year INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS media_type VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_queue ADD COLUMN IF NOT EXISTS path TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS library_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS error_details TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_history ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
                ))
                # Probe recent scans schema alignment
                conn.execute(text(
                    "ALTER TABLE emby_probe_recent_scans ADD COLUMN IF NOT EXISTS library_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_recent_scans ADD COLUMN IF NOT EXISTS oldest_scanned_timestamp TIMESTAMP"
                ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_probe_recent_scans' AND column_name = 'library_id'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_recent_scans SET library_id = COALESCE(library_id, ''__all__'')';
                            END IF;
                        END $$;
                    """))
                else:
                    if _sqlite_has_column("emby_probe_recent_scans", "library_id"):
                        conn.execute(text(
                            "UPDATE emby_probe_recent_scans SET library_id = COALESCE(library_id, '__all__')"
                        ))
                # Probe blacklist id/legacy columns
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS id SERIAL"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS id INTEGER"
                    ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS item_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS item_type VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS server_name VARCHAR(255)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_probe_queue' AND column_name = 'item_name'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_queue SET name = COALESCE(name, item_name::text)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_probe_history' AND column_name = 'item_name'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_history SET name = COALESCE(name, item_name::text)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_probe_history' AND column_name = 'error_message'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_history SET error_details = COALESCE(error_details, error_message::text)';
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("emby_probe_queue", "item_name"):
                        conn.execute(text(
                            "UPDATE emby_probe_queue SET name = COALESCE(name, item_name)"
                        ))
                    if _sqlite_has_column("emby_probe_history", "item_name"):
                        conn.execute(text(
                            "UPDATE emby_probe_history SET name = COALESCE(name, item_name)"
                        ))
                    if _sqlite_has_column("emby_probe_history", "error_message"):
                        conn.execute(text(
                            "UPDATE emby_probe_history SET error_details = COALESCE(error_details, error_message)"
                        ))
                    if _sqlite_has_column("emby_probe_blacklist", "id"):
                        conn.execute(text(
                            "UPDATE emby_probe_blacklist SET id = COALESCE(id, rowid)"
                        ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'emby_probe_blacklist_id_seq'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_blacklist SET id = COALESCE(id, nextval(''emby_probe_blacklist_id_seq''))';
                            END IF;
                        END
                        $$;
                    """))

                # Emby collections schema alignment
                conn.execute(text(
                    "ALTER TABLE emby_collection_definitions ADD COLUMN IF NOT EXISTS id VARCHAR(50)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_definitions ADD COLUMN IF NOT EXISTS data JSON"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_definitions ADD COLUMN IF NOT EXISTS data TEXT"
                    ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_definitions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_definitions ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_collection_definitions' AND column_name = 'collection_id'
                            ) THEN
                                EXECUTE 'UPDATE emby_collection_definitions SET id = COALESCE(id, collection_id::text)';
                            END IF;
                        END
                        $$;
                    """))
                    conn.execute(text(
                        "UPDATE emby_collection_definitions SET data = COALESCE(data, '{}'::json)"
                    ))
                else:
                    if _sqlite_has_column("emby_collection_definitions", "collection_id"):
                        conn.execute(text(
                            "UPDATE emby_collection_definitions SET id = COALESCE(id, collection_id)"
                        ))
                    conn.execute(text(
                        "UPDATE emby_collection_definitions SET data = COALESCE(data, '{}')"
                    ))

                # Emby collections poster/backdrop blobs
                conn.execute(text(
                    "ALTER TABLE emby_collection_posters ADD COLUMN IF NOT EXISTS data BYTEA" if "postgresql" in self.url else "ALTER TABLE emby_collection_posters ADD COLUMN IF NOT EXISTS data BLOB"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_collection_posters ADD COLUMN IF NOT EXISTS mime_type VARCHAR(50)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_posters ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_posters ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                conn.execute(text(
                    "ALTER TABLE emby_collection_backdrops ADD COLUMN IF NOT EXISTS data BYTEA" if "postgresql" in self.url else "ALTER TABLE emby_collection_backdrops ADD COLUMN IF NOT EXISTS data BLOB"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_collection_backdrops ADD COLUMN IF NOT EXISTS mime_type VARCHAR(50)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_backdrops ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_collection_backdrops ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_collection_posters' AND column_name = 'image_data'
                            ) THEN
                                EXECUTE 'UPDATE emby_collection_posters SET data = COALESCE(data, image_data)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_collection_backdrops' AND column_name = 'image_data'
                            ) THEN
                                EXECUTE 'UPDATE emby_collection_backdrops SET data = COALESCE(data, image_data)';
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("emby_collection_posters", "image_data"):
                        conn.execute(text(
                            "UPDATE emby_collection_posters SET data = COALESCE(data, image_data)"
                        ))
                    if _sqlite_has_column("emby_collection_backdrops", "image_data"):
                        conn.execute(text(
                            "UPDATE emby_collection_backdrops SET data = COALESCE(data, image_data)"
                        ))
                conn.execute(text(
                    "ALTER TABLE justwatch_cache ADD COLUMN IF NOT EXISTS providers JSON"
                ))
                # User Link/Backup migrations
                conn.execute(text(
                    "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS is_leader BOOLEAN DEFAULT FALSE"
                ))
                # Icon Rules migrations
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BYTEA" if "postgresql" in self.url else "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BLOB"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS mime_type VARCHAR(50)"
                ))
                # Group password storage
                if "postgresql" in self.url:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS emby_group_passwords (
                            group_id VARCHAR(255) PRIMARY KEY,
                            password_enc TEXT NOT NULL,
                            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS emby_group_passwords (
                            group_id VARCHAR(255) PRIMARY KEY,
                            password_enc TEXT NOT NULL,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                    """))

                # Library associations columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE library_associations ADD COLUMN IF NOT EXISTS library_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE library_associations ADD COLUMN IF NOT EXISTS collection_type VARCHAR(50)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE library_associations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE library_associations ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))

                # Library group order columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE library_group_order ADD COLUMN IF NOT EXISTS collection_type VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE library_group_order ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE library_group_order ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE library_group_order ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'library_group_order' AND column_name = 'order_index'
                            ) THEN
                                EXECUTE 'UPDATE library_group_order SET position = COALESCE(position, order_index)';
                            END IF;
                            EXECUTE 'UPDATE library_group_order SET collection_type = COALESCE(collection_type, '''')';
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("library_group_order", "order_index"):
                        conn.execute(text(
                            "UPDATE library_group_order SET position = COALESCE(position, order_index)"
                        ))
                    conn.execute(text(
                        "UPDATE library_group_order SET collection_type = COALESCE(collection_type, '')"
                    ))

                # Emby icon profiles/rules columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_icon_profiles ADD COLUMN IF NOT EXISTS id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_profiles ADD COLUMN IF NOT EXISTS label VARCHAR(255)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_profiles ADD COLUMN IF NOT EXISTS is_group_profile BOOLEAN DEFAULT FALSE"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_profiles ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS profile_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS column_key VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS icon_path TEXT"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BYTEA"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS image_data BLOB"
                    ))
                conn.execute(text(
                    "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS mime_type VARCHAR(50)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_icon_rules ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                # Backfill profile_id/rule_id from legacy id columns when present (PostgreSQL only).
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_icon_profiles' AND column_name = 'profile_id'
                            ) THEN
                                EXECUTE 'UPDATE emby_icon_profiles SET id = COALESCE(id, profile_id::text)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_icon_rules' AND column_name = 'rule_id'
                            ) THEN
                                EXECUTE 'UPDATE emby_icon_rules SET profile_id = COALESCE(profile_id, rule_id::text)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_icon_rules' AND column_name = 'label'
                            ) THEN
                                EXECUTE 'UPDATE emby_icon_rules SET icon_path = COALESCE(icon_path, label::text)';
                            END IF;
                            EXECUTE 'UPDATE emby_icon_profiles SET label = COALESCE(label, id)';
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("emby_icon_profiles", "profile_id"):
                        conn.execute(text(
                            "UPDATE emby_icon_profiles SET id = COALESCE(id, profile_id)"
                        ))
                    if _sqlite_has_column("emby_icon_rules", "rule_id"):
                        conn.execute(text(
                            "UPDATE emby_icon_rules SET profile_id = COALESCE(profile_id, rule_id)"
                        ))
                    if _sqlite_has_column("emby_icon_rules", "label"):
                        conn.execute(text(
                            "UPDATE emby_icon_rules SET icon_path = COALESCE(icon_path, label)"
                        ))
                    conn.execute(text(
                        "UPDATE emby_icon_profiles SET label = COALESCE(label, id)"
                    ))

                # Emby user links columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS link_key VARCHAR(255)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS group_id VARCHAR(255)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_user_links ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                conn.execute(text(
                    "UPDATE emby_user_links SET link_key = COALESCE(link_key, server_id || ':' || user_id)"
                ))
                conn.execute(text(
                    "UPDATE emby_user_links SET group_id = COALESCE(group_id, 'unlinked_' || server_id || '_' || user_id)"
                ))

                # Emby probe blacklist columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS reason TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_probe_blacklist ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0"
                ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_probe_blacklist' AND column_name = 'error_message'
                            ) THEN
                                EXECUTE 'UPDATE emby_probe_blacklist SET reason = COALESCE(reason, error_message::text)';
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("emby_probe_blacklist", "error_message"):
                        conn.execute(text(
                            "UPDATE emby_probe_blacklist SET reason = COALESCE(reason, error_message)"
                        ))

                # Category blacklist/hidden columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE category_blacklist ADD COLUMN IF NOT EXISTS category_name VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE category_hidden ADD COLUMN IF NOT EXISTS category_name VARCHAR(500)"
                ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'category_blacklist' AND column_name = 'category'
                            ) THEN
                                EXECUTE 'UPDATE category_blacklist SET category_name = COALESCE(category_name, category::text)';
                            END IF;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'category_hidden' AND column_name = 'category'
                            ) THEN
                                EXECUTE 'UPDATE category_hidden SET category_name = COALESCE(category_name, category::text)';
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("category_blacklist", "category"):
                        conn.execute(text(
                            "UPDATE category_blacklist SET category_name = COALESCE(category_name, category)"
                        ))
                    if _sqlite_has_column("category_hidden", "category"):
                        conn.execute(text(
                            "UPDATE category_hidden SET category_name = COALESCE(category_name, category)"
                        ))

                # Latest progress columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS state VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS total INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS completed INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS message TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE"
                    if "postgresql" in self.url else
                    "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS started_at DATETIME"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_progress ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))

                # Latest cache change columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS cache_item_id INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS sort_index INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS kind VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS label VARCHAR(200)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS season_number INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS episode_number INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS episode_title VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS quality VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS resolution VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS video_codec VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_codec VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_channels VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS container VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS bitrate VARCHAR(50)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS source_name VARCHAR(200)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS path TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS size INTEGER"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS media_source_id VARCHAR(100)"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS added_at TIMESTAMP WITH TIME ZONE"
                    if "postgresql" in self.url else
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS added_at DATETIME"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS video_details TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_details TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_ita TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_eng TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_fra TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_spa TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_ger TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_jpn TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS audio_langs TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS subtitle_langs TEXT"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_cache_changes ADD COLUMN IF NOT EXISTS created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))

                # Latest cache errors columns (legacy schema)
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_errors ADD COLUMN IF NOT EXISTS message TEXT"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_cache_errors ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE emby_latest_cache_errors ADD COLUMN IF NOT EXISTS created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'emby_latest_cache_errors' AND column_name = 'error'
                            ) THEN
                                EXECUTE 'UPDATE emby_latest_cache_errors SET message = COALESCE(message, error::text)';
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("emby_latest_cache_errors", "error"):
                        conn.execute(text(
                            "UPDATE emby_latest_cache_errors SET message = COALESCE(message, error)"
                        ))

                # RSS item schema alignment
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS id SERIAL"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS id INTEGER"
                    ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS source_name VARCHAR(200)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS source_url VARCHAR(1000)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS source_tags JSON"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS title VARCHAR(1000)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS link VARCHAR(2000)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS guid VARCHAR(1000)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS author VARCHAR(500)"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS summary TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS content TEXT"
                ))
                if "postgresql" in self.url:
                    conn.execute(text(
                        "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS categories VARCHAR[]"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS categories JSON"
                    ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS published_at TIMESTAMP"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items ADD COLUMN IF NOT EXISTS extra JSON"
                ))
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'rss_items' AND column_name = 'id'
                            ) THEN
                                IF NOT EXISTS (
                                    SELECT 1 FROM pg_class WHERE relname = 'rss_items_id_seq'
                                ) THEN
                                    CREATE SEQUENCE rss_items_id_seq;
                                END IF;
                                ALTER TABLE rss_items ALTER COLUMN id SET DEFAULT nextval('rss_items_id_seq');
                                UPDATE rss_items SET id = nextval('rss_items_id_seq') WHERE id IS NULL;
                            END IF;
                        END
                        $$;
                    """))
                else:
                    if _sqlite_has_column("rss_items", "id"):
                        conn.execute(text(
                            "UPDATE rss_items SET id = rowid WHERE id IS NULL"
                        ))

                # RSS Category Management migrations
                # Drop visibility_status column (no longer needed - visibility determined by categories)
                conn.execute(text(
                    "DROP INDEX IF EXISTS ix_rss_items_visibility_status"
                ))
                conn.execute(text(
                    "ALTER TABLE rss_items DROP COLUMN IF EXISTS visibility_status"
                ))

                # Create category_hidden table if not exists
                if "postgresql" in self.url:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS category_hidden (
                            id SERIAL PRIMARY KEY,
                            category_name VARCHAR(500) UNIQUE NOT NULL,
                            added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                    """))
                else:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS category_hidden (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            category_name VARCHAR(500) UNIQUE NOT NULL,
                            added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                # Create index on category_name
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_category_hidden_category_name ON category_hidden(category_name)"
                ))

                # Convert categories column from JSON to ARRAY for better performance
                if "postgresql" in self.url:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            -- Check if column is JSON/JSONB type
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'rss_items'
                                AND column_name = 'categories'
                                AND (data_type = 'json' OR data_type = 'jsonb')
                            ) THEN
                                -- Create temporary function to convert JSON array to text array
                                CREATE OR REPLACE FUNCTION temp_json_to_text_array(val json)
                                RETURNS text[] AS $func$
                                    SELECT CASE
                                        WHEN val IS NULL THEN NULL
                                        WHEN jsonb_typeof(val::jsonb) = 'array'
                                        THEN ARRAY(SELECT jsonb_array_elements_text(val::jsonb))
                                        ELSE ARRAY[]::text[]
                                    END;
                                $func$ LANGUAGE SQL IMMUTABLE;

                                -- Convert column using helper function
                                ALTER TABLE rss_items
                                ALTER COLUMN categories
                                TYPE varchar[]
                                USING temp_json_to_text_array(categories);

                                -- Drop temporary function
                                DROP FUNCTION temp_json_to_text_array(json);
                            END IF;
                        END $$;
                    """))
                    # Create GIN index on categories array for fast overlap queries
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_rss_items_categories_gin ON rss_items USING GIN(categories)"
                    ))
                # Latest cache/state indexes
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_cache_kind_server_type ON emby_latest_cache_items (cache_kind, server_id, item_type)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_cache_kind_sort ON emby_latest_cache_items (cache_kind, sort_ts)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_movies_server_last_seen ON emby_latest_state_movies (server_id, last_seen_at)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_movies_server_item ON emby_latest_state_movies (server_id, item_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_series_server_last_seen ON emby_latest_state_series (server_id, last_seen_at)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_series_server ON emby_latest_state_series (server_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_episodes_server_series ON emby_latest_state_episodes (server_id, series_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_series_groups_server_series ON emby_latest_state_series_groups (server_id, series_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_latest_state_episodes_episode_id ON emby_latest_state_episodes (episode_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_emby_image_cache_expires ON emby_image_cache (expires_at)"
                ))
                # Ensure latest cache item columns exist (compat upgrade from older schemas)
                latest_cache_columns = [
                    "item_type VARCHAR(20)",
                    "server_id VARCHAR(36)",
                    "item_id VARCHAR(36)",
                    "signature VARCHAR(255)",
                    "batch_id VARCHAR(255)",
                    "title VARCHAR(500)",
                    "original_title VARCHAR(500)",
                    "series_name VARCHAR(500)",
                    "season_name VARCHAR(500)",
                    "season_number INTEGER",
                    "episode_number INTEGER",
                    "episode_title VARCHAR(500)",
                    "year INTEGER",
                    "overview TEXT",
                    "genres VARCHAR[]",
                    "community_rating VARCHAR(50)",
                    "official_rating VARCHAR(50)",
                    "runtime_minutes INTEGER",
                    "added_at TIMESTAMP WITH TIME ZONE",
                    "premiere_date TIMESTAMP WITH TIME ZONE",
                    "child_count INTEGER",
                    "season_count INTEGER",
                    "episode_count INTEGER",
                    "image_tag VARCHAR(255)",
                    "image_url TEXT",
                    "poster_url TEXT",
                    "backdrop_url TEXT",
                    "banner_url TEXT",
                    "thumb_url TEXT",
                    "logo_url TEXT",
                    "emby_url TEXT",
                    "tagline TEXT",
                    "studios VARCHAR[]",
                    "cast_members VARCHAR[]",
                    "directors VARCHAR[]",
                    "creators VARCHAR[]",
                    "tmdb_id VARCHAR(50)",
                    "imdb_id VARCHAR(50)",
                    "tvdb_id VARCHAR(50)",
                    "trakt_id VARCHAR(100)",
                    "library_id VARCHAR(36)",
                    "library_name VARCHAR(500)",
                    "server_name VARCHAR(255)",
                    "server_icon VARCHAR(100)",
                    "server_icon_color VARCHAR(50)",
                    "server_icon_style VARCHAR(50)",
                    "update_type VARCHAR(20)",
                    "update_label VARCHAR(200)",
                    "tmdb_poster_url TEXT",
                    "tmdb_backdrop_url TEXT",
                    "tmdb_banner_url TEXT",
                    "tmdb_thumb_url TEXT",
                    "tmdb_rating VARCHAR(50)",
                    "tmdb_votes VARCHAR(50)",
                    "imdb_rating VARCHAR(50)",
                    "imdb_votes VARCHAR(50)",
                    "metacritic_rating VARCHAR(50)",
                    "trakt_rating VARCHAR(50)",
                    "trakt_votes VARCHAR(50)",
                    "omdb_fetched_at TIMESTAMP WITH TIME ZONE",
                    "sort_ts TIMESTAMP WITH TIME ZONE"
                ]
                for column_def in latest_cache_columns:
                    conn.execute(text(
                        f"ALTER TABLE emby_latest_cache_items ADD COLUMN IF NOT EXISTS {column_def}"
                    ))
                # Drop deprecated latest cache columns (no longer used)
                drop_latest_cache_columns = [
                    "critic_rating",
                    "tmdb_logo_url",
                    "rt_tomatometer",
                    "rt_audience",
                    "letterboxd_rating",
                    "jellyseerr_request_id",
                    "jellyseerr_request_status",
                    "jellyseerr_request_status_label",
                    "jellyseerr_requested_by"
                ]
                for column_name in drop_latest_cache_columns:
                    conn.execute(text(
                        f"ALTER TABLE emby_latest_cache_items DROP COLUMN IF EXISTS {column_name}"
                    ))
                # Ensure BIGINT for size columns (avoid overflow on large files)
                conn.execute(text(
                    "ALTER TABLE emby_latest_cache_changes ALTER COLUMN size TYPE BIGINT"
                ))
                conn.execute(text(
                    "ALTER TABLE emby_latest_state_series_changes ALTER COLUMN size TYPE BIGINT"
                ))
        except SQLAlchemyError as exc:  # pragma: no cover
            raise StorageError(f"Errore migrazioni DB: {exc}") from exc

    def _get_session(self) -> Any:
        if self._Session is None:
            self.ensure_ready()
        return self._Session()

    def test_connection(self) -> tuple[bool, Optional[str]]:
        try:
            self.ensure_ready()
            if self._engine is None:
                return False, "Engine non inizializzato"
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, None
        except Exception as exc:  # pragma: no cover - runtime guard
            return False, str(exc)
