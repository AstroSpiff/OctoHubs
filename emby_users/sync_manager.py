import logging
from typing import Dict, Any, Optional, Tuple, List, Callable

logger = logging.getLogger(__name__)


class SyncManager:
    def __init__(
        self,
        storage,
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
        fetch_user_details: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[str]]],
        fetch_users_list: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Optional[str]]],
        update_user_policy: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        update_user_config: Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[bool, Optional[str]]],
        create_user: Callable[[Dict[str, Any], str], Tuple[bool, Dict[str, Any]]],
        playstate_sync: Callable[[str, str, List[tuple], bool], Dict[str, Any]],
        link_clone_to_group: Callable[[str, str, Optional[str], str, str, Optional[str]], str],
    ):
        self.storage = storage
        self._get_server_by_id = get_server_by_id
        self._fetch_user_details = fetch_user_details
        self._fetch_users_list = fetch_users_list
        self._update_user_policy = update_user_policy
        self._update_user_config = update_user_config
        self._create_user = create_user
        self._playstate_sync = playstate_sync
        self._link_clone_to_group = link_clone_to_group

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

    def sync_user_config(self, source_server_id: str, source_user_id: str, target_tuples: List[tuple]) -> Dict[str, Any]:
        """
        Copies Configuration and Policy from source to targets.
        target_tuples: list of (server_id, user_id)

        CRITICAL: Excludes server-specific ID fields (like EnabledFolders, MyMediaExcludes)
        to prevent breaking access on the target server.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        src_details, err = self._fetch_user_details(source_server, source_user_id)
        if err or not src_details:
            return {"error": f"Failed to fetch source user: {err}"}

        src_policy = src_details.get("Policy", {})
        src_config = src_details.get("Configuration", {})

        POLICY_EXCLUDE = {
            "IsAdministrator", "IsDisabled", "IsHidden", "IsHiddenFromUnusedDevices",
            "EnableAllFolders", "EnabledFolders", "ExcludedSubFolders",
            "BlockedTags", "BlockedMediaTags", "AccessSchedules",
            "Authentication", "Password", "InvalidLoginAttemptCount", "LoginAttemptsBeforeLockout",
            "MaxActiveSessions", "SyncPlayfield"
        }

        CONFIG_EXCLUDE = {
            "MyMediaExcludes", "GroupedFolders", "DashboardLayout",
            "HomePageSectionOrder", "LandingScreen", "LatestItemsExcludes"
        }

        results = {"success": [], "failed": []}

        for tgt_srv_id, tgt_uid in target_tuples:
            tgt_server = self._get_server_by_id(tgt_srv_id)
            if not tgt_server:
                results["failed"].append(f"Server {tgt_srv_id} not found")
                continue

            tgt_details, err_t = self._fetch_user_details(tgt_server, tgt_uid)
            if err_t or not tgt_details:
                results["failed"].append(f"{tgt_server['name']}: Failed to fetch target")
                continue

            self._backup_user(tgt_server, tgt_uid, "full_sync_pre")

            tgt_policy = tgt_details.get("Policy", {})
            for k, v in src_policy.items():
                if k not in POLICY_EXCLUDE:
                    tgt_policy[k] = v

            tgt_config = tgt_details.get("Configuration", {})
            for k, v in src_config.items():
                if k not in CONFIG_EXCLUDE:
                    tgt_config[k] = v

            ok_p, _ = self._update_user_policy(tgt_server, tgt_uid, tgt_policy)
            ok_c, _ = self._update_user_config(tgt_server, tgt_uid, tgt_config)

            if ok_p and ok_c:
                results["success"].append(f"{tgt_server['name']} ({tgt_uid})")
            else:
                results["failed"].append(f"{tgt_server['name']}: Policy={ok_p}, Config={ok_c}")

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
        link_group: bool = False
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
            "[CLONE][1/4] Start: source_user_id=%s target_server_id=%s sync_config=%s sync_playstate=%s sync_resume=%s link_group=%s",
            source_user_id,
            target_server_id,
            sync_config,
            sync_playstate,
            sync_resume,
            link_group
        )

        src_server = self._get_server_by_id(source_server_id)
        tgt_server = self._get_server_by_id(target_server_id)
        if not src_server or not tgt_server:
            return {"error": "Server not found"}

        src_user, err = self._fetch_user_details(src_server, source_user_id)
        if not src_user:
            return {"error": "Source user not found"}
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
        else:
            logger.info(
                "[CLONE][2/4] Creating target user: %s -> user=%s",
                _srv_label(tgt_server),
                target_username
            )
            ok, res = self._create_user(tgt_server, target_username)
            if not ok:
                return {"error": f"Failed to create user: {res}"}
            tgt_user_id = res.get("Id")
            logger.info(
                "[CLONE][2/4] Target created: %s -> user=%s (%s)",
                _srv_label(tgt_server),
                target_username,
                tgt_user_id
            )

        if not tgt_user_id:
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
            self.sync_user_config(source_server_id, source_user_id, [(target_server_id, tgt_user_id)])
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

        return {"ok": True, "target_user_id": tgt_user_id, "playstate_stats": res_play}
