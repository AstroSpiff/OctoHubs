"""Creation and deletion flows for Emby users."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.operation_progress import emit_progress

logger = logging.getLogger(__name__)


SYNC_STATE_DOMAINS = ("settings", "playstate", "favorites", "playlists")


class UserLifecycleManager:
    def __init__(
        self,
        storage,
        settings_manager,
        password_manager,
        group_manager,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        get_unlinked_group_id: Callable[[str, str], str],
        fetch_users_list: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        create_user: Callable[[Dict[str, Any], str, Optional[str]], Tuple[bool, Any]],
        delete_user: Callable[[Dict[str, Any], str], Tuple[bool, Any]],
    ):
        self.storage = storage
        self.settings_manager = settings_manager
        self.password_manager = password_manager
        self.group_manager = group_manager
        self._get_server_by_id = get_server_by_id
        self._get_unlinked_group_id = get_unlinked_group_id
        self._fetch_users_list = fetch_users_list
        self._fetch_user_details = fetch_user_details
        self._create_user = create_user
        self._delete_user = delete_user

    def create_users(
        self,
        targets: List[Dict[str, Any]],
        settings: Optional[Dict[str, Any]] = None,
        apply_libraries: bool = False,
        password: str = "",
        link_group: bool = False,
        group_name: str = "",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        created: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        target_list = list(targets or [])
        total = len(target_list)
        last_username = ""
        emit_progress(progress_callback, "start", "Preparazione creazione utenti", 0, total)

        for index, target in enumerate(target_list, start=1):
            server_id = str(target.get("server_id") or "").strip()
            username = str(target.get("username") or target.get("name") or "").strip()
            last_username = username or last_username
            emit_progress(
                progress_callback,
                "create",
                f"Creo {username or 'utente'}",
                index - 1,
                total,
                {"server_id": server_id, "username": username},
            )
            if not server_id or not username:
                failed.append({"server_id": server_id, "username": username, "error": "Target non valido"})
                emit_progress(progress_callback, "create", f"Target non valido: {username}", index, total)
                continue

            server = self._get_server_by_id(server_id)
            if not server:
                failed.append({"server_id": server_id, "username": username, "error": "Server non trovato"})
                emit_progress(progress_callback, "create", f"Server non trovato: {server_id}", index, total)
                continue

            users, err = self._fetch_users_list(server)
            if err:
                failed.append({"server_id": server_id, "username": username, "error": f"Lista utenti non disponibile: {err}"})
                emit_progress(progress_callback, "create", f"Lista utenti non disponibile: {username}", index, total)
                continue
            if any(str(user.get("Name") or "").lower() == username.lower() for user in users):
                failed.append({"server_id": server_id, "username": username, "error": "Utente gia esistente"})
                emit_progress(progress_callback, "create", f"Utente gia esistente: {username}", index, total)
                continue

            ok, payload = self._create_user(server, username, None)
            if not ok:
                failed.append({"server_id": server_id, "username": username, "error": payload or "Creazione fallita"})
                emit_progress(progress_callback, "create", f"Creazione fallita: {username}", index, total)
                continue

            user_id = self._created_user_id(payload)
            if not user_id:
                users_after, _ = self._fetch_users_list(server)
                match = next((user for user in users_after if str(user.get("Name") or "").lower() == username.lower()), None)
                user_id = self._created_user_id(match)
            if not user_id:
                failed.append({"server_id": server_id, "username": username, "error": "ID nuovo utente non trovato"})
                emit_progress(progress_callback, "create", f"ID nuovo utente non trovato: {username}", index, total)
                continue

            created_item = {
                "server_id": server_id,
                "user_id": user_id,
                "username": username,
                "server_name": server.get("alias") or server.get("name") or server_id,
            }
            created.append(created_item)
            emit_progress(
                progress_callback,
                "create",
                f"Creato {username}",
                index,
                total,
                {"server_id": server_id, "user_id": user_id, "username": username},
            )

            if password:
                emit_progress(progress_callback, "password", f"Applico password a {username}", index, total)
                pass_result = self.password_manager.update_user_password(server_id, user_id, password)
                if not pass_result.get("ok"):
                    failed.append({
                        "server_id": server_id,
                        "user_id": user_id,
                        "username": username,
                        "error": "Utente creato, password non applicata",
                    })

        if created and self._has_settings(settings, apply_libraries):
            emit_progress(progress_callback, "settings", "Applico impostazioni iniziali", total, total)
            apply_result = self.settings_manager.apply_settings_to_users(
                created,
                settings or {},
                apply_libraries=apply_libraries,
            )
            for item in apply_result.get("failed") or []:
                failed.append({"error": str(item)})

        group_id = None
        if link_group and len(created) > 1:
            links = []
            for idx, item in enumerate(created):
                links.append({
                    "server_id": item["server_id"],
                    "user_id": item["user_id"],
                    "username": item["username"],
                    "is_leader": idx == 0,
                })
            group_id = self.group_manager.link_users(links)
            if group_name:
                self.group_manager.rename_group(group_id, group_name)

        emit_progress(
            progress_callback,
            "complete",
            f"Creazione completata: {last_username}" if last_username else "Creazione completata",
            total,
            total,
            {"created": len(created), "failed": len(failed), "group_id": group_id},
        )
        return {
            "ok": bool(created) and not failed,
            "created": created,
            "failed": failed,
            "group_id": group_id,
        }

    def delete_single_user(self, server_id: str, user_id: str, expected_name: str = "") -> Dict[str, Any]:
        result = self._delete_user_from_emby(server_id, user_id, expected_name)
        if result.get("ok"):
            self._cleanup_user(server_id, user_id)
        return result

    def delete_group_users(self, group_id: str, expected_name: str = "") -> Dict[str, Any]:
        if not group_id or group_id == "owners":
            return {"ok": False, "error": "Gruppo non eliminabile"}

        links = self.storage.get_user_links(group_id=group_id)
        if not links and group_id.startswith("unlinked_"):
            parts = group_id[len("unlinked_"):].split("_", 1)
            if len(parts) == 2:
                links = [{"server_id": parts[0], "user_id": parts[1], "username": None}]
        if not links:
            return {"ok": False, "error": "Gruppo senza utenti"}

        deleted: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for link in links:
            server_id = link.get("server_id")
            user_id = link.get("user_id")
            result = self._delete_user_from_emby(server_id, user_id)
            if result.get("ok"):
                deleted.append(result["user"])
                self._cleanup_user(server_id, user_id)
            else:
                failed.append({
                    "server_id": server_id,
                    "user_id": user_id,
                    "error": result.get("error") or "Eliminazione fallita",
                })

        if not failed:
            self._cleanup_group(group_id)

        return {
            "ok": bool(deleted) and not failed,
            "deleted": deleted,
            "failed": failed,
            "group_id": group_id,
        }

    def _delete_user_from_emby(self, server_id: str, user_id: str, expected_name: str = "") -> Dict[str, Any]:
        server = self._get_server_by_id(server_id)
        if not server:
            return {"ok": False, "error": "Server non trovato"}

        details, err = self._fetch_user_details(server, user_id)
        if err or not details:
            return {"ok": False, "error": f"Utente non trovato: {err}"}

        name = str(details.get("Name") or "")
        if expected_name and expected_name.strip().lower() != name.lower():
            return {"ok": False, "error": "Nome conferma non corrisponde"}
        if self._is_protected_user(details):
            return {"ok": False, "error": "Utente protetto: gli amministratori non vengono eliminati"}

        ok, payload = self._delete_user(server, user_id)
        if not ok:
            return {"ok": False, "error": payload or "Eliminazione Emby fallita"}

        return {
            "ok": True,
            "user": {
                "server_id": server_id,
                "user_id": user_id,
                "username": name,
                "server_name": server.get("alias") or server.get("name") or server_id,
            },
        }

    def _cleanup_user(self, server_id: str, user_id: str) -> None:
        try:
            self.storage.remove_user_link(server_id, user_id)
            self.storage.delete_key(self.settings_manager.settings_user_key(server_id, user_id))
            self.storage.delete_group_password(self._get_unlinked_group_id(server_id, user_id))
            self.storage.delete_icon_binding("user", f"{server_id}:{user_id}")
            for domain in SYNC_STATE_DOMAINS:
                self.storage.delete_key(f"emby_user_sync_state:{domain}:{server_id}:{user_id}")
        except Exception as exc:  # pragma: no cover
            logger.warning("[USERS] Cleanup failed for %s/%s: %s", server_id, user_id, exc)

    def _cleanup_group(self, group_id: str) -> None:
        try:
            self.storage.delete_key(self.settings_manager.settings_group_key(group_id))
            self.storage.delete_key(f"group_settings:{group_id}")
            self.storage.delete_key(f"group_name:{group_id}")
            self.storage.delete_group_password(group_id)
            self.storage.delete_icon_binding("group", group_id)
        except Exception as exc:  # pragma: no cover
            logger.warning("[USERS] Group cleanup failed for %s: %s", group_id, exc)

    def _created_user_id(self, payload: Any) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        user_id = payload.get("Id") or payload.get("id") or payload.get("UserId")
        if not user_id and isinstance(payload.get("User"), dict):
            user = payload["User"]
            user_id = user.get("Id") or user.get("id") or user.get("UserId")
        return str(user_id) if user_id else None

    def _has_settings(self, settings: Optional[Dict[str, Any]], apply_libraries: bool) -> bool:
        if apply_libraries:
            return True
        if not isinstance(settings, dict):
            return False
        for scope in ("policy", "config", "display_preferences"):
            value = settings.get(scope)
            if isinstance(value, dict) and value:
                return True
        return False

    def _is_protected_user(self, details: Dict[str, Any]) -> bool:
        policy = details.get("Policy") if isinstance(details, dict) else {}
        if not isinstance(policy, dict):
            policy = {}
        return bool(policy.get("IsAdministrator"))
