"""Telegram delivery phase for Latest publication notifications."""

from __future__ import annotations

import logging

from core.safe_output import safe_print as print
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.log_sanitization import sanitize_diagnostic_text


logger = logging.getLogger(__name__)


@dataclass
class DeliveryOutcome:
    errors: List[str]
    sent: int = 0
    failed: int = 0
    claim_skips: int = 0
    state_updates: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sent_signatures: set = field(default_factory=set)
    last_send: float = 0.0

    def throttle(self, minimum_interval: float = 1.1) -> None:
        elapsed = time.monotonic() - self.last_send
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)
        self.last_send = time.monotonic()

    def result(self) -> Dict[str, Any]:
        summary = f"Notifiche inviate: {self.sent}." if self.sent else "Nessuna notifica inviata."
        if self.claim_skips and not self.sent and not self.failed and not self.errors:
            summary = "Nessuna notifica da inviare: consegne già registrate o in corso."
        if self.failed:
            summary = f"{summary} Errori: {self.failed}."
        if self.errors:
            summary = f"{summary} Avvisi: {len(self.errors)}."
        complete = not self.failed and not self.errors
        success = complete and bool(self.sent or self.claim_skips)
        status = "success" if success else ("partial" if self.sent or self.claim_skips else "error")
        return {
            "success": success,
            "status": status,
            "message": summary,
            "sent": self.sent,
            "failed": self.failed,
            "errors": self.errors,
        }


