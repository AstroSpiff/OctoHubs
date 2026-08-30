import logging
from typing import Dict, Any, Optional, Tuple, List, Callable

from .password_crypto import PasswordCipher, password_cipher_from_environment

logger = logging.getLogger(__name__)


class PasswordManager:
    def __init__(
        self,
        storage,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_group_users: Callable[[str], List[Tuple[str, str, Optional[str]]]],
        get_unlinked_group_id: Callable[[str, str], str],
        update_user_password: Callable[[Dict[str, Any], str, str], Tuple[bool, Optional[str]]],
    ):
        self.storage = storage
        self._get_server_by_id = get_server_by_id
        self._get_group_users = get_group_users
        self._get_unlinked_group_id = get_unlinked_group_id
        self._update_user_password = update_user_password
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
        """Decrypt one stored password and lazily rotate legacy ciphertexts."""
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
            group_id = self._get_unlinked_group_id(server_id, user_id)
        return self.get_group_password_info(group_id, include_password=include_password)

    def set_group_password(self, group_id: str, new_password: str) -> Dict[str, Any]:
        new_password = new_password or ""
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}

        logger.info("[PASSWORD] Apply: group=%s users=%s", group_id, len(users))
        failures = []
        applied = 0
        for server_id, user_id, _ in users:
            server = self._get_server_by_id(server_id)
            if not server:
                failures.append({"server_id": server_id, "user_id": user_id, "error": "Server not found"})
                continue
            ok, _ = self._update_user_password(server, user_id, new_password)
            if ok:
                applied += 1
            else:
                failures.append({"server_id": server_id, "user_id": user_id, "error": "Update failed"})

        if failures:
            logger.error("[PASSWORD] Group update failed for %s: %s", group_id, failures)
            return {"ok": False, "group_id": group_id, "applied": applied, "failed": failures}

        if new_password:
            enc = self.encrypt_password(new_password)
            self.storage.save_group_password(group_id, enc)
            # Overwrite per-user saved passwords to match the group
            for server_id, user_id, _ in users:
                self.storage.save_group_password(
                    self._get_unlinked_group_id(server_id, user_id),
                    enc
                )
            logger.info("[PASSWORD] Saved group password: %s", group_id)
        else:
            self.storage.delete_group_password(group_id)
            # Clear per-user saved passwords when group password is removed
            for server_id, user_id, _ in users:
                self.storage.delete_group_password(
                    self._get_unlinked_group_id(server_id, user_id)
                )
            logger.info("[PASSWORD] Cleared group password: %s", group_id)

        return {"ok": True, "group_id": group_id, "applied": applied, "failed": []}

    def update_user_password(self, server_id: str, user_id: str, new_password: str) -> Dict[str, Any]:
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

        user_password_id = self._get_unlinked_group_id(server_id, user_id)
        if new_password:
            enc = self.encrypt_password(new_password)
            self.storage.save_group_password(user_password_id, enc)
            logger.info("[PASSWORD] Saved user password: %s/%s", server_id, user_id)
        else:
            self.storage.delete_group_password(user_password_id)
            logger.info("[PASSWORD] Cleared user password: %s/%s", server_id, user_id)
        return {"ok": True}
