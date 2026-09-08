import logging
from typing import Dict, Any, Optional, Tuple, List, Callable

from .password_crypto import PasswordCipher, password_cipher_from_environment
from .mutation_coordinator import UserMutationCoordinator, group_sync_key, user_mutation_keys
from core.log_sanitization import format_exception_for_log
from core.storage.field_limits import require_group_password_id

logger = logging.getLogger(__name__)


class PasswordManager:
    def __init__(
        self,
        storage,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_group_users: Callable[[str], List[Tuple[str, str, Optional[str]]]],
        get_unlinked_group_id: Callable[[str, str], str],
        update_user_password: Callable[[Dict[str, Any], str, str], Tuple[bool, Optional[str]]],
        mutation_coordinator: UserMutationCoordinator | None = None,
    ):
        self.storage = storage
        self._get_server_by_id = get_server_by_id
        self._get_group_users = get_group_users
        self._get_unlinked_group_id = get_unlinked_group_id
        self._update_user_password = update_user_password
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)
        self._password_cipher: Optional[PasswordCipher] = None

    def _get_password_cipher(self) -> PasswordCipher:
        if self._password_cipher is not None:
            return self._password_cipher
        self._password_cipher = password_cipher_from_environment()
        return self._password_cipher

    def encrypt_password(self, plaintext: str) -> str:
        cipher = self._get_password_cipher()
        return cipher.encrypt(plaintext)

    def decrypt_password(self, token: str) -> Optional[str]:
        plaintext, _needs_rotation = self._get_password_cipher().decrypt(token)
        if plaintext is None:
            logger.error("[PASSWORD] Decrypt failed")
            return None
        return plaintext

    def decrypt_saved_password(self, group_id: str, token: str) -> Optional[str]:
        """Decrypt one stored password and lazily rotate previous-key ciphertexts."""
        cipher = self._get_password_cipher()
        plaintext, needs_rotation = cipher.decrypt(token)
        if plaintext is None:
            logger.error("[PASSWORD] Decrypt failed for group=%s", group_id)
            return None
        if needs_rotation:
            self.storage.save_group_password(group_id, cipher.encrypt(plaintext))
            logger.info("[PASSWORD] Rotated stored password: group=%s", group_id)
        return plaintext

    def _get_user_password_entry(self, server_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self.storage.get_group_password(self._get_unlinked_group_id(server_id, user_id))

    def get_user_plain_password(self, server_id: str, user_id: str) -> Optional[str]:
        group_id = self._get_unlinked_group_id(server_id, user_id)
        entry = self.storage.get_group_password(group_id)
        if not entry or not entry.get("password_enc"):
            return None
        return self.decrypt_saved_password(group_id, entry["password_enc"])

    def ensure_user_password_inherits_group(self, group_id: str, server_id: str, user_id: str) -> None:
        group_entry = self.storage.get_group_password(group_id)
        if not group_entry or not group_entry.get("password_enc"):
            return
        user_entry = self._get_user_password_entry(server_id, user_id)
        if user_entry:
            return
        logger.info(
            "[PASSWORD] Skip inherit: no automatic password inheritance for user %s/%s",
            server_id,
            user_id
        )

    def get_group_password_info(self, group_id: str, *, include_password: bool = True) -> Dict[str, Any]:
        entry = self.storage.get_group_password(group_id)
        if not entry:
            logger.info("[PASSWORD] Read: group=%s saved=false", group_id)
            result = {"ok": True, "group_id": group_id, "saved": False, "updated_at": None}
            if include_password:
                result["password"] = None
            return result
        password = (
            self.decrypt_saved_password(group_id, entry["password_enc"])
            if entry.get("password_enc")
            else None
        )
        logger.info("[PASSWORD] Read: group=%s saved=%s", group_id, bool(password))
        result = {
            "ok": True,
            "group_id": group_id,
            "saved": bool(password),
            "updated_at": entry.get("updated_at")
        }
        if include_password:
            result["password"] = password
        return result

    def get_password_info(
        self,
        group_id: Optional[str] = None,
        server_id: Optional[str] = None,
        user_id: Optional[str] = None,
        *,
        include_password: bool = True,
    ) -> Dict[str, Any]:
        if not group_id:
            if not server_id or not user_id:
                return {"ok": False, "error": "Missing target"}
            if not self._get_server_by_id(server_id):
                return {"ok": False, "error": "Server not found"}
            group_id = self._get_unlinked_group_id(server_id, user_id)
        elif group_id.startswith("unlinked_"):
            # Synthetic IDs are storage details, not public group identities.
            # User-scoped reads must provide server_id + user_id so ownership
            # can be checked without parsing an ambiguous compound identifier.
            return {"ok": False, "error": "Invalid target"}
        elif not self._get_group_users(group_id):
            return {"ok": False, "error": "Group not found"}
        return self.get_group_password_info(group_id, include_password=include_password)

    def set_group_password(self, group_id: str, new_password: str) -> Dict[str, Any]:
        new_password = new_password or ""
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}

        keys = [
            group_sync_key(group_id),
            *(key for server_id, user_id, _ in users for key in user_mutation_keys(server_id, user_id)),
        ]
        with self._mutation_coordinator.guard(keys) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utenti già in corso", "group_id": group_id}
            current_users = self._get_group_users(group_id)
            if {(server_id, user_id) for server_id, user_id, _ in current_users} != {
                (server_id, user_id) for server_id, user_id, _ in users
            }:
                return {"ok": False, "busy": True, "error": "Il gruppo utenti è cambiato; riprova", "group_id": group_id}
            return self._set_group_password_guarded(group_id, new_password, current_users)

    def _set_group_password_guarded(
        self,
        group_id: str,
        new_password: str,
        users: List[Tuple[str, str, Optional[str]]],
    ) -> Dict[str, Any]:

        group_id = require_group_password_id(group_id)
        user_password_ids = {
            (server_id, user_id): require_group_password_id(
                self._get_unlinked_group_id(server_id, user_id)
            )
            for server_id, user_id, _ in users
        }
        logger.info("[PASSWORD] Apply: group=%s users=%s", group_id, len(users))
        failures = []
        applied = 0
        encrypted_password = self.encrypt_password(new_password) if new_password else None
        for server_id, user_id, _ in users:
            server = self._get_server_by_id(server_id)
            if not server:
                failures.append({"server_id": server_id, "user_id": user_id, "error": "Server not found"})
                continue
            ok, update_error = self._update_user_password(server, user_id, new_password)
            if ok:
                applied += 1
                user_password_id = user_password_ids[(server_id, user_id)]
                try:
                    if encrypted_password:
                        self.storage.save_group_password(user_password_id, encrypted_password)
                    else:
                        self.storage.delete_group_password(user_password_id)
                except Exception as exc:
                    logger.error(
                        "[PASSWORD] Local persistence failed after remote update for %s/%s:\n%s",
                        server_id,
                        user_id,
                        format_exception_for_log(exc),
                    )
                    failures.append({
                        "server_id": server_id,
                        "user_id": user_id,
                        "stage": "persistence",
                        "error": "Password applicata, persistenza locale non completata",
                    })
            else:
                failures.append({
                    "server_id": server_id,
                    "user_id": user_id,
                    "error": update_error or "Update failed",
                })

        if failures:
            logger.error("[PASSWORD] Group update failed for %s: %s", group_id, failures)
            return {
                "ok": False,
                "status": "partial" if applied else "error",
                "group_id": group_id,
                "applied": applied,
                "failed": failures,
                "reconciliation_required": bool(applied),
            }

        try:
            if new_password:
                self.storage.save_group_password(group_id, encrypted_password)
                logger.info("[PASSWORD] Saved group password: %s", group_id)
            else:
                self.storage.delete_group_password(group_id)
                logger.info("[PASSWORD] Cleared group password: %s", group_id)
        except Exception as exc:
            logger.error(
                "[PASSWORD] Group snapshot persistence failed after remote updates for %s:\n%s",
                group_id,
                format_exception_for_log(exc),
            )
            return {
                "ok": False,
                "status": "partial",
                "group_id": group_id,
                "applied": applied,
                "failed": [{
                    "group_id": group_id,
                    "stage": "persistence",
                    "error": "Password applicata, riepilogo del gruppo non salvato",
                }],
                "reconciliation_required": True,
            }

        return {"ok": True, "group_id": group_id, "applied": applied, "failed": []}

    def update_user_password(self, server_id: str, user_id: str, new_password: str) -> Dict[str, Any]:
        with self._mutation_coordinator.guard(user_mutation_keys(server_id, user_id)) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Operazione utente già in corso"}
            return self._update_user_password_guarded(server_id, user_id, new_password)

    def _update_user_password_guarded(self, server_id: str, user_id: str, new_password: str) -> Dict[str, Any]:
        user_password_id = require_group_password_id(
            self._get_unlinked_group_id(server_id, user_id)
        )
        server = self._get_server_by_id(server_id)
        if not server:
            return {"ok": False, "error": "Server not found"}
        logger.info(
            "[PASSWORD] Update requested: server=%s user=%s",
            server_id,
            user_id
        )
        ok, _ = self._update_user_password(server, user_id, new_password or "")
        if not ok:
            return {"ok": False, "error": "Update failed"}

        try:
            if new_password:
                enc = self.encrypt_password(new_password)
                self.storage.save_group_password(user_password_id, enc)
                logger.info("[PASSWORD] Saved user password: %s/%s", server_id, user_id)
            else:
                self.storage.delete_group_password(user_password_id)
                logger.info("[PASSWORD] Cleared user password: %s/%s", server_id, user_id)
        except Exception as exc:
            logger.error(
                "[PASSWORD] Local persistence failed after remote update for %s/%s:\n%s",
                server_id,
                user_id,
                format_exception_for_log(exc),
            )
            return {
                "ok": False,
                "status": "partial",
                "applied": 1,
                "failed": [{
                    "server_id": server_id,
                    "user_id": user_id,
                    "stage": "persistence",
                    "error": "Password applicata, persistenza locale non completata",
                }],
                "reconciliation_required": True,
            }
        return {"ok": True}
