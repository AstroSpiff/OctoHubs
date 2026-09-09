"""One-shot preparation for the published pre-Alembic FastAPI schema.

The published FastAPI release did not persist ``emby_image_cache.image_url``.
Alembic revision 03 adds that column as nullable so populated databases can be
altered, while revision 04 correctly requires the canonical non-null contract.
This preparation runs under the migration advisory lock before Alembic and
supplies the deterministic cache reference used by the current writer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text


_PRE_FINALIZATION_REVISIONS = {
    None,
    "20260829_01",
    "20260829_02",
    "20260829_03",
}
_FASTAPI_IMAGE_CACHE_SIGNATURES = (
    # Schema declared by the published FastAPI model.
    {"cache_key", "mime_type", "image_data", "image_hash"},
    # Older physical schema still present in the real published deployment.
    {"cache_key", "server_id", "item_id", "content_type", "data", "size"},
)


def _current_revision(connection: Any, tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    rows = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if not rows:
        return None
    if len(rows) > 1:
        return "__unsupported__"
    return str(rows[0])


def prepare_published_fastapi_schema(connection: Any) -> bool:
    """Make the published FastAPI image cache consumable by revision 04.

    The operation is deliberately narrow and idempotent. Unknown schemas and
    databases already finalized beyond revision 03 are left untouched so the
    normal schema validator can fail closed instead of hiding drift.
    """

    if connection.dialect.name != "postgresql":
        return False

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "emby_image_cache" not in tables:
        return False
    if _current_revision(connection, tables) not in _PRE_FINALIZATION_REVISIONS:
        return False

    columns = {column["name"] for column in inspector.get_columns("emby_image_cache")}
    if not any(
        signature.issubset(columns)
        for signature in _FASTAPI_IMAGE_CACHE_SIGNATURES
    ):
        return False

    changed = False
    if "image_url" not in columns:
        connection.execute(text("ALTER TABLE emby_image_cache ADD COLUMN image_url TEXT"))
        changed = True

    result = connection.execute(
        text(
            "UPDATE emby_image_cache "
            "SET image_url='cache://' || cache_key "
            "WHERE image_url IS NULL"
        )
    )
    return changed or bool(result.rowcount)


__all__ = ["prepare_published_fastapi_schema"]
