"""Emby image cache storage operations."""

from __future__ import annotations

from datetime import timedelta
import hashlib
from typing import Any, Dict, Optional, Protocol

from core.persisted_text import project_persisted_text
from core.storage.field_limits import (
    IMAGE_CACHE_KEY_MAX_LENGTH,
    IMAGE_CACHE_MIME_TYPE_MAX_LENGTH,
    require_bounded_text,
)
from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_models import SQLAlchemyError, EmbyImageCache, _utcnow, func


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageImageCacheMixin(_SessionProvider):
    def load_emby_image_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        try:
            cache_key = require_bounded_text(
                cache_key,
                field="cache_key",
                max_length=IMAGE_CACHE_KEY_MAX_LENGTH,
            )
        except ValueError:
            return None
        session = self._get_session()
        try:
            row = session.get(EmbyImageCache, cache_key)
            if not row:
                return None
            now = _utcnow()
            if row.expires_at and row.expires_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            if row.expires_at and row.expires_at < now:
                session.delete(row)
                session.commit()
                return None
            return {
                "content_type": row.mime_type,
                "data": row.image_data,
            }
        finally:
            close_session_safely(session)
    def save_emby_image_cache(
        self,
        cache_key: str,
        server_id: Optional[str],
        item_id: Optional[str],
        image_type: Optional[str],
        max_width: Optional[int],
        max_height: Optional[int],
        tag: Optional[str],
        scope: Optional[str],
        content_type: str,
        data: bytes,
        ttl_seconds: int,
        max_rows: int = 5000
    ) -> None:
        if not cache_key or not data:
            return
        cache_key = require_bounded_text(
            cache_key,
            field="cache_key",
            max_length=IMAGE_CACHE_KEY_MAX_LENGTH,
        )
        content_type = (
            project_persisted_text(content_type, IMAGE_CACHE_MIME_TYPE_MAX_LENGTH)
            or "application/octet-stream"
        )
        session = self._get_session()
        try:
            expires_at = _utcnow() + timedelta(seconds=max(ttl_seconds, 0))
            row = session.get(EmbyImageCache, cache_key)
            if not row:
                row = EmbyImageCache(cache_key=cache_key)
            # The schema intentionally stores opaque image bytes only.  Keep
            # the public cache API stable while mapping it to its actual model.
            row.image_url = f"cache://{cache_key}"  # type: ignore[assignment]
            row.mime_type = content_type  # type: ignore[assignment]
            row.image_data = data  # type: ignore[assignment]
            row.image_hash = hashlib.sha256(data).hexdigest()  # type: ignore[assignment]
            row.created_at = _utcnow()  # type: ignore[assignment]
            row.expires_at = expires_at  # type: ignore[assignment]
            session.add(row)

            # prune expired
            session.query(EmbyImageCache).filter(EmbyImageCache.expires_at < _utcnow()).delete(synchronize_session=False)  # type: ignore[attr-defined]

            if max_rows and max_rows > 0:
                total = session.query(func.count(EmbyImageCache.cache_key)).scalar()  # type: ignore[attr-defined]
                if total and total > max_rows:
                    overflow = int(total - max_rows)
                    old_rows = (
                        session.query(EmbyImageCache.cache_key)
                        .order_by(EmbyImageCache.created_at.asc())  # type: ignore[attr-defined]
                        .limit(overflow)
                        .all()
                    )
                    old_keys = [row_key for (row_key,) in old_rows]
                    if old_keys:
                        session.query(EmbyImageCache).filter(EmbyImageCache.cache_key.in_(old_keys)).delete(synchronize_session=False)  # type: ignore[attr-defined]

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio image cache: {exc}") from exc
        finally:
            close_session_safely(session)
