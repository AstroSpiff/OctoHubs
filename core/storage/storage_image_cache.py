"""Emby image cache storage operations."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, EmbyImageCache, _utcnow, func


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageImageCacheMixin(_SessionProvider):
    def load_emby_image_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if not cache_key:
            return None
        session = self._get_session()
        try:
            row = session.get(EmbyImageCache, cache_key)
            if not row:
                return None
            if row.expires_at and row.expires_at < _utcnow():
                session.delete(row)
                session.commit()
                return None
            return {
                "content_type": row.content_type,
                "data": row.data
            }
        finally:
            session.close()
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
        session = self._get_session()
        try:
            expires_at = _utcnow() + timedelta(seconds=max(ttl_seconds, 0))
            row = session.get(EmbyImageCache, cache_key)
            if not row:
                row = EmbyImageCache(cache_key=cache_key)
            row.server_id = server_id  # type: ignore[assignment]
            row.item_id = item_id  # type: ignore[assignment]
            row.image_type = image_type  # type: ignore[assignment]
            row.max_width = max_width  # type: ignore[assignment]
            row.max_height = max_height  # type: ignore[assignment]
            row.tag = tag  # type: ignore[assignment]
            row.scope = scope  # type: ignore[assignment]
            row.content_type = content_type  # type: ignore[assignment]
            row.data = data  # type: ignore[assignment]
            row.size = len(data)  # type: ignore[assignment]
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
            session.rollback()
            raise StorageError(f"Errore salvataggio image cache: {exc}") from exc
        finally:
            session.close()
