"""RSS storage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from core.storage.storage_errors import StorageError
from core.storage.storage_models import SQLAlchemyError, RssItem, CategoryBlacklist, CategoryHidden, _utcnow, func, or_


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageRssMixin(_SessionProvider):
    def save_rss_items(self, items: list[Dict[str, Any]], dedup_keep: str = "newest") -> Dict[str, int]:
        """Insert or update RSS items, deduplicating by link."""
        import re
        import html

        session = self._get_session()
        dedup_keep = "oldest" if dedup_keep == "oldest" else "newest"
        counts = {"inserted": 0, "updated": 0, "skipped": 0, "removed": 0}

        try:
            def ensure_aware(value: Optional[datetime]) -> datetime:
                if value is None:
                    return _utcnow()
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)

            for item in items:
                link = (item.get("link") or "").strip()
                if not link:
                    counts["skipped"] += 1
                    continue

                # Check if any category is blacklisted (split composite categories)
                import re
                import html
                categories = item.get("categories") or []
                if isinstance(categories, list):
                    is_blacklisted = False
                    for cat in categories:
                        if isinstance(cat, str):
                            # Split composite categories by ',' and '/'
                            parts = re.split(r'[,/]', cat)
                            for part in parts:
                                cleaned = html.unescape(part.strip())  # Decode HTML entities
                                if cleaned and self.is_category_blacklisted(cleaned):
                                    is_blacklisted = True
                                    break
                            if is_blacklisted:
                                break
                    if is_blacklisted:
                        counts["skipped"] += 1
                        continue

                existing = (
                    session.query(RssItem)
                    .filter(RssItem.link == link)  # type: ignore[attr-defined]
                    .all()
                )

                def entry_time(entry: Any) -> datetime:
                    return ensure_aware(entry.updated_at or entry.published_at or entry.ingested_at)

                def payload_time(payload: Dict[str, Any]) -> datetime:
                    return ensure_aware(
                        payload.get("updated_at")
                        or payload.get("published_at")
                        or payload.get("ingested_at")
                        or _utcnow()
                    )

                def apply_payload(target: Any, payload: Dict[str, Any]) -> None:
                    target.source_name = payload.get("source_name")  # type: ignore[assignment]
                    target.source_url = payload.get("source_url")  # type: ignore[assignment]
                    target.source_tags = payload.get("source_tags")  # type: ignore[assignment]
                    target.title = payload.get("title")  # type: ignore[assignment]
                    target.link = link  # type: ignore[assignment]
                    target.guid = payload.get("guid")  # type: ignore[assignment]
                    target.author = payload.get("author")  # type: ignore[assignment]
                    target.summary = payload.get("summary")  # type: ignore[assignment]
                    target.content = payload.get("content")  # type: ignore[assignment]
                    target.categories = payload.get("categories")  # type: ignore[assignment]
                    target.published_at = payload.get("published_at")  # type: ignore[assignment]
                    target.updated_at = payload.get("updated_at")  # type: ignore[assignment]
                    target.ingested_at = payload.get("ingested_at") or _utcnow()  # type: ignore[assignment]
                    target.extra = payload.get("extra")  # type: ignore[assignment]

                if not existing:
                    entry = RssItem()
                    apply_payload(entry, item)
                    session.add(entry)
                    counts["inserted"] += 1
                    continue

                ordered = sorted(existing, key=entry_time)
                keep_entry = ordered[0] if dedup_keep == "oldest" else ordered[-1]
                candidate_time = payload_time(item)
                keep_time = entry_time(keep_entry)
                should_update = (
                    candidate_time < keep_time
                    if dedup_keep == "oldest"
                    else candidate_time > keep_time
                )
                if should_update:
                    apply_payload(keep_entry, item)
                    counts["updated"] += 1
                else:
                    counts["skipped"] += 1

                for entry in existing:
                    if entry.id != keep_entry.id:
                        session.delete(entry)
                        counts["removed"] += 1

            session.commit()
            return counts
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore salvataggio RSS: {exc}") from exc
        finally:
            session.close()

    def dedupe_rss_items(self, dedup_keep: str = "newest") -> Dict[str, int]:
        """Remove duplicate RSS items by link."""
        session = self._get_session()
        dedup_keep = "oldest" if dedup_keep == "oldest" else "newest"
        removed = 0
        try:
            def ensure_aware(value: Optional[datetime]) -> datetime:
                if value is None:
                    return _utcnow()
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)

            duplicates = (
                session.query(RssItem.link)  # type: ignore[attr-defined]
                .filter(RssItem.link.isnot(None))  # type: ignore[attr-defined]
                .group_by(RssItem.link)  # type: ignore[attr-defined]
                .having(func.count(RssItem.link) > 1)  # type: ignore[attr-defined]
                .all()
            )
            for (link,) in duplicates:
                entries = (
                    session.query(RssItem)
                    .filter(RssItem.link == link)  # type: ignore[attr-defined]
                    .all()
                )
                if len(entries) < 2:
                    continue
                entries = sorted(entries, key=lambda entry: ensure_aware(entry.updated_at or entry.published_at or entry.ingested_at))
                keep_entry = entries[0] if dedup_keep == "oldest" else entries[-1]
                for entry in entries:
                    if entry.id != keep_entry.id:
                        session.delete(entry)
                        removed += 1
            session.commit()
            return {"removed": removed, "links": len(duplicates)}
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore deduplica RSS: {exc}") from exc
        finally:
            session.close()

    def list_rss_items(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """List RSS items with pagination."""
        session = self._get_session()
        try:
            total = session.query(RssItem).count()
            ordering = func.coalesce(
                RssItem.published_at,  # type: ignore[attr-defined]
                RssItem.updated_at,  # type: ignore[attr-defined]
                RssItem.ingested_at  # type: ignore[attr-defined]
            ).desc()
            query = session.query(RssItem).order_by(ordering)
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            entries = query.all()

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            items = [
                {
                    "id": entry.id,
                    "source_name": entry.source_name,
                    "source_url": entry.source_url,
                    "source_tags": entry.source_tags,
                    "title": entry.title,
                    "link": entry.link,
                    "guid": entry.guid,
                    "author": entry.author,
                    "summary": entry.summary,
                    "content": entry.content,
                    "categories": entry.categories,
                    "published_at": to_iso(entry.published_at),
                    "updated_at": to_iso(entry.updated_at),
                    "ingested_at": to_iso(entry.ingested_at)
                }
                for entry in entries
            ]
            return {"total": total, "items": items}
        finally:
            session.close()

    def search_rss_items(self, keywords: str, limit: int = 50, offset: int = 0, use_regex: bool = False, search_in: str = "all") -> Dict[str, Any]:
        """Search RSS items by keywords in title, summary, and content.

        Args:
            keywords: Search pattern (literal text or regex pattern)
            limit: Max results to return
            offset: Offset for pagination
            use_regex: If True, treat keywords as regex pattern (PostgreSQL ~* operator)
            search_in: Where to search - "all", "title", "summary", "content"
        """
        session = self._get_session()
        try:
            # Determina i campi in cui cercare
            search_fields = []
            if search_in == "all":
                search_fields = [RssItem.title, RssItem.summary, RssItem.content]
            elif search_in == "title":
                search_fields = [RssItem.title]
            elif search_in == "summary":
                search_fields = [RssItem.summary]
            elif search_in == "content":
                search_fields = [RssItem.content]
            else:
                # Default a "all" se valore non valido
                search_fields = [RssItem.title, RssItem.summary, RssItem.content]

            # Costruisci filtro di ricerca
            if use_regex:
                # Usa operatore regex PostgreSQL ~* (case-insensitive)
                filters = [field.op('~*')(keywords) for field in search_fields]  # type: ignore[attr-defined]
                query = session.query(RssItem).filter(or_(*filters))
            else:
                # Ricerca normale con ILIKE
                search_filter = f"%{keywords}%"
                filters = [field.ilike(search_filter) for field in search_fields]  # type: ignore[attr-defined]
                query = session.query(RssItem).filter(or_(*filters))

            total = query.count()

            ordering = func.coalesce(
                RssItem.published_at,  # type: ignore[attr-defined]
                RssItem.updated_at,  # type: ignore[attr-defined]
                RssItem.ingested_at  # type: ignore[attr-defined]
            ).desc()
            query = query.order_by(ordering)

            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)
            entries = query.all()

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            items = [
                {
                    "id": entry.id,
                    "source_name": entry.source_name,
                    "source_url": entry.source_url,
                    "source_tags": entry.source_tags,
                    "title": entry.title,
                    "link": entry.link,
                    "guid": entry.guid,
                    "author": entry.author,
                    "summary": entry.summary,
                    "content": entry.content,
                    "categories": entry.categories,
                    "published_at": to_iso(entry.published_at),
                    "updated_at": to_iso(entry.updated_at),
                    "ingested_at": to_iso(entry.ingested_at)
                }
                for entry in entries
            ]
            return {"total": total, "items": items}
        finally:
            session.close()

    def delete_rss_items(self, item_ids: List[int]) -> int:
        """Delete RSS items by IDs. Returns count of deleted items."""
        if not item_ids:
            return 0

        session = self._get_session()
        try:
            deleted_count = session.query(RssItem).filter(
                RssItem.id.in_(item_ids)  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante eliminazione items RSS: {exc}")
        finally:
            session.close()

    def add_category_to_blacklist(self, category_name: str) -> bool:
        """Add a category to the blacklist. Returns True if added, False if already exists."""
        if not category_name or not category_name.strip():
            return False

        session = self._get_session()
        try:
            existing = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first()

            if existing:
                return False

            new_entry = CategoryBlacklist(category_name=category_name.strip())  # type: ignore[call-arg]
            session.add(new_entry)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante aggiunta categoria alla blacklist: {exc}")
        finally:
            session.close()

    def remove_category_from_blacklist(self, category_name: str) -> bool:
        """Remove a category from the blacklist. Returns True if removed, False if not found."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            deleted_count = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count > 0
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante rimozione categoria dalla blacklist: {exc}")
        finally:
            session.close()

    def list_blacklisted_categories(self) -> List[Dict[str, Any]]:
        """List all blacklisted categories."""
        session = self._get_session()
        try:
            entries = session.query(CategoryBlacklist).order_by(CategoryBlacklist.category_name).all()  # type: ignore[attr-defined]

            def to_iso(value: Optional[datetime]) -> Optional[str]:
                if value is None:
                    return None
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc).isoformat()

            return [
                {
                    "id": entry.id,
                    "category_name": entry.category_name,
                    "added_at": to_iso(entry.added_at)
                }
                for entry in entries
            ]
        finally:
            session.close()

    def is_category_blacklisted(self, category_name: str) -> bool:
        """Check if a category is blacklisted."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            exists = session.query(CategoryBlacklist).filter(
                CategoryBlacklist.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first() is not None
            return exists
        finally:
            session.close()

    def add_category_to_hidden(self, category_name: str) -> bool:
        """Add a category to hidden list. Returns True if added, False if already exists."""
        if not category_name:
            return False

        category_name = category_name.strip()
        session = self._get_session()
        try:
            # Check if already exists
            existing = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name  # type: ignore[attr-defined]
            ).first()

            if existing:
                return False

            # Add new entry
            entry = CategoryHidden()  # type: ignore[misc]
            entry.category_name = category_name  # type: ignore[attr-defined]
            entry.added_at = _utcnow()  # type: ignore[attr-defined]
            session.add(entry)
            session.commit()
            return True
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore aggiunta categoria a hidden: {exc}") from exc
        finally:
            session.close()

    def remove_category_from_hidden(self, category_name: str) -> bool:
        """Remove a category from hidden list. Returns True if removed, False if not found."""
        if not category_name:
            return False

        category_name = category_name.strip()
        session = self._get_session()
        try:
            deleted = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name  # type: ignore[attr-defined]
            ).delete()
            session.commit()
            return deleted > 0
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            raise StorageError(f"Errore rimozione categoria da hidden: {exc}") from exc
        finally:
            session.close()

    def list_hidden_categories(self) -> List[Dict[str, Any]]:
        """List all hidden categories with their timestamps."""
        session = self._get_session()
        try:
            entries = session.query(CategoryHidden).order_by(CategoryHidden.category_name).all()  # type: ignore[attr-defined]
            return [
                {
                    "category_name": entry.category_name,
                    "added_at": entry.added_at.isoformat() if entry.added_at else None
                }
                for entry in entries
            ]
        finally:
            session.close()

    def is_category_hidden(self, category_name: str) -> bool:
        """Check if a category is hidden."""
        if not category_name:
            return False

        session = self._get_session()
        try:
            exists = session.query(CategoryHidden).filter(
                CategoryHidden.category_name == category_name.strip()  # type: ignore[attr-defined]
            ).first() is not None
            return exists
        finally:
            session.close()

    def get_all_categories_with_counts(self) -> Dict[str, Any]:
        """Get all categories from RSS items with article counts, plus blacklisted categories.
        Composite categories (containing ',' or '/') are split into individual categories.
        HTML entities are decoded (e.g., &amp; -> &)."""
        import re
        import html

        session = self._get_session()
        try:
            # Ottieni tutti gli ID degli items per tracciare quali item hanno una categoria
            items = session.query(RssItem.id, RssItem.categories).all()
            category_item_ids: Dict[str, set] = {}  # category_name -> set of item IDs

            for item in items:
                if item.categories:
                    item_id = item.id
                    for cat in item.categories:
                        if cat:
                            # Split composite categories by ',' and '/'
                            parts = re.split(r'[,/]', cat)
                            for part in parts:
                                cleaned = html.unescape(part.strip())  # Decode HTML entities
                                if cleaned:
                                    if cleaned not in category_item_ids:
                                        category_item_ids[cleaned] = set()
                                    category_item_ids[cleaned].add(item_id)

            # Convert to counts
            category_counts = {cat: len(ids) for cat, ids in category_item_ids.items()}

            # Ottieni categorie blacklistate e nascoste
            blacklist_entries = session.query(CategoryBlacklist).all()
            blacklisted = {entry.category_name for entry in blacklist_entries}

            hidden_entries = session.query(CategoryHidden).all()
            hidden = {entry.category_name for entry in hidden_entries}

            # Costruisci risultato
            categories = []
            for cat_name, count in sorted(category_counts.items()):
                categories.append({
                    "name": cat_name,
                    "count": count,
                    "blacklisted": cat_name in blacklisted,
                    "hidden": cat_name in hidden
                })

            # Aggiungi categorie blacklistate senza articoli
            for cat_name in sorted(blacklisted):
                if cat_name not in category_counts:
                    categories.append({
                        "name": cat_name,
                        "count": 0,
                        "blacklisted": True,
                        "hidden": cat_name in hidden
                    })

            # Aggiungi categorie nascoste senza articoli
            for cat_name in sorted(hidden):
                if cat_name not in category_counts and cat_name not in blacklisted:
                    categories.append({
                        "name": cat_name,
                        "count": 0,
                        "blacklisted": False,
                        "hidden": True
                    })

            return {
                "categories": categories,
                "total_categories": len(categories),
                "blacklisted_count": len(blacklisted),
                "hidden_count": len(hidden)
            }
        finally:
            session.close()

    def delete_items_by_categories(self, category_names: List[str]) -> int:
        """Delete all RSS items that have any of the specified categories (including composite categories).
        Returns count of deleted items."""
        import re
        import html

        if not category_names:
            return 0

        session = self._get_session()
        try:
            # Trova tutti gli item che hanno almeno una delle categorie specificate
            items_to_delete = []
            for item in session.query(RssItem).all():
                if item.categories:
                    should_delete = False
                    for cat in item.categories:
                        # Split composite categories by ',' and '/'
                        parts = re.split(r'[,/]', cat)
                        for part in parts:
                            cleaned = html.unescape(part.strip())  # Decode HTML entities
                            if cleaned in category_names:
                                should_delete = True
                                break
                        if should_delete:
                            break
                    if should_delete:
                        items_to_delete.append(item.id)

            if not items_to_delete:
                return 0

            deleted_count = session.query(RssItem).filter(
                RssItem.id.in_(items_to_delete)  # type: ignore[attr-defined]
            ).delete(synchronize_session=False)
            session.commit()
            return deleted_count
        except Exception as exc:
            session.rollback()
            raise StorageError(f"Errore durante eliminazione items per categoria: {exc}")
        finally:
            session.close()
