import logging
from typing import Dict, Any, Optional, Tuple, List, Callable

from core.log_sanitization import (
    format_exception_for_log,
    redact_mapping_for_log,
    sanitize_diagnostic_text,
)

from emby_users.operation_progress import emit_progress
from emby_users.mutation_coordinator import UserMutationCoordinator, server_mutation_key
from emby_users.settings_manager import USER_SETTINGS_SCHEMA
from emby_users.sync_results import SyncStepError, validate_sync_result
from emby_users.settings_scope import (
    build_allowed_fields,
    can_sync_config_field,
    can_sync_display_field,
    can_sync_policy_field,
    normalize_config_categories,
)

logger = logging.getLogger(__name__)


def _server_label(server: Optional[Dict[str, Any]]) -> str:
    if not server:
        return "server:<?>"
    name = server.get("alias") or server.get("name") or server.get("id") or "server"
    return f"{name} ({server.get('id')})"


class SyncManager:
    def __init__(
        self,
        storage,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_users_list: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        create_user: Callable[[Dict[str, Any], str], Tuple[bool, Dict[str, Any]]],
        playstate_sync: Callable[[str, str, List[tuple], bool], Dict[str, Any]],
        library_access_sync: Callable[[str, str, List[tuple]], Dict[str, Any]],
        favorites_sync: Callable[[str, str, List[tuple]], Dict[str, Any]],
        playlists_sync: Callable[[str, str, List[tuple]], Dict[str, Any]],
        link_clone_to_group: Callable[[str, str, Optional[str], str, str, Optional[str]], str],
        apply_config_patch: Callable[[str, str, Dict[str, Any], Optional[str]], Dict[str, Any]],
        fetch_user_display_preferences: Optional[
            Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]]
        ] = None,
        map_config_for_server: Optional[
            Callable[[Dict[str, Any], str, Optional[str]], Dict[str, Any]]
        ] = None,
        mutation_coordinator: UserMutationCoordinator | None = None,
    ):
        self.storage = storage
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_users_list = fetch_users_list
        self._fetch_user_display_preferences = fetch_user_display_preferences
        self._create_user = create_user
        self._playstate_sync = playstate_sync
        self._library_access_sync = library_access_sync
        self._favorites_sync = favorites_sync
        self._playlists_sync = playlists_sync
        self._link_clone_to_group = link_clone_to_group
        self._apply_config_patch = apply_config_patch
        self._map_config_for_server = map_config_for_server
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)

    def _backup_user(self, server: Dict[str, Any], user_id: str, reason: str) -> None:
        """
        Creates a DB backup of the user's current state.
        """
        details, err = self._fetch_user_details(server, user_id)
        if details:
            self.storage.create_user_backup(
                server["id"],
                user_id,
                details.get("Name", "Unknown"),
                f"full_{reason}",
                details
            )

    def sync_user_config(
        self,
        source_server_id: str,
        source_user_id: str,
        target_tuples: List[tuple],
        config_categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Copies Configuration and Policy from source to targets.
        target_tuples: list of (server_id, user_id)

        Server-specific library IDs are remapped through OctoHubs associations;
        unrelated protected fields remain excluded from the copy.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        src_details, err = self._fetch_user_details(source_server, source_user_id)
        if err or not src_details:
            return {"error": f"Failed to fetch source user: {err}"}

        src_policy = src_details.get("Policy", {})
        src_config = src_details.get("Configuration", {})
        if not isinstance(src_policy, dict):
            src_policy = {}
        if not isinstance(src_config, dict):
            src_config = {}
        src_display = {}
        if self._fetch_user_display_preferences:
            src_display, display_err = self._fetch_user_display_preferences(source_server, source_user_id)
            if display_err:
                logger.warning(
                    "[SYNC_CONFIG] Source DisplayPreferences unavailable: %s",
                    sanitize_diagnostic_text(display_err),
                )
                src_display = {}
        categories = normalize_config_categories(config_categories)
        allowed_policy, allowed_config, allowed_display = build_allowed_fields(USER_SETTINGS_SCHEMA, categories)
        policy_patch = {
            key: value
            for key, value in src_policy.items()
            if can_sync_policy_field(key, allowed_policy)
        }
        base_config_patch = {
            key: value
            for key, value in src_config.items()
            if can_sync_config_field(key, allowed_config)
        }
        src_custom = src_display.get("CustomPrefs") if isinstance(src_display, dict) else {}
        display_patch = {}
        if isinstance(src_custom, dict):
            display_patch = {
                str(key): value
                for key, value in src_custom.items()
                if can_sync_display_field(str(key), allowed_display)
            }

        results = {"success": [], "failed": [], "categories": sorted(categories)}

        for tgt_srv_id, tgt_uid in target_tuples:
            tgt_server = self._get_server_by_id(tgt_srv_id)
            if not tgt_server:
                results["failed"].append(f"Server {tgt_srv_id} not found")
                continue

            self._backup_user(tgt_server, tgt_uid, "full_sync_pre")
            config_patch = dict(base_config_patch)
            if config_patch and self._map_config_for_server:
                config_patch = self._map_config_for_server(
                    config_patch,
                    tgt_srv_id,
                    source_server_id,
                )

            apply_result = self._apply_config_patch(
                tgt_srv_id,
                tgt_uid,
                {
                    "policy": policy_patch,
                    "config": config_patch,
                    "display_preferences": display_patch,
                },
                source_server_id,
            )

            if apply_result.get("ok"):
                results["success"].append(f"{tgt_server['name']} ({tgt_uid})")
            else:
                results["failed"].append(
                    f"{tgt_server['name']}: Policy={apply_result.get('policy')}, "
                    f"Config={apply_result.get('config')}, "
                    f"Display={apply_result.get('display_preferences')}"
                )

        return results

    def clone_user(
        self,
        source_server_id: str,
        source_user_id: str,
        target_server_id: str,
        new_username: Optional[str] = None,
        sync_config: bool = True,
        sync_playstate: bool = True,
        sync_resume: bool = False,
        sync_library_access: bool = False,
        sync_favorites: bool = False,
        sync_playlists: bool = False,
        link_group: bool = False,
        config_categories: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        keys = {
            server_mutation_key(source_server_id),
            server_mutation_key(target_server_id),
        }
        with self._mutation_coordinator.guard(keys) as acquired:
            if not acquired:
                return {
                    "ok": False,
                    "busy": True,
                    "error": "Operazione utenti in corso sul server; riprova al termine.",
                }
            return self._clone_user_guarded(
                source_server_id,
                source_user_id,
                target_server_id,
                new_username,
                sync_config,
                sync_playstate,
                sync_resume,
                sync_library_access,
                sync_favorites,
                sync_playlists,
                link_group,
                config_categories,
                progress_callback,
            )

    def _clone_user_guarded(
        self,
        source_server_id: str,
        source_user_id: str,
        target_server_id: str,
        new_username: Optional[str] = None,
        sync_config: bool = True,
        sync_playstate: bool = True,
        sync_resume: bool = False,
        sync_library_access: bool = False,
        sync_favorites: bool = False,
        sync_playlists: bool = False,
        link_group: bool = False,
        config_categories: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Clones a user from source to target server.
        Creates the user if missing (matching by Name).
        Syncs Config, Policy and Playstate based on flags.
        """
        domain_failures: Dict[str, str] = {}
        successful_domains: list[str] = []

        logger.info(
            "[CLONE][1/4] Start: source_user_id=%s target_server_id=%s sync_config=%s sync_playstate=%s sync_resume=%s sync_library_access=%s sync_favorites=%s sync_playlists=%s link_group=%s",
            sanitize_diagnostic_text(source_user_id),
            sanitize_diagnostic_text(target_server_id),
            sync_config,
            sync_playstate,
            sync_resume,
            sync_library_access,
            sync_favorites,
            sync_playlists,
            link_group
        )
        total_steps = 3 + sum(
            (
                sync_config,
                sync_playstate,
                sync_library_access,
                sync_favorites,
                sync_playlists,
            )
        )
        current_step = 0
        emit_progress(
            progress_callback,
            "start",
            "Preparazione clonazione",
            current_step,
            total_steps,
            {"source_server_id": source_server_id, "source_user_id": source_user_id, "target_server_id": target_server_id},
        )

        src_server = self._get_server_by_id(source_server_id)
        tgt_server = self._get_server_by_id(target_server_id)
        if not src_server or not tgt_server:
            emit_progress(progress_callback, "error", "Server non trovato", total_steps, total_steps)
            return {"error": "Server not found"}

        src_user, err = self._fetch_user_details(src_server, source_user_id)
        if not src_user:
            emit_progress(progress_callback, "error", "Utente sorgente non trovato", total_steps, total_steps)
            return {"error": "Source user not found"}
        current_step += 1
        emit_progress(
            progress_callback,
            "source",
            f"Sorgente risolta: {src_user.get('Name') or source_user_id}",
            current_step,
            total_steps,
            {"source_username": src_user.get("Name")},
        )
        logger.info(
            "[CLONE][2/4] Source resolved: %s -> user=%s (%s)",
            sanitize_diagnostic_text(_server_label(src_server)),
            sanitize_diagnostic_text(src_user.get("Name")),
            sanitize_diagnostic_text(source_user_id),
        )

        target_username = new_username.strip() if new_username and new_username.strip() else src_user["Name"]
        if new_username and new_username.strip() and new_username.strip() != src_user.get("Name"):
            logger.info(
                "[CLONE][2/4] Target username override: '%s' -> '%s'",
                sanitize_diagnostic_text(src_user.get("Name")),
                sanitize_diagnostic_text(target_username),
            )

        tgt_user_id, target_created, target_error, current_step = self._resolve_clone_target(
            tgt_server,
            target_server_id,
            target_username,
            current_step,
            total_steps,
            progress_callback,
        )
        if target_error or tgt_user_id is None:
            return {"error": target_error or "Failed to resolve target user ID"}

        current_step = self._link_clone_group(
            enabled=link_group,
            source_server_id=source_server_id,
            source_user_id=source_user_id,
            source_username=src_user.get("Name"),
            target_server_id=target_server_id,
            target_user_id=tgt_user_id,
            target_username=target_username,
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
        )

        target = [(target_server_id, tgt_user_id)]
        res_config, current_step = self._clone_domain_step(
            enabled=sync_config,
            name="config",
            work=lambda: self.sync_user_config(
                source_server_id,
                source_user_id,
                target,
                config_categories=config_categories,
            ),
            start_log=(
                "[CLONE][3/4] Sync config: %s user=%s (%s) -> %s user=%s (%s)",
                _server_label(src_server), src_user.get("Name"), source_user_id,
                _server_label(tgt_server), target_username, tgt_user_id,
            ),
            skipped_log="[CLONE][3/4] Sync config skipped",
            success_message="Impostazioni copiate",
            failure_message="Copia impostazioni non riuscita",
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
        )
        res_play, current_step = self._clone_domain_step(
            enabled=sync_playstate,
            name="playstate",
            work=lambda: self._playstate_sync(
                source_server_id, source_user_id, target, sync_resume
            ),
            start_log=(
                "[CLONE][4/4] Sync playstate: %s user=%s (%s) -> %s user=%s (%s) resume=%s",
                _server_label(src_server), src_user.get("Name"), source_user_id,
                _server_label(tgt_server), target_username, tgt_user_id, sync_resume,
            ),
            skipped_log="[CLONE][4/4] Sync playstate skipped",
            success_message="Visti e resume copiati",
            failure_message="Copia visti e resume non riuscita",
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
            result_logger=self._log_clone_playstate_result,
        )
        res_library_access, current_step = self._clone_domain_step(
            enabled=sync_library_access,
            name="library_access",
            work=lambda: self._library_access_sync(
                source_server_id, source_user_id, target
            ),
            start_log=(
                "[CLONE][4/4] Sync library access: source=%s target=%s",
                source_user_id, tgt_user_id,
            ),
            skipped_log="[CLONE][4/4] Sync library access skipped",
            success_message="Accessi librerie copiati",
            failure_message="Copia accessi librerie non riuscita",
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
        )
        res_favorites, current_step = self._clone_domain_step(
            enabled=sync_favorites,
            name="favorites",
            work=lambda: self._favorites_sync(source_server_id, source_user_id, target),
            start_log=(
                "[CLONE][4/4] Sync favorites: source=%s target=%s",
                source_user_id, tgt_user_id,
            ),
            skipped_log="[CLONE][4/4] Sync favorites skipped",
            success_message="Preferiti copiati",
            failure_message="Copia preferiti non riuscita",
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
        )
        res_playlists, current_step = self._clone_domain_step(
            enabled=sync_playlists,
            name="playlists",
            work=lambda: self._playlists_sync(source_server_id, source_user_id, target),
            start_log=(
                "[CLONE][4/4] Sync playlists: source=%s target=%s",
                source_user_id, tgt_user_id,
            ),
            skipped_log="[CLONE][4/4] Sync playlists skipped",
            success_message="Playlist copiate",
            failure_message="Copia playlist non riuscita",
            failures=domain_failures,
            successes=successful_domains,
            current_step=current_step,
            total_steps=total_steps,
            progress_callback=progress_callback,
        )
        return self._clone_result(
            target_server_id=target_server_id,
            target_user_id=tgt_user_id,
            target_username=target_username,
            target_created=target_created,
            failures=domain_failures,
            successes=successful_domains,
            stats={
                "config_stats": res_config,
                "playstate_stats": res_play,
                "library_access_stats": res_library_access,
                "favorites_stats": res_favorites,
                "playlists_stats": res_playlists,
            },
            total_steps=total_steps,
            progress_callback=progress_callback,
        )

    def _resolve_clone_target(
        self,
        server: Dict[str, Any],
        server_id: str,
        username: str,
        current_step: int,
        total_steps: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> tuple[Optional[str], bool, Optional[str], int]:
        users, _ = self._fetch_users_list(server)
        matches = [
            user
            for user in users
            if user.get("Name", "").lower() == username.lower()
        ]
        self._log_duplicate_clone_targets(server, username, matches)
        target_user = matches[0] if matches else None
        created = target_user is None
        if created:
            logger.info(
                "[CLONE][2/4] Creating target user: %s -> user=%s",
                sanitize_diagnostic_text(_server_label(server)),
                sanitize_diagnostic_text(username),
            )
            ok, payload = self._create_user(server, username)
            if not ok:
                emit_progress(
                    progress_callback,
                    "error",
                    f"Creazione utente fallita: {username}",
                    total_steps,
                    total_steps,
                )
                return None, False, f"Failed to create user: {payload}", current_step
            target_user = payload

        target_user_id = target_user.get("Id") if isinstance(target_user, dict) else None
        logger.info(
            "[CLONE][2/4] Target %s: %s -> user=%s (%s)",
            "created" if created else "exists",
            sanitize_diagnostic_text(_server_label(server)),
            sanitize_diagnostic_text(username),
            sanitize_diagnostic_text(target_user_id),
        )
        current_step += 1
        emit_progress(
            progress_callback,
            "target",
            f"{'Creato utente destinazione' if created else 'Utente destinazione esistente'}: {username}",
            current_step,
            total_steps,
            {
                "target_server_id": server_id,
                "target_user_id": target_user_id,
                "target_username": username,
            },
        )
        if not target_user_id:
            emit_progress(
                progress_callback,
                "error",
                "ID utente destinazione non risolto",
                total_steps,
                total_steps,
            )
            return None, created, "Failed to resolve target user ID", current_step
        return str(target_user_id), created, None, current_step

    @staticmethod
    def _log_duplicate_clone_targets(
        server: Dict[str, Any],
        username: str,
        matches: List[Dict[str, Any]],
    ) -> None:
        if len(matches) <= 1:
            return
        logger.warning(
            "[CLONE][2/4] Multiple target users match name '%s' on %s: %s",
            sanitize_diagnostic_text(username),
            sanitize_diagnostic_text(_server_label(server)),
            sanitize_diagnostic_text([user.get("Id") for user in matches]),
        )

    def _link_clone_group(
        self,
        *,
        enabled: bool,
        source_server_id: str,
        source_user_id: str,
        source_username: Optional[str],
        target_server_id: str,
        target_user_id: str,
        target_username: str,
        failures: Dict[str, str],
        successes: list[str],
        current_step: int,
        total_steps: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> int:
        if enabled:
            try:
                group_id = self._link_clone_to_group(
                    source_server_id,
                    source_user_id,
                    source_username,
                    target_server_id,
                    target_user_id,
                    target_username,
                )
                if not group_id:
                    raise RuntimeError("Associazione al gruppo non confermata")
                logger.info(
                    "[CLONE][2/4] Linked target to source group: %s",
                    sanitize_diagnostic_text(group_id),
                )
                successes.append("group_link")
            except Exception as exc:
                logger.error(
                    "[CLONE][2/4] Failed to link target to group:\n%s",
                    format_exception_for_log(exc),
                )
                failures["group_link"] = "Associazione al gruppo non riuscita"
        else:
            logger.info("[CLONE][2/4] Group link skipped (link_group=False)")
        current_step += 1
        emit_progress(
            progress_callback,
            "group",
            "Associazione gruppo verificata",
            current_step,
            total_steps,
        )
        return current_step

    def _clone_domain_step(
        self,
        *,
        enabled: bool,
        name: str,
        work: Callable[[], Dict[str, Any]],
        start_log: tuple[Any, ...],
        skipped_log: str,
        success_message: str,
        failure_message: str,
        failures: Dict[str, str],
        successes: list[str],
        current_step: int,
        total_steps: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        result_logger: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> tuple[Optional[Dict[str, Any]], int]:
        if not enabled:
            logger.info("%s", sanitize_diagnostic_text(skipped_log))
            return None, current_step
        logger.info(
            sanitize_diagnostic_text(start_log[0]),
            *(
                value
                if isinstance(value, (bool, int, float)) or value is None
                else sanitize_diagnostic_text(value)
                for value in start_log[1:]
            ),
        )
        result = self._run_clone_domain(name, work, failures, successes)
        current_step += 1
        emit_progress(
            progress_callback,
            name,
            failure_message if name in failures else success_message,
            current_step,
            total_steps,
        )
        if result_logger is not None:
            result_logger(result)
        return result, current_step

    @staticmethod
    def _run_clone_domain(
        name: str,
        work: Callable[[], Dict[str, Any]],
        failures: Dict[str, str],
        successes: list[str],
    ) -> Dict[str, Any]:
        result: Any = None
        try:
            result = work()
            validate_sync_result(result)
        except SyncStepError as exc:
            failures[name] = str(exc)
            if SyncManager._has_structured_domain_success(result):
                successes.append(name)
            return result if isinstance(result, dict) else {"error": str(exc)}
        except Exception as exc:
            failures[name] = "Errore durante la copia"
            logger.error(
                "[CLONE] Domain %s failed:\n%s",
                sanitize_diagnostic_text(name),
                format_exception_for_log(exc),
            )
            return {"error": "Errore durante la copia"}
        successes.append(name)
        return result

    @staticmethod
    def _has_structured_domain_success(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        success = result.get("success")
        return isinstance(success, (list, tuple, set, dict)) and bool(success)

    @staticmethod
    def _log_clone_playstate_result(result: Dict[str, Any]) -> None:
        logger.info(
            "[CLONE][4/4] Sync playstate result: counts=%s resume=%s",
            redact_mapping_for_log(result.get("counts", {})),
            redact_mapping_for_log(result.get("resume_counts", {})),
        )

    @staticmethod
    def _clone_result(
        *,
        target_server_id: str,
        target_user_id: str,
        target_username: str,
        target_created: bool,
        failures: Dict[str, str],
        successes: list[str],
        stats: Dict[str, Optional[Dict[str, Any]]],
        total_steps: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> Dict[str, Any]:
        partial = bool(failures) and (target_created or bool(successes))
        result = {
            "ok": not failures,
            "status": "partial" if partial else "error" if failures else "success",
            "target_user_id": target_user_id,
            **stats,
            "failed_domains": failures,
        }
        if failures:
            result["partial"] = partial
            result["error"] = "Clonazione non completata per tutti i domini richiesti"
            emit_progress(
                progress_callback,
                "error",
                result["error"],
                total_steps,
                total_steps,
                {
                    "target_server_id": target_server_id,
                    "target_user_id": target_user_id,
                    "target_username": target_username,
                    "failed_domains": sorted(failures),
                },
            )
            return result
        emit_progress(
            progress_callback,
            "complete",
            f"Clonazione completata: {target_username}",
            total_steps,
            total_steps,
            {
                "target_server_id": target_server_id,
                "target_user_id": target_user_id,
                "target_username": target_username,
            },
        )
        return result
