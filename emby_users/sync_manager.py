import logging
from typing import Dict, Any, Optional, Tuple, List, Callable

from emby_users.operation_progress import emit_progress
from emby_users.settings_manager import USER_SETTINGS_SCHEMA
from emby_users.settings_scope import (
    build_allowed_fields,
    can_sync_config_field,
    can_sync_display_field,
    can_sync_policy_field,
    normalize_config_categories,
)

logger = logging.getLogger(__name__)


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

        Server-specific library IDs are remapped through OctoHub associations;
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
                logger.warning("[SYNC_CONFIG] Source DisplayPreferences unavailable: %s", display_err)
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
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Clones a user from source to target server.
        Creates the user if missing (matching by Name).
        Syncs Config, Policy and Playstate based on flags.
        """
        def _srv_label(srv: Optional[Dict[str, Any]]) -> str:
            if not srv:
                return "server:<?>"
            name = srv.get("alias") or srv.get("name") or srv.get("id") or "server"
            return f"{name} ({srv.get('id')})"

        logger.info(
            "[CLONE][1/4] Start: source_user_id=%s target_server_id=%s sync_config=%s sync_playstate=%s sync_resume=%s sync_library_access=%s sync_favorites=%s sync_playlists=%s link_group=%s",
            source_user_id,
            target_server_id,
            sync_config,
            sync_playstate,
            sync_resume,
            sync_library_access,
            sync_favorites,
            sync_playlists,
            link_group
        )
        enabled_domains = [
            enabled for enabled in [
                sync_config,
                sync_playstate,
                sync_library_access,
                sync_favorites,
                sync_playlists,
            ]
            if enabled
        ]
        total_steps = 3 + len(enabled_domains)
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
            _srv_label(src_server),
            src_user.get("Name"),
            source_user_id
        )

        target_username = new_username.strip() if new_username and new_username.strip() else src_user["Name"]
        if new_username and new_username.strip() and new_username.strip() != src_user.get("Name"):
            logger.info(
                "[CLONE][2/4] Target username override: '%s' -> '%s'",
                src_user.get("Name"),
                target_username
            )

        tgt_users, _ = self._fetch_users_list(tgt_server)
        target_matches = [u for u in tgt_users if u.get("Name", "").lower() == target_username.lower()]
        target_user = target_matches[0] if target_matches else None
        if len(target_matches) > 1:
            try:
                ids = [u.get("Id") for u in target_matches]
                logger.warning(
                    "[CLONE][2/4] Multiple target users match name '%s' on %s: %s",
                    target_username,
                    _srv_label(tgt_server),
                    ids
                )
            except Exception:
                pass

        tgt_user_id = None
        if target_user:
            tgt_user_id = target_user["Id"]
            logger.info(
                "[CLONE][2/4] Target exists: %s -> user=%s (%s)",
                _srv_label(tgt_server),
                target_user.get("Name"),
                tgt_user_id
            )
            current_step += 1
            emit_progress(
                progress_callback,
                "target",
                f"Utente destinazione esistente: {target_username}",
                current_step,
                total_steps,
                {"target_server_id": target_server_id, "target_user_id": tgt_user_id, "target_username": target_username},
            )
        else:
            logger.info(
                "[CLONE][2/4] Creating target user: %s -> user=%s",
                _srv_label(tgt_server),
                target_username
            )
            ok, res = self._create_user(tgt_server, target_username)
            if not ok:
                emit_progress(progress_callback, "error", f"Creazione utente fallita: {target_username}", total_steps, total_steps)
                return {"error": f"Failed to create user: {res}"}
            tgt_user_id = res.get("Id")
            logger.info(
                "[CLONE][2/4] Target created: %s -> user=%s (%s)",
                _srv_label(tgt_server),
                target_username,
                tgt_user_id
            )
            current_step += 1
            emit_progress(
                progress_callback,
                "target",
                f"Creato utente destinazione: {target_username}",
                current_step,
                total_steps,
                {"target_server_id": target_server_id, "target_user_id": tgt_user_id, "target_username": target_username},
            )

        if not tgt_user_id:
            emit_progress(progress_callback, "error", "ID utente destinazione non risolto", total_steps, total_steps)
            return {"error": "Failed to resolve target user ID"}

        if link_group:
            try:
                group_id = self._link_clone_to_group(
                    source_server_id,
                    source_user_id,
                    src_user.get("Name"),
                    target_server_id,
                    tgt_user_id,
                    target_username
                )
                logger.info(
                    "[CLONE][2/4] Linked target to source group: %s",
                    group_id
                )
            except Exception as exc:
                logger.error("[CLONE][2/4] Failed to link target to group: %s", exc)
        else:
            logger.info("[CLONE][2/4] Group link skipped (link_group=False)")
        current_step += 1
        emit_progress(progress_callback, "group", "Associazione gruppo verificata", current_step, total_steps)

        if sync_config:
            logger.info(
                "[CLONE][3/4] Sync config: %s user=%s (%s) -> %s user=%s (%s)",
                _srv_label(src_server),
                src_user.get("Name"),
                source_user_id,
                _srv_label(tgt_server),
                target_username,
                tgt_user_id
            )
            self.sync_user_config(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)],
                config_categories=config_categories
            )
            current_step += 1
            emit_progress(progress_callback, "config", "Impostazioni copiate", current_step, total_steps)
        else:
            logger.info("[CLONE][3/4] Sync config skipped")

        res_play = None
        if sync_playstate:
            logger.info(
                "[CLONE][4/4] Sync playstate: %s user=%s (%s) -> %s user=%s (%s) resume=%s",
                _srv_label(src_server),
                src_user.get("Name"),
                source_user_id,
                _srv_label(tgt_server),
                target_username,
                tgt_user_id,
                sync_resume
            )
            res_play = self._playstate_sync(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)],
                sync_resume
            )
            current_step += 1
            emit_progress(progress_callback, "playstate", "Visti e resume copiati", current_step, total_steps)
            try:
                counts = res_play.get("counts", {}) if isinstance(res_play, dict) else {}
                resume_counts = res_play.get("resume_counts", {}) if isinstance(res_play, dict) else {}
                logger.info(
                    "[CLONE][4/4] Sync playstate result: counts=%s resume=%s",
                    counts,
                    resume_counts
                )
            except Exception:
                pass
        else:
            logger.info("[CLONE][4/4] Sync playstate skipped")

        res_library_access = None
        if sync_library_access:
            logger.info("[CLONE][4/4] Sync library access: source=%s target=%s", source_user_id, tgt_user_id)
            res_library_access = self._library_access_sync(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)]
            )
            current_step += 1
            emit_progress(progress_callback, "library_access", "Accessi librerie copiati", current_step, total_steps)
        else:
            logger.info("[CLONE][4/4] Sync library access skipped")

        res_favorites = None
        if sync_favorites:
            logger.info("[CLONE][4/4] Sync favorites: source=%s target=%s", source_user_id, tgt_user_id)
            res_favorites = self._favorites_sync(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)]
            )
            current_step += 1
            emit_progress(progress_callback, "favorites", "Preferiti copiati", current_step, total_steps)
        else:
            logger.info("[CLONE][4/4] Sync favorites skipped")

        res_playlists = None
        if sync_playlists:
            logger.info("[CLONE][4/4] Sync playlists: source=%s target=%s", source_user_id, tgt_user_id)
            res_playlists = self._playlists_sync(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)]
            )
            current_step += 1
            emit_progress(progress_callback, "playlists", "Playlist copiate", current_step, total_steps)
        else:
            logger.info("[CLONE][4/4] Sync playlists skipped")

        emit_progress(
            progress_callback,
            "complete",
            f"Clonazione completata: {target_username}",
            total_steps,
            total_steps,
            {"target_server_id": target_server_id, "target_user_id": tgt_user_id, "target_username": target_username},
        )
        return {
            "ok": True,
            "target_user_id": tgt_user_id,
            "playstate_stats": res_play,
            "library_access_stats": res_library_access,
            "favorites_stats": res_favorites,
            "playlists_stats": res_playlists
        }
