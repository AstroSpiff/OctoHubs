"""Creation and deletion flows for Emby users."""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Callable, Dict, List, Optional, Tuple

from emby_users.operation_progress import emit_progress
from emby_users.mutation_coordinator import (
    UserMutationCoordinator,
    group_sync_key,
    server_mutation_key,
    user_mutation_keys,
)
from core.log_sanitization import format_exception_for_log
from core.storage.field_limits import (
    EMBY_STORED_IDENTIFIER_MAX_LENGTH,
    require_bounded_text,
    require_emby_username,
)

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
        mutation_coordinator: UserMutationCoordinator | None = None,
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
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)

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
        target_list = list(targets or [])
        server_keys = {
            server_mutation_key(str(target.get("server_id") or "").strip())
            for target in target_list
            if isinstance(target, dict) and str(target.get("server_id") or "").strip()
        }
        with self._mutation_coordinator.guard(server_keys) as acquired:
            if not acquired:
                return {
                    "ok": False,
                    "busy": True,
                    "created": [],
                    "failed": [{"error": "Operazione utenti in corso sul server"}],
                    "group_id": None,
                }
            return self._create_users_guarded(
                target_list,
                settings,
                apply_libraries,
                password,
                link_group,
                group_name,
                progress_callback,
            )

    def _create_users_guarded(
        self,
        target_list: List[Dict[str, Any]],
        settings: Optional[Dict[str, Any]],
        apply_libraries: bool,
        password: str,
        link_group: bool,
        group_name: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Dict[str, Any]:
        created: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        total = len(target_list)
        last_username = ""
        emit_progress(progress_callback, "start", "Preparazione creazione utenti", 0, total)

        for index, target in enumerate(target_list, start=1):
            server_id = str(target.get("server_id") or "").strip()
            username = str(target.get("username") or target.get("name") or "").strip()
            last_username = username or last_username
            created_items, failed_items = self._create_target_user(
                server_id=server_id,
                username=username,
                password=password,
                index=index,
                total=total,
                progress_callback=progress_callback,
            )
            created.extend(created_items)
            failed.extend(failed_items)

        try:
            failed.extend(
                self._apply_initial_user_settings(
                    created, settings, apply_libraries, total, progress_callback
                )
            )
        except Exception as exc:
            logger.error(
                "[USERS] Initial settings persistence failed after user creation:\n%s",
                format_exception_for_log(exc),
            )
            failed.append({
                "stage": "settings",
                "error": "Utenti creati, impostazioni iniziali non completate",
            })

        group_id, link_failures = self._link_created_users(created, link_group, group_name)
        failed.extend(link_failures)
        ok = bool(created) and not failed
        status = "success" if ok else ("partial" if created else "error")

        emit_progress(
            progress_callback,
            "complete" if ok else "error",
            (
                f"Creazione completata: {last_username}"
                if ok and last_username
                else "Creazione completata"
                if ok
                else "Creazione parziale: verificare gli interventi richiesti"
                if created
                else "Creazione non riuscita"
            ),
            total,
            total,
            {"created": len(created), "failed": len(failed), "group_id": group_id},
        )
        return {
            "ok": ok,
            "status": status,
            "created": created,
            "failed": failed,
            "group_id": group_id,
            "reconciliation_required": bool(created and failed),
        }

    def _create_target_user(
        self,
        *,
        server_id: str,
        username: str,
        password: str,
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            server_id = require_bounded_text(
                server_id,
                field="server_id",
                max_length=EMBY_STORED_IDENTIFIER_MAX_LENGTH,
            )
            username = require_emby_username(username)
        except ValueError:
            return [], [self._creation_failure(
                server_id,
                username,
                "Target non valido",
                f"Target non valido: {username}",
                index,
                total,
                progress_callback,
            )]
        emit_progress(
            progress_callback,
            "create",
            f"Creo {username or 'utente'}",
            index - 1,
            total,
            {"server_id": server_id, "username": username},
        )
        if not server_id or not username:
            return [], [self._creation_failure(
                server_id,
                username,
                "Target non valido",
                f"Target non valido: {username}",
                index,
                total,
                progress_callback,
            )]

        server = self._get_server_by_id(server_id)
        if not server:
            return [], [self._creation_failure(
                server_id,
                username,
                "Server non trovato",
                f"Server non trovato: {server_id}",
                index,
                total,
                progress_callback,
            )]

        users, error = self._fetch_users_list(server)
        if error:
            message = f"Lista utenti non disponibile: {error}"
            return [], [self._creation_failure(
                server_id,
                username,
                message,
                f"Lista utenti non disponibile: {username}",
                index,
                total,
                progress_callback,
            )]
        existing = next(
            (
                user
                for user in users
                if str(user.get("Name") or "").lower() == username.lower()
            ),
            None,
        )
        pending_result = self._resume_pending_creation(
            server=server,
            server_id=server_id,
            username=username,
            password=password,
            existing=existing,
            index=index,
            total=total,
            progress_callback=progress_callback,
        )
        if pending_result is not None:
            return pending_result
        if existing is not None:
            return [], [self._creation_failure(
                server_id,
                username,
                "Utente gia esistente",
                f"Utente gia esistente: {username}",
                index,
                total,
                progress_callback,
            )]

        if not self.storage.reserve_emby_user_creation(server_id, username):
            return self._unresolved_creation_result(
                server,
                server_id,
                username,
                index,
                total,
                progress_callback,
                remote_created=False,
            )

        ok, payload = self._create_user(server, username, None)
        if not ok:
            self.storage.clear_emby_user_creation(server_id, username)
            message = payload or "Creazione fallita"
            return [], [self._creation_failure(
                server_id,
                username,
                message,
                f"Creazione fallita: {username}",
                index,
                total,
                progress_callback,
            )]

        self.storage.mark_emby_user_creation_remote(server_id, username)
        user_id = self._resolve_created_user_id(server, username, payload)
        if not user_id:
            return self._unresolved_creation_result(
                server,
                server_id,
                username,
                index,
                total,
                progress_callback,
                remote_created=True,
            )

        self.storage.clear_emby_user_creation(server_id, username)
        return self._finish_created_user(
            server,
            server_id,
            username,
            user_id,
            password,
            index,
            total,
            progress_callback,
        )

    def _resume_pending_creation(
        self,
        *,
        server: Dict[str, Any],
        server_id: str,
        username: str,
        password: str,
        existing: Optional[Dict[str, Any]],
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Optional[tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
        pending = self.storage.get_emby_user_creation(server_id, username)
        if pending is None:
            return None
        recovered_id = self._created_user_id(existing) if existing is not None else ""
        if recovered_id:
            self.storage.clear_emby_user_creation(server_id, username)
            return self._finish_created_user(
                server,
                server_id,
                username,
                recovered_id,
                password,
                index,
                total,
                progress_callback,
            )
        return self._unresolved_creation_result(
            server,
            server_id,
            username,
            index,
            total,
            progress_callback,
            remote_created=pending.get("status") == "remote_created",
        )

    def _unresolved_creation_result(
        self,
        server: Dict[str, Any],
        server_id: str,
        username: str,
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        *,
        remote_created: bool,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        message = (
            "Utente remoto creato; ID non ancora disponibile"
            if remote_created
            else "Creazione già prenotata; riconciliazione remota necessaria"
        )
        unresolved = {
            "server_id": server_id,
            "user_id": None,
            "username": username,
            "server_name": server.get("alias") or server.get("name") or server_id,
            "remote_created": remote_created,
            "identity_resolved": False,
        }
        failure = self._creation_failure(
            server_id,
            username,
            message,
            f"Creazione in riconciliazione: {username}",
            index,
            total,
            progress_callback,
        )
        failure.update({"stage": "identity", "remote_created": remote_created})
        return [unresolved], [failure]

    def _finish_created_user(
        self,
        server: Dict[str, Any],
        server_id: str,
        username: str,
        user_id: str,
        password: str,
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:

        created_item = {
            "server_id": server_id,
            "user_id": user_id,
            "username": username,
            "server_name": server.get("alias") or server.get("name") or server_id,
            "remote_created": True,
            "identity_resolved": True,
        }
        emit_progress(
            progress_callback,
            "create",
            f"Creato {username}",
            index,
            total,
            {"server_id": server_id, "user_id": user_id, "username": username},
        )
        try:
            password_failures = self._apply_created_user_password(
                created_item, password, index, total, progress_callback
            )
        except Exception as exc:
            logger.error(
                "[USERS] Password stage failed after user creation for %s/%s:\n%s",
                server_id,
                user_id,
                format_exception_for_log(exc),
            )
            password_failures = [{
                "server_id": server_id,
                "user_id": user_id,
                "username": username,
                "stage": "password",
                "error": "Utente creato, password non completata",
            }]
        return [created_item], password_failures

    def _resolve_created_user_id(
        self,
        server: Dict[str, Any],
        username: str,
        payload: Any,
    ) -> Optional[str]:
        user_id = self._created_user_id(payload)
        if user_id:
            return user_id
        users, _ = self._fetch_users_list(server)
        match = next(
            (
                user
                for user in users
                if str(user.get("Name") or "").lower() == username.lower()
            ),
            None,
        )
        return self._created_user_id(match)

    @staticmethod
    def _creation_failure(
        server_id: str,
        username: str,
        error: Any,
        progress_message: str,
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Dict[str, Any]:
        emit_progress(
            progress_callback,
            "create",
            progress_message,
            index,
            total,
        )
        return {"server_id": server_id, "username": username, "error": error}

    def _apply_created_user_password(
        self,
        created_item: Dict[str, Any],
        password: str,
        index: int,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> List[Dict[str, Any]]:
        if not password:
            return []
        username = created_item["username"]
        emit_progress(
            progress_callback,
            "password",
            f"Applico password a {username}",
            index,
            total,
        )
        result = self.password_manager.update_user_password(
            created_item["server_id"], created_item["user_id"], password
        )
        if result.get("ok"):
            return []
        return [{
            "server_id": created_item["server_id"],
            "user_id": created_item["user_id"],
            "username": username,
            "error": "Utente creato, password non applicata",
        }]

    def _apply_initial_user_settings(
        self,
        created: List[Dict[str, Any]],
        settings: Optional[Dict[str, Any]],
        apply_libraries: bool,
        total: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> List[Dict[str, Any]]:
        resolved = [item for item in created if item.get("user_id")]
        if not resolved or not self._has_settings(settings, apply_libraries):
            return []
        emit_progress(
            progress_callback,
            "settings",
            "Applico impostazioni iniziali",
            total,
            total,
        )
        result = self.settings_manager.apply_settings_to_users(
            resolved,
            settings or {},
            apply_libraries=apply_libraries,
        )
        return [{"error": str(item)} for item in result.get("failed") or []]

    def _link_created_users(
        self,
        created: List[Dict[str, Any]],
        link_group: bool,
        group_name: str,
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        resolved = [item for item in created if item.get("user_id")]
        if not link_group or len(resolved) <= 1:
            return None, []
        links = [
            {
                "server_id": item["server_id"],
                "user_id": item["user_id"],
                "username": item["username"],
                "is_leader": index == 0,
            }
            for index, item in enumerate(resolved)
        ]
        try:
            group_id = self.group_manager.link_users(links)
        except Exception as exc:
            logger.error(
                "[USERS] Linking newly created users failed:\n%s",
                format_exception_for_log(exc),
            )
            return None, [{
                "stage": "link",
                "error": "Utenti creati, collegamento del gruppo non completato",
            }]
        if group_name:
            try:
                self.group_manager.rename_group(group_id, group_name)
            except Exception as exc:
                logger.error(
                    "[USERS] Rename of newly linked group failed:\n%s",
                    format_exception_for_log(exc),
                )
                return group_id, [{
                    "stage": "rename",
                    "group_id": group_id,
                    "error": "Gruppo collegato, rinomina non completata",
                }]
        return group_id, []

    def delete_single_user(self, server_id: str, user_id: str, expected_name: str = "") -> Dict[str, Any]:
        with self._mutation_coordinator.guard(user_mutation_keys(server_id, user_id)) as user_acquired:
            if not user_acquired:
                return {"ok": False, "busy": True, "error": "Sincronizzazione del gruppo in corso; riprova al termine."}
            group_id = self._group_id_for_user(server_id, user_id)
            with self._group_sync_guard(group_id) as group_acquired:
                if not group_acquired:
                    return {"ok": False, "busy": True, "error": "Sincronizzazione del gruppo in corso; riprova al termine."}
                result = self._delete_user_from_emby(server_id, user_id, expected_name)
                if result.get("ok"):
                    cleanup_error = self._cleanup_user(
                        server_id,
                        user_id,
                        str(result.get("user", {}).get("username") or ""),
                    )
                    if cleanup_error:
                        return {**result, "ok": False, "partial": True, "cleanup_error": cleanup_error}
                return result

    def delete_group_users(self, group_id: str, expected_name: str = "") -> Dict[str, Any]:
        if not group_id or group_id == "owners":
            return {"ok": False, "error": "Gruppo non eliminabile"}

        initial_links = self.storage.get_user_links(group_id=group_id)
        if not initial_links and group_id.startswith("unlinked_"):
            parts = group_id[len("unlinked_"):].split("_", 1)
            if len(parts) == 2:
                initial_links = [{"server_id": parts[0], "user_id": parts[1], "username": None}]
        guard_keys = {
            group_sync_key(group_id),
            *(
                key
                for link in initial_links
                for key in user_mutation_keys(link.get("server_id"), link.get("user_id"))
            ),
        }
        with self._mutation_coordinator.guard(guard_keys) as acquired:
            if not acquired:
                return {"ok": False, "busy": True, "error": "Sincronizzazione del gruppo in corso; riprova al termine."}
            # Reload after acquiring the fence; a pre-lock snapshot can point to
            # users that have already moved to another group.
            links = self.storage.get_user_links(group_id=group_id)
            if not links and group_id.startswith("unlinked_"):
                parts = group_id[len("unlinked_"):].split("_", 1)
                if len(parts) == 2:
                    links = [{"server_id": parts[0], "user_id": parts[1], "username": None}]
            if not links:
                return {"ok": False, "error": "Gruppo senza utenti"}
            deleted, failed, cleanup_errors = self._delete_group_members(links)

            if not failed and not cleanup_errors:
                group_cleanup_error = self._cleanup_group(group_id)
                if group_cleanup_error:
                    cleanup_errors.append({"group_id": group_id, "error": group_cleanup_error})

        return {
            "ok": bool(deleted) and not failed and not cleanup_errors,
            "partial": bool(deleted) and bool(failed or cleanup_errors),
            "deleted": deleted,
            "failed": failed,
            "cleanup_errors": cleanup_errors,
            "group_id": group_id,
        }

    def _delete_group_members(
        self,
        links: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        deleted: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        cleanup_errors: List[Dict[str, Any]] = []
        for link in links:
            server_id = link.get("server_id")
            user_id = link.get("user_id")
            result = self._delete_user_from_emby(server_id, user_id)
            if result.get("ok"):
                deleted.append(result["user"])
                cleanup_error = self._cleanup_user(
                    server_id,
                    user_id,
                    str(result.get("user", {}).get("username") or ""),
                )
                if cleanup_error:
                    cleanup_errors.append({"server_id": server_id, "user_id": user_id, "error": cleanup_error})
                continue
            failed.append({
                "server_id": server_id,
                "user_id": user_id,
                "error": result.get("error") or "Eliminazione fallita",
            })
        return deleted, failed, cleanup_errors

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

    def _group_id_for_user(self, server_id: str, user_id: str) -> str:
        get_links = getattr(self.storage, "get_user_links", None)
        links = get_links(server_id=server_id, user_id=user_id) if callable(get_links) else []
        if links:
            return str(links[0].get("group_id") or self._get_unlinked_group_id(server_id, user_id))
        return self._get_unlinked_group_id(server_id, user_id)

    def _group_sync_guard(self, group_id: str):
        guard = getattr(self.group_manager, "sync_guard", None)
        return guard(group_id) if callable(guard) else nullcontext(True)

    def _cleanup_user(self, server_id: str, user_id: str, username: str = "") -> str:
        try:
            get_links = getattr(self.storage, "get_user_links", None)
            links = get_links(server_id=server_id, user_id=user_id) if callable(get_links) else []
            group_id = str(links[0].get("group_id") or "") if links else ""
            if group_id:
                for member in get_links(group_id=group_id):
                    if (member.get("server_id"), member.get("user_id")) == (server_id, user_id):
                        continue
                    self.password_manager.ensure_user_password_inherits_group(
                        group_id,
                        member["server_id"],
                        member["user_id"],
                    )
            atomic_cleanup = getattr(self.storage, "cleanup_deleted_emby_user", None)
            if callable(atomic_cleanup):
                atomic_cleanup(server_id, user_id, username)
                return ""
            self._cleanup_user_without_atomic_storage(
                server_id,
                user_id,
                username,
                group_id,
            )
            return ""
        except Exception as exc:
            logger.warning("[USERS] Cleanup failed for %s/%s:\n%s", server_id, user_id, format_exception_for_log(exc))
            return "Cleanup locale non completato"

    def _cleanup_user_without_atomic_storage(
        self,
        server_id: str,
        user_id: str,
        username: str,
        group_id: str,
    ) -> None:
        """Clean lightweight test/integration storage without a transaction API."""
        unlink_user = getattr(self.group_manager, "unlink_user", None)
        if callable(unlink_user):
            guarded_unlink = getattr(self.group_manager, "_unlink_user_guarded", None)
            if callable(guarded_unlink) and group_id:
                guarded_unlink(server_id, user_id, expected_group_id=group_id)
            else:
                unlink_user(server_id, user_id)
        else:
            self.storage.remove_user_link(server_id, user_id)
        self.storage.delete_key(self.settings_manager.settings_user_key(server_id, user_id))
        self.storage.delete_group_password(self._get_unlinked_group_id(server_id, user_id))
        self.storage.delete_icon_binding("user", f"{server_id}:{user_id}")
        clear_creation = getattr(self.storage, "clear_emby_user_creation", None)
        if username and callable(clear_creation):
            clear_creation(server_id, username)
        for domain in SYNC_STATE_DOMAINS:
            self.storage.delete_key(f"emby_user_sync_state:{domain}:{server_id}:{user_id}")

    def _cleanup_group(self, group_id: str) -> str:
        try:
            self.storage.delete_key(self.settings_manager.settings_group_key(group_id))
            self.storage.delete_key(f"group_settings:{group_id}")
            self.storage.delete_key(f"group_name:{group_id}")
            self.storage.delete_group_password(group_id)
            self.storage.delete_icon_binding("group", group_id)
            return ""
        except Exception as exc:
            logger.warning("[USERS] Group cleanup failed for %s:\n%s", group_id, format_exception_for_log(exc))
            return "Cleanup locale del gruppo non completato"

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
