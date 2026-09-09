"""Reconcile and retire superseded FastAPI storage tables.

Revision ID: 20260909_25
Revises: 20260908_24
Create Date: 2026-09-09
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "20260909_25"
down_revision = "20260908_24"
branch_labels = None
depends_on = None


_EMPTY_OBSOLETE_TABLES = (
    "category_blacklist",
    "category_hidden",
    "emby_latest_state_episodes",
    "emby_latest_state_movies",
    "emby_latest_state_series",
    "emby_latest_state_series_changes",
    "emby_latest_state_series_groups",
    "inoreader_item_alternates",
    "inoreader_item_canonicals",
    "inoreader_item_categories",
    "inoreader_item_enclosures",
    "inoreader_items",
    "inoreader_streams",
    "inoreader_sync_state",
    "manual_search_results",
    "manual_search_sessions",
    "rss_items",
    "user_icons",
)
_METADATA_OBSOLETE_TABLES = ("schema_migrations",)
_OBSOLETE_IMAGE_CACHE_COLUMNS = (
    "server_id",
    "item_id",
    "image_type",
    "max_width",
    "max_height",
    "tag",
    "scope",
    "content_type",
    "data",
    "size",
)
_OBSOLETE_COLUMNS = {
    "emby_collection_backdrops": ("image_data",),
    "emby_collection_definitions": ("collection_id",),
    "emby_collection_posters": ("image_data",),
    "emby_icon_profiles": ("name", "profile_id"),
    "emby_icon_rules": (
        "excluded_terms",
        "label",
        "required_terms",
        "rule_id",
        "rule_type",
    ),
    "emby_latest_cache_errors": ("error",),
    "emby_latest_cache_items": (
        "cast",
        "critic_rating",
        "tmdb_logo_url",
        "rt_tomatometer",
        "rt_audience",
        "letterboxd_rating",
        "jellyseerr_request_id",
        "jellyseerr_request_status",
        "jellyseerr_request_status_label",
        "jellyseerr_requested_by",
    ),
    "emby_probe_blacklist": ("error_message",),
    "emby_probe_history": ("error_message", "item_name"),
    "emby_probe_queue": ("item_name",),
    "emby_user_links": ("referral_admin",),
    "justwatch_cache": ("id",),
    "library_group_order": ("order_index",),
}
_RENAMED_COLUMNS = {
    "emby_collection_backdrops": (("image_data", "data"),),
    "emby_collection_definitions": (("collection_id", "id"),),
    "emby_collection_posters": (("image_data", "data"),),
    "emby_icon_rules": (("rule_id", "profile_id"), ("label", "icon_path")),
    "emby_image_cache": (("content_type", "mime_type"), ("data", "image_data")),
    "emby_latest_cache_errors": (("error", "message"),),
    "emby_latest_cache_items": (("cast", "cast_members"),),
    "emby_probe_blacklist": (("error_message", "reason"),),
    "emby_probe_history": (("item_name", "name"), ("error_message", "error_details")),
    "emby_probe_queue": (("item_name", "name"),),
    "library_group_order": (("order_index", "position"),),
}
_MERGE_TABLES = {
    "emby_probe_recent_scan",
    "emby_probe_recent_scans",
    "key_value",
    "key_value_store",
    "request_cache",
    "request_overview",
    "request_rule_entries",
    "request_rules",
}


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _lock_migration_tables(bind) -> None:
    candidates = (
        set(_EMPTY_OBSOLETE_TABLES)
        | set(_METADATA_OBSOLETE_TABLES)
        | set(_OBSOLETE_COLUMNS)
        | set(_RENAMED_COLUMNS)
        | _MERGE_TABLES
        | {"app_settings", "emby_image_cache", "legacy_auth_imports"}
    )
    present = sorted(candidates & _tables(bind))
    if present:
        quoted = ", ".join(f'"{table}"' for table in present)
        bind.execute(text(f"LOCK TABLE {quoted} IN ACCESS EXCLUSIVE MODE"))


def _reject_ambiguous_json_conflicts(
    bind,
    *,
    legacy_table: str,
    current_table: str,
    key: str,
    legacy_value: str,
    current_value: str,
) -> None:
    conflict = bind.execute(
        text(
            f'SELECT 1 FROM "{legacy_table}" legacy '
            f'JOIN "{current_table}" current USING ("{key}") '
            f'WHERE legacy."{legacy_value}"::jsonb '
            f'IS DISTINCT FROM current."{current_value}"::jsonb '
            "AND ((legacy.updated_at IS NULL AND current.updated_at IS NULL) "
            "OR legacy.updated_at = current.updated_at) LIMIT 1"
        )
    ).first()
    if conflict is not None:
        raise RuntimeError(
            f"Cannot retire {legacy_table}: equal-time rows disagree with {current_table}"
        )


def _merge_key_value(bind) -> None:
    tables = _tables(bind)
    if "key_value_store" not in tables:
        return
    if "key_value" not in tables:
        raise RuntimeError("Cannot retire key_value_store: target key_value is missing")
    _reject_ambiguous_json_conflicts(
        bind,
        legacy_table="key_value_store",
        current_table="key_value",
        key="key",
        legacy_value="value",
        current_value="value",
    )
    bind.execute(
        text(
            "INSERT INTO key_value (key, value, updated_at) "
            "SELECT key, value, updated_at FROM key_value_store "
            "ON CONFLICT (key) DO UPDATE SET "
            "value=EXCLUDED.value, updated_at=EXCLUDED.updated_at "
            "WHERE (key_value.updated_at IS NULL AND EXCLUDED.updated_at IS NOT NULL) "
            "OR EXCLUDED.updated_at > key_value.updated_at"
        )
    )


def _merge_request_rules(bind) -> None:
    tables = _tables(bind)
    if "request_rules" not in tables:
        return
    if "request_rule_entries" not in tables:
        raise RuntimeError(
            "Cannot retire request_rules: target request_rule_entries is missing"
        )
    _reject_ambiguous_json_conflicts(
        bind,
        legacy_table="request_rules",
        current_table="request_rule_entries",
        key="request_id",
        legacy_value="data",
        current_value="rules",
    )
    bind.execute(
        text(
            "INSERT INTO request_rule_entries (request_id, rules, updated_at) "
            "SELECT request_id, data, updated_at FROM request_rules "
            "ON CONFLICT (request_id) DO UPDATE SET "
            "rules=EXCLUDED.rules, updated_at=EXCLUDED.updated_at "
            "WHERE (request_rule_entries.updated_at IS NULL "
            "AND EXCLUDED.updated_at IS NOT NULL) "
            "OR EXCLUDED.updated_at > request_rule_entries.updated_at"
        )
    )


def _merge_request_overview(bind) -> None:
    tables = _tables(bind)
    if "request_overview" not in tables:
        return
    if "request_cache" not in tables:
        raise RuntimeError(
            "Cannot retire request_overview: target request_cache is missing"
        )
    _reject_ambiguous_json_conflicts(
        bind,
        legacy_table="request_overview",
        current_table="request_cache",
        key="id",
        legacy_value="payload",
        current_value="payload",
    )
    bind.execute(
        text(
            "INSERT INTO request_cache (id, payload, updated_at) "
            "SELECT id, payload, updated_at FROM request_overview "
            "ON CONFLICT (id) DO UPDATE SET "
            "payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at "
            "WHERE (request_cache.updated_at IS NULL "
            "AND EXCLUDED.updated_at IS NOT NULL) "
            "OR EXCLUDED.updated_at > request_cache.updated_at"
        )
    )
    sequence = bind.execute(
        text("SELECT pg_get_serial_sequence('request_cache', 'id')")
    ).scalar_one_or_none()
    if sequence:
        bind.execute(
            text(
                "SELECT setval(CAST(:sequence AS regclass), "
                "COALESCE((SELECT MAX(id) FROM request_cache), 1), "
                "EXISTS (SELECT 1 FROM request_cache))"
            ),
            {"sequence": sequence},
        )


def _merge_recent_scans(bind) -> None:
    tables = _tables(bind)
    if "emby_probe_recent_scan" not in tables:
        return
    if "emby_probe_recent_scans" not in tables:
        raise RuntimeError(
            "Cannot retire emby_probe_recent_scan: target "
            "emby_probe_recent_scans is missing"
        )
    columns = {
        column["name"]
        for column in inspect(bind).get_columns("emby_probe_recent_scan")
    }
    library = (
        "COALESCE(legacy.library_id, '__all__')"
        if "library_id" in columns
        else "'__all__'"
    )
    conflict = bind.execute(
        text(
            "SELECT 1 FROM emby_probe_recent_scan legacy "
            "JOIN emby_probe_recent_scans current "
            f"ON current.server_id=legacy.server_id AND current.library_id={library} "
            "WHERE ((legacy.last_scan_at IS NULL AND current.last_scan_at IS NULL) "
            "OR legacy.last_scan_at=current.last_scan_at) "
            "AND legacy.oldest_scanned_timestamp IS DISTINCT FROM "
            "current.oldest_scanned_timestamp LIMIT 1"
        )
    ).first()
    if conflict is not None:
        raise RuntimeError(
            "Cannot retire emby_probe_recent_scan: equal-time rows disagree"
        )
    bind.execute(
        text(
            "INSERT INTO emby_probe_recent_scans "
            "(server_id, library_id, oldest_scanned_timestamp, last_scan_at, payload) "
            f"SELECT legacy.server_id, {library}, legacy.oldest_scanned_timestamp, "
            "legacy.last_scan_at, '{}'::json "
            "FROM emby_probe_recent_scan legacy "
            "ON CONFLICT (server_id, library_id) DO UPDATE SET "
            "oldest_scanned_timestamp=EXCLUDED.oldest_scanned_timestamp, "
            "last_scan_at=EXCLUDED.last_scan_at "
            "WHERE (emby_probe_recent_scans.last_scan_at IS NULL "
            "AND EXCLUDED.last_scan_at IS NOT NULL) "
            "OR EXCLUDED.last_scan_at > emby_probe_recent_scans.last_scan_at"
        )
    )


def _assert_empty_obsolete_tables(bind) -> None:
    tables = _tables(bind)
    populated = [
        table
        for table in _EMPTY_OBSOLETE_TABLES
        if table in tables
        and bind.execute(text(f'SELECT 1 FROM "{table}" LIMIT 1')).first() is not None
    ]
    if populated:
        raise RuntimeError(
            "Cannot retire populated unsupported tables: " + ", ".join(populated)
        )


def _validate_renamed_columns(bind, tables: set[str]) -> None:
    for table, mappings in _RENAMED_COLUMNS.items():
        if table not in tables:
            continue
        columns = _columns(bind, table)
        for source, target in mappings:
            if source not in columns:
                continue
            if target not in columns:
                raise RuntimeError(
                    f"Cannot retire {table}.{source}: target {target} is missing"
                )
            conflict = bind.execute(
                text(
                    f'SELECT 1 FROM "{table}" WHERE "{source}" IS NOT NULL '
                    f'AND "{target}" IS NOT NULL AND "{source}" IS DISTINCT '
                    f'FROM "{target}" LIMIT 1'
                )
            ).first()
            if conflict is not None:
                raise RuntimeError(
                    f"Cannot retire {table}.{source}: conflicting {target} values exist"
                )


def _copy_renamed_columns(bind, tables: set[str]) -> None:
    for table, mappings in _RENAMED_COLUMNS.items():
        if table not in tables:
            continue
        columns = _columns(bind, table)
        for source, target in mappings:
            if {source, target}.issubset(columns):
                bind.execute(
                    text(
                        f'UPDATE "{table}" SET "{target}"="{source}" '
                        f'WHERE "{target}" IS NULL AND "{source}" IS NOT NULL'
                    )
                )


def _reconcile_icon_profile_columns(bind, tables: set[str]) -> None:
    if "emby_icon_profiles" not in tables:
        return
    columns = _columns(bind, "emby_icon_profiles")
    if {"id", "label", "name"}.issubset(columns):
        ambiguous = bind.execute(
            text(
                "SELECT 1 FROM emby_icon_profiles "
                "WHERE name IS NOT NULL AND name <> '' "
                "AND name <> id AND name <> label AND label <> id LIMIT 1"
            )
        ).first()
        if ambiguous is not None:
            raise RuntimeError(
                "Cannot retire emby_icon_profiles.name: conflicting labels exist"
            )
        bind.execute(
            text(
                "UPDATE emby_icon_profiles SET label=name "
                "WHERE label=id AND name IS NOT NULL AND name <> '' AND name <> id"
            )
        )
    if {"id", "profile_id"}.issubset(columns):
        mismatch = bind.execute(
            text(
                "SELECT 1 FROM emby_icon_profiles "
                "WHERE profile_id IS NOT NULL AND profile_id <> id LIMIT 1"
            )
        ).first()
        if mismatch is not None:
            raise RuntimeError(
                "Cannot retire emby_icon_profiles.profile_id: identity mismatch"
            )


def _populated_columns(bind, table: str, candidates: tuple[str, ...]) -> list[str]:
    columns = _columns(bind, table)
    return [
        column
        for column in candidates
        if column in columns
        and bind.execute(
            text(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT 1')
        ).first()
        is not None
    ]


def _validate_unsupported_columns(bind, tables: set[str]) -> None:
    if "emby_icon_rules" in tables:
        unsupported = _populated_columns(
            bind,
            "emby_icon_rules",
            ("excluded_terms", "required_terms", "rule_type"),
        )
        if unsupported:
            raise RuntimeError(
                "Cannot retire populated icon-rule columns: "
                + ", ".join(unsupported)
            )
    if "emby_user_links" in tables:
        populated = _populated_columns(bind, "emby_user_links", ("referral_admin",))
        if populated:
            raise RuntimeError("Cannot retire populated emby_user_links.referral_admin")


def _drop_known_obsolete_columns(bind, tables: set[str]) -> None:
    if "emby_image_cache" in tables:
        columns = _columns(bind, "emby_image_cache")
        for column in _OBSOLETE_IMAGE_CACHE_COLUMNS:
            if column in columns:
                op.drop_column("emby_image_cache", column)
    for table, obsolete_columns in _OBSOLETE_COLUMNS.items():
        if table not in tables:
            continue
        columns = _columns(bind, table)
        for column in obsolete_columns:
            if column in columns:
                op.drop_column(table, column)


def _migrate_and_drop_obsolete_columns(bind) -> None:
    tables = _tables(bind)
    _validate_renamed_columns(bind, tables)
    _reconcile_icon_profile_columns(bind, tables)
    _validate_unsupported_columns(bind, tables)
    _copy_renamed_columns(bind, tables)
    _drop_known_obsolete_columns(bind, tables)


def _remove_rss_settings(bind) -> None:
    if "app_settings" not in _tables(bind) or "data" not in _columns(bind, "app_settings"):
        return
    bind.execute(
        text(
            "UPDATE app_settings SET data=(CASE "
            "WHEN jsonb_typeof(data::jsonb -> 'AUTO_TASKS')='object' THEN "
            "jsonb_set(data::jsonb - 'RSS_IMPORT', '{AUTO_TASKS}', "
            "(data::jsonb -> 'AUTO_TASKS') - 'rss', false) "
            "ELSE data::jsonb - 'RSS_IMPORT' END)::json "
            "WHERE data IS NOT NULL AND jsonb_typeof(data::jsonb)='object' "
            "AND ((data::jsonb ? 'RSS_IMPORT') OR "
            "(jsonb_typeof(data::jsonb -> 'AUTO_TASKS')='object' "
            "AND (data::jsonb -> 'AUTO_TASKS') ? 'rss'))"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        if "legacy_auth_imports" in _tables(bind):
            op.drop_table("legacy_auth_imports")
        return

    _lock_migration_tables(bind)
    _assert_empty_obsolete_tables(bind)
    _merge_key_value(bind)
    _merge_request_rules(bind)
    _merge_request_overview(bind)
    _merge_recent_scans(bind)
    _migrate_and_drop_obsolete_columns(bind)
    _remove_rss_settings(bind)

    tables = _tables(bind)
    for table in (
        "key_value_store",
        "request_rules",
        "request_overview",
        "emby_probe_recent_scan",
        *_EMPTY_OBSOLETE_TABLES,
        *_METADATA_OBSOLETE_TABLES,
        "legacy_auth_imports",
    ):
        if table in tables:
            op.drop_table(table)
    bind.execute(text("DROP SEQUENCE IF EXISTS rss_items_id_seq CASCADE"))


def downgrade() -> None:
    # Retired duplicate sources are intentionally not recreated. Allow older
    # independent revisions to perform their own guarded downgrades.
    return
