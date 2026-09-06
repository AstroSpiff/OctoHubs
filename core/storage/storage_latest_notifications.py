"""Persistent idempotency ledger for Latest notification deliveries."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from core.storage.storage_errors import StorageError
from core.storage.storage_locks import lock_latest_refresh
from core.storage.storage_models import (
    AppSettings,
    EmbyLatestNotificationDelivery,
    SQLAlchemyError,
    _utcnow,
)


class _SessionProvider(Protocol):
    def _get_session(self) -> Any: ...


class StorageLatestNotificationMixin(_SessionProvider):
    _LATEST_NOTIFICATION_CLAIM_LEASE = timedelta(minutes=15)
    _LATEST_NOTIFICATION_RETENTION = timedelta(days=90)
    _LATEST_NOTIFICATION_UNKNOWN_RETENTION = timedelta(days=365)

    @staticmethod
    def _notification_server_exists(session: Any, server_id: str) -> bool:
        if session.get_bind().dialect.name != "postgresql":
            # SQLite is retained only for isolated unit tests and does not
            # provide the shared advisory-lock/delete contract.
            return True
        settings = session.get(AppSettings, 1)
        if settings is None or not isinstance(settings.data, dict):
            # Compatibility for isolated storage tests and pre-seed upgrades.
            return True
        emby = settings.data.get("EMBY")
        servers = emby.get("SERVERS") if isinstance(emby, dict) else None
        if not isinstance(servers, list):
            return True
        return any(
            isinstance(server, dict)
            and str(server.get("id") or "") == str(server_id or "")
            for server in servers
        )

    def _prune_latest_notification_deliveries(self, session: Any, now) -> int:
        sent_or_failed_before = now - self._LATEST_NOTIFICATION_RETENTION
        unknown_before = now - self._LATEST_NOTIFICATION_UNKNOWN_RETENTION
        deleted = session.query(EmbyLatestNotificationDelivery).filter(
            (
                EmbyLatestNotificationDelivery.status.in_(("sent", "failed"))
                & (EmbyLatestNotificationDelivery.updated_at < sent_or_failed_before)
            )
            | (
                (EmbyLatestNotificationDelivery.status == "unknown")
                & (EmbyLatestNotificationDelivery.updated_at < unknown_before)
            )
        ).delete(synchronize_session=False)
        return int(deleted or 0)

    def prune_latest_notification_deliveries(self) -> int:
        """Remove old delivery outcomes while retaining unknowns for reconciliation."""
        session = self._get_session()
        try:
            deleted = self._prune_latest_notification_deliveries(session, _utcnow())
            session.commit()
            return deleted
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore pulizia consegne notifiche Latest: {exc}") from exc
        finally:
            session.close()

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
            lock_latest_refresh(session)
            if not self._notification_server_exists(session, server_id):
                session.rollback()
                return "server_deleted"
            self._prune_latest_notification_deliveries(session, now)
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

            # A process may have died after the provider accepted a message but
            # before the ledger was completed. Never resend that message
            # automatically: move the abandoned claim to an explicit unknown
            # state so an operator can reconcile/reset it without double sends.
            stale_before = now - self._LATEST_NOTIFICATION_CLAIM_LEASE
            session.query(EmbyLatestNotificationDelivery).filter(
                EmbyLatestNotificationDelivery.delivery_key == delivery_key,
                EmbyLatestNotificationDelivery.status == "claimed",
                EmbyLatestNotificationDelivery.claimed_at < stale_before,
            ).update(
                {
                    "status": "unknown",
                    "last_error": "Esito consegna sconosciuto dopo interruzione del worker",
                    "updated_at": now,
                },
                synchronize_session=False,
            )
            session.commit()

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
            if row is not None and row.status in {"sent", "unknown"}:
                return str(row.status)
            return "in_progress"
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
            lock_latest_refresh(session)
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
            lock_latest_refresh(session)
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

    def reset_latest_notification_deliveries(self) -> int:
        """Explicitly clear the ledger as part of the operator reset workflow."""
        session = self._get_session()
        try:
            deleted = session.query(EmbyLatestNotificationDelivery).delete(
                synchronize_session=False,
            )
            session.commit()
            return int(deleted or 0)
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError(f"Errore reset consegne notifiche Latest: {exc}") from exc
        finally:
            session.close()


__all__ = ["StorageLatestNotificationMixin"]
