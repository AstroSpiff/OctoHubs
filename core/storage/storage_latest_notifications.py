"""Persistent idempotency ledger for Latest notification deliveries."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from core.storage.storage_errors import StorageError
from core.storage.storage_models import (
    EmbyLatestNotificationDelivery,
    SQLAlchemyError,
    _utcnow,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageLatestNotificationMixin(_SessionProvider):
    def claim_latest_notification_delivery(
        self,
        *,
        delivery_key: str,
        server_id: str,
        publication_key: str,
        destination_key: str,
        claim_token: str,
    ) -> str:
        """Claim a delivery once, or report its already-persisted state."""
        session = self._get_session()
        now = _utcnow()
        try:
            session.add(
                EmbyLatestNotificationDelivery(
                    delivery_key=delivery_key,
                    server_id=server_id,
                    publication_key=publication_key,
                    destination_key=destination_key,
                    status="claimed",
                    claim_token=claim_token,
                    claimed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                session.commit()
                return "acquired"
            except IntegrityError:
                session.rollback()

            updated = (
                session.query(EmbyLatestNotificationDelivery)
                .filter(
                    EmbyLatestNotificationDelivery.delivery_key == delivery_key,
                    EmbyLatestNotificationDelivery.status == "failed",
                )
                .update(
                    {
                        "status": "claimed",
                        "claim_token": claim_token,
                        "claimed_at": now,
                        "failed_at": None,
                        "last_error": None,
                        "updated_at": now,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            if updated:
                return "acquired"

            row = session.get(EmbyLatestNotificationDelivery, delivery_key)
            return "sent" if row is not None and row.status == "sent" else "in_progress"
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore claim notifica Latest: {exc}") from exc
        finally:
            session.close()

    def complete_latest_notification_delivery(
        self,
        *,
        delivery_key: str,
        claim_token: str,
    ) -> bool:
        """Complete only the claim owned by the caller."""
        session = self._get_session()
        now = _utcnow()
        try:
            updated = (
                session.query(EmbyLatestNotificationDelivery)
                .filter(
                    EmbyLatestNotificationDelivery.delivery_key == delivery_key,
                    EmbyLatestNotificationDelivery.status == "claimed",
                    EmbyLatestNotificationDelivery.claim_token == claim_token,
                )
                .update(
                    {
                        "status": "sent",
                        "sent_at": now,
                        "updated_at": now,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return bool(updated)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore completamento notifica Latest: {exc}") from exc
        finally:
            session.close()

    def fail_latest_notification_delivery(
        self,
        *,
        delivery_key: str,
        claim_token: str,
        error: str,
    ) -> bool:
        """Make a confirmed failed delivery claim available for a later retry."""
        session = self._get_session()
        now = _utcnow()
        try:
            updated = (
                session.query(EmbyLatestNotificationDelivery)
                .filter(
                    EmbyLatestNotificationDelivery.delivery_key == delivery_key,
                    EmbyLatestNotificationDelivery.status == "claimed",
                    EmbyLatestNotificationDelivery.claim_token == claim_token,
                )
                .update(
                    {
                        "status": "failed",
                        "failed_at": now,
                        "last_error": str(error or "")[:2000] or None,
                        "updated_at": now,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return bool(updated)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore rilascio notifica Latest: {exc}") from exc
        finally:
            session.close()


__all__ = ["StorageLatestNotificationMixin"]
