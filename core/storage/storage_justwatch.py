"""JustWatch cache storage operations."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.storage.field_limits import require_justwatch_cache_key
from core.storage.storage_errors import StorageError
from core.storage.storage_session_cleanup import close_session_safely, rollback_session_safely
from core.storage.storage_models import SQLAlchemyError, JustWatchCache, _utcnow


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageJustWatchMixin(_SessionProvider):
    def get_justwatch_cache(
        self,
        show_name: str,
        season: int,
        episode: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached JustWatch availability data for a specific episode."""
        show_name = require_justwatch_cache_key(show_name)
        session = self._get_session()
        try:
            entry = (
                session.query(JustWatchCache)
                .filter(
                    JustWatchCache.show_name == show_name,  # type: ignore[attr-defined]
                    JustWatchCache.season == season,  # type: ignore[attr-defined]
                    JustWatchCache.episode == episode  # type: ignore[attr-defined]
                )
                .first()
            )
            if entry:
                return {
                    "show_name": entry.show_name,
                    "season": entry.season,
                    "episode": entry.episode,
                    "is_available": entry.is_available,
                    "providers": entry.providers,
                    "last_checked": entry.last_checked
                }
            return None
        finally:
            close_session_safely(session)

    def save_justwatch_cache(
        self,
        show_name: str,
        season: int,
        episode: int,
        is_available: bool,
        providers: Optional[list] = None
    ) -> None:
        """Save or update JustWatch availability data for an episode."""
        show_name = require_justwatch_cache_key(show_name)
        session = self._get_session()
        try:
            dialect_name = session.get_bind().dialect.name
            checked_at = _utcnow()
            values = {
                "show_name": show_name,
                "season": season,
                "episode": episode,
                "is_available": is_available,
                "providers": providers,
                "last_checked": checked_at,
            }
            if dialect_name in {"postgresql", "sqlite"}:
                insert_factory = (
                    postgresql_insert if dialect_name == "postgresql" else sqlite_insert
                )
                statement = insert_factory(JustWatchCache).values(**values)
                update_values = {
                    "is_available": statement.excluded.is_available,
                    "last_checked": statement.excluded.last_checked,
                }
                if providers is not None:
                    update_values["providers"] = statement.excluded.providers
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=("show_name", "season", "episode"),
                        set_=update_values,
                    )
                )
                session.commit()
                return

            entry = (
                session.query(JustWatchCache)
                .filter(
                    JustWatchCache.show_name == show_name,  # type: ignore[attr-defined]
                    JustWatchCache.season == season,  # type: ignore[attr-defined]
                    JustWatchCache.episode == episode  # type: ignore[attr-defined]
                )
                .first()
            )

            if entry:
                entry.is_available = is_available  # type: ignore[assignment]
                if providers is not None:
                    entry.providers = providers  # type: ignore[assignment]
                entry.last_checked = _utcnow()  # type: ignore[assignment]
            else:
                new_entry = JustWatchCache(
                    **values,
                )
                session.add(new_entry)

            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore salvataggio cache JustWatch: {exc}") from exc
        finally:
            close_session_safely(session)

    def clear_justwatch_cache(self, show_name: Optional[str] = None) -> int:
        """
        Clear JustWatch cache entries.

        Args:
            show_name: If provided, clear only entries for this show.
                      If None, clear all cache.

        Returns:
            Number of entries deleted
        """
        if show_name is not None:
            show_name = require_justwatch_cache_key(show_name)
        session = self._get_session()
        try:
            query = session.query(JustWatchCache)
            if show_name:
                query = query.filter(JustWatchCache.show_name == show_name)  # type: ignore[attr-defined]

            count = query.count()
            query.delete()
            session.commit()
            return count
        except SQLAlchemyError as exc:  # pragma: no cover
            rollback_session_safely(session)
            raise StorageError(f"Errore svuotamento cache JustWatch: {exc}") from exc
        finally:
            close_session_safely(session)

    def get_justwatch_cache_stats(self) -> Dict[str, int]:
        """Get statistics about JustWatch cache."""
        session = self._get_session()
        try:
            total = session.query(JustWatchCache).count()
            available = (
                session.query(JustWatchCache)
                .filter(JustWatchCache.is_available.is_(True))  # type: ignore[attr-defined]
                .count()
            )
            unavailable = (
                session.query(JustWatchCache)
                .filter(JustWatchCache.is_available.is_(False))  # type: ignore[attr-defined]
                .count()
            )

            return {
                "total": total,
                "available": available,
                "unavailable": unavailable
            }
        finally:
            close_session_safely(session)