class NotificationDeliveryMixin:
    """Deliver planned rule runs while preserving destination idempotency."""

    dep: Any
    db_storage: Any
    config: Dict[str, Any]

    def _publication_signature(self, item: Dict[str, Any]) -> str:
        raise NotImplementedError

    def _publication_state_key(self, item: Dict[str, Any]) -> str:
        raise NotImplementedError

    def _destination_key(self, bot_id: Any, chat_id: Any) -> str:
        raise NotImplementedError

    def _notification_send_order_key(self, item: Dict[str, Any]) -> tuple:
        raise NotImplementedError

    def _item_state_entry(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def _destination_notified(
        self,
        entry: Optional[Dict[str, Any]],
        item: Dict[str, Any],
        key: str,
    ) -> bool:
        raise NotImplementedError

    def _deliver_rule_runs(self, rule_runs: List[Dict[str, Any]], outcome: DeliveryOutcome) -> None:
        for run in rule_runs:
            template = run.get("template") or self.dep.default_template()
            name = str(run.get("name") or run.get("id") or "Regola")
            items = sorted(run.get("items") or [], key=self._notification_send_order_key)
            for item in items:
                self._deliver_item(item, name, template, run.get("recipients") or [], outcome)

    def _deliver_item(
        self,
        item: Dict[str, Any],
        rule_name: str,
        template: str,
        recipients: List[Dict[str, Any]],
        outcome: DeliveryOutcome,
    ) -> None:
        signature = self._publication_signature(item)
        if not signature:
            return
        message_parts = self._message_parts(item, rule_name, template, outcome)
        if message_parts is None:
            return
        message, image_url = message_parts
        update = outcome.state_updates.setdefault(signature, {
            "item": item,
            "publication_key": self._publication_state_key(item),
            "delivered": {},
            "required": set(),
        })
        photo_state = {"attempted": False, "photo": None, "error": ""}
        state_entry = self._item_state_entry(item)
        for recipient in recipients:
            self._deliver_recipient(
                item, signature, message, image_url, recipient, state_entry, update, photo_state, outcome
            )

    def _message_parts(
        self,
        item: Dict[str, Any],
        rule_name: str,
        template: str,
        outcome: DeliveryOutcome,
    ) -> Optional[Tuple[str, str]]:
        result = self.dep.build_message(item, template, return_error=True)
        if not isinstance(result, tuple) or len(result) not in (2, 3):
            return None
        message, image_url = result[:2]
        template_error = result[2] if len(result) == 3 else None
        if template_error:
            title = item.get("title") or item.get("series_name") or item.get("item_id") or "contenuto"
            logger.warning(
                "[LATEST_NOTIFY] template failed rule=%s title=%s detail=%s",
                sanitize_diagnostic_text(rule_name),
                sanitize_diagnostic_text(title),
                sanitize_diagnostic_text(template_error),
            )
            outcome.errors.append(
                f"Errore template regola '{sanitize_diagnostic_text(rule_name)}' "
                f"per '{sanitize_diagnostic_text(title)}'"
            )
            outcome.failed += 1
            return None
        return (message, image_url) if message or image_url else None

    def _recipient_values(self, recipient: Any) -> Optional[Tuple[Any, Any, Any, str]]:
        if not isinstance(recipient, dict):
            return None
        token = recipient.get("token")
        bot_id = recipient.get("bot_id")
        chat_id = recipient.get("chat_id")
        key = recipient.get("destination_key") or self._destination_key(bot_id, chat_id)
        return (token, bot_id, chat_id, key) if token and chat_id and key else None

    def _deliver_recipient(
        self,
        item: Dict[str, Any],
        signature: str,
        message: str,
        image_url: str,
        recipient: Any,
        state_entry: Optional[Dict[str, Any]],
        update: Dict[str, Any],
        photo_state: Dict[str, Any],
        outcome: DeliveryOutcome,
    ) -> None:
        values = self._recipient_values(recipient)
        if values is None:
            return
        token, bot_id, chat_id, key = values
        update["required"].add(key)
        if self._destination_notified(state_entry, item, key):
            return
        delivery_signature = (signature, str(bot_id), str(chat_id))
        if delivery_signature in outcome.sent_signatures:
            print(f"   -> [NOTIFY] Skip duplicato: {item.get('title', 'Unknown')} (già notificato al destinatario)")
            return
        claim = self._claim(item, signature, key, outcome)
        if claim is None:
            return
        if not self._prepare_photo(image_url, item, claim, photo_state, outcome):
            return
        ok, error = self._send_telegram(token, chat_id, message, photo_state.get("photo"), outcome)
        self._record_delivery(
            ok, error, claim, key, bot_id, chat_id, delivery_signature, update, outcome
        )

    def _claim(self, item: Dict[str, Any], signature: str, key: str, outcome: DeliveryOutcome) -> Any:
        try:
            claim = self.dep.claim_delivery(
                self.db_storage,
                publication_signature=signature,
                destination_key=key,
                server_id=str(item.get("server_id") or ""),
            )
        except Exception as exc:
            logger.warning(
                "[LATEST_NOTIFY] delivery claim failed: %s",
                sanitize_diagnostic_text(exc),
            )
            outcome.failed += 1
            outcome.errors.append("Errore prenotazione notifica")
            return None
        if not claim.acquired:
            outcome.claim_skips += 1
            return None
        return claim

    def _prepare_photo(
        self,
        image_url: str,
        item: Dict[str, Any],
        claim: Any,
        photo_state: Dict[str, Any],
        outcome: DeliveryOutcome,
    ) -> bool:
        if image_url and not photo_state["attempted"]:
            photo_state["photo"] = self.dep.prepare_photo(image_url, item, self.config)
            photo_state["attempted"] = True
            photo_state["error"] = photo_state["photo"].error
        if not photo_state["error"]:
            return True
        title = item.get("title") or item.get("series_name") or item.get("item_id") or "contenuto"
        logger.warning(
            "[LATEST_NOTIFY] image unavailable title=%s detail=%s",
            sanitize_diagnostic_text(title),
            sanitize_diagnostic_text(photo_state["error"]),
        )
        error = f"Immagine non disponibile per '{sanitize_diagnostic_text(title)}'"
        self._fail_claim(claim, error, outcome)
        outcome.errors.append(error)
        outcome.failed += 1
        return False

    @staticmethod
    def _text_payload(chat_id: Any, message: str) -> Dict[str, Any]:
        preview_enabled = "http://" in message or "https://" in message
        return {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": not preview_enabled,
        }

    def _send_once(self, token: str, chat_id: Any, message: str, photo: Any) -> Tuple[bool, str, Dict[str, Any]]:
        if photo:
            return self.dep.send_photo(self.dep.telegram_request, token, chat_id, message, photo)
        return self.dep.telegram_request(token, "sendMessage", self._text_payload(chat_id, message))

    def _send_telegram(
        self,
        token: str,
        chat_id: Any,
        message: str,
        photo: Any,
        outcome: DeliveryOutcome,
    ) -> Tuple[bool, str]:
        outcome.throttle()
        ok, error, params = self._send_once(token, chat_id, message, photo)
        retry_after = params.get("retry_after") if not ok and isinstance(params, dict) else None
        if isinstance(retry_after, (int, float)) and retry_after > 0:
            time.sleep(float(retry_after) + 0.2)
            outcome.throttle()
            ok, error, _params = self._send_once(token, chat_id, message, photo)
        return ok, error

    def _fail_claim(self, claim: Any, error: str, outcome: DeliveryOutcome) -> None:
        try:
            self.dep.fail_delivery(self.db_storage, claim, error)
        except Exception as exc:
            logger.warning(
                "[LATEST_NOTIFY] release claim failed: %s",
                sanitize_diagnostic_text(exc),
            )
            outcome.errors.append("Errore rilascio claim notifica")

    def _record_delivery(
        self,
        ok: bool,
        error: str,
        claim: Any,
        key: str,
        bot_id: Any,
        chat_id: Any,
        delivery_signature: tuple,
        update: Dict[str, Any],
        outcome: DeliveryOutcome,
    ) -> None:
        if not ok:
            safe_error = "Errore invio Telegram"
            if error:
                logger.warning(
                    "[LATEST_NOTIFY] Telegram delivery failed: %s",
                    sanitize_diagnostic_text(error),
                )
            self._fail_claim(claim, safe_error, outcome)
            outcome.failed += 1
            outcome.errors.append(safe_error)
            return
        try:
            self.dep.complete_delivery(self.db_storage, claim)
        except Exception as exc:
            logger.warning(
                "[LATEST_NOTIFY] completion claim failed: %s",
                sanitize_diagnostic_text(exc),
            )
            outcome.errors.append("Notifica inviata ma claim non completato")
        outcome.sent += 1
        update["delivered"][key] = {"bot_id": str(bot_id), "chat_id": str(chat_id)}
        outcome.sent_signatures.add(delivery_signature)
