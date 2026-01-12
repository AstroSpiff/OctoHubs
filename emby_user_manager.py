"""
Manager for Emby Users, handling sync, policies, and multi-server orchestration.
"""
import uuid
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from api_clients import (
    _fetch_emby_users_list,
    _fetch_emby_user_details,
    _update_emby_user_policy,
    _update_emby_user_configuration,
    _fetch_emby_user_items_for_sync,
    _mark_emby_item_played,
    _create_emby_user,
    _call_emby_api
)
from storage import DatabaseStorage

logger = logging.getLogger(__name__)

class EmbyUserManager:
    def __init__(self, storage: DatabaseStorage, config: Dict[str, Any]):
        self.storage = storage
        self.config = config

    def _get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        servers = self.config.get("EMBY", {}).get("SERVERS", [])
        for s in servers:
            if s.get("id") == server_id:
                return s
        return None

    def get_users_dashboard_data(self) -> Dict[str, Any]:
        """
        Aggregates users from all servers and their link status.
        """
        servers = self.config.get("EMBY", {}).get("SERVERS", [])
        active_servers = [s for s in servers if s.get("enabled")]
        
        # 1. Fetch all users from all servers
        all_users_raw = []
        for server in active_servers:
            users, error = _fetch_emby_users_list(server)
            if error:
                logger.error(f"Error fetching users from {server['name']}: {error}")
                continue
            for u in users:
                u["_server_id"] = server["id"]
                u["_server_name"] = server["name"]
                all_users_raw.append(u)

        # 2. Get existing links from DB
        links = self.storage.get_user_links()
        # Map: (server_id, user_id) -> {group_id, is_leader}
        link_map = {}
        for l in links:
            link_map[(l["server_id"], l["user_id"])] = {
                "group_id": l["group_id"],
                "is_leader": l.get("is_leader", False)
            }

        # 3. Group users
        grouped_users = {} # group_id -> list of user entries
        
        for u in all_users_raw:
            sid = u["_server_id"]
            uid = u["Id"]
            name = u["Name"]
            
            link_info = link_map.get((sid, uid))
            gid = link_info["group_id"] if link_info else f"unlinked_{sid}_{uid}"
            db_is_leader = link_info["is_leader"] if link_info else False
                
            if gid not in grouped_users:
                grouped_users[gid] = {
                    "id": gid,
                    "name": name, # Representative name
                    "users": [],
                    "is_linked": not gid.startswith("unlinked_")
                }
            
            # Enrich user object
            policy = u.get("Policy", {})
            primary_image_tag = u.get("PrimaryImageTag")
            image_url = ""
            if primary_image_tag:
                from urllib.parse import urlencode
                query = {
                    "server_id": sid,
                    "item_id": uid,
                    "type": "Primary",
                    "tag": primary_image_tag,
                    "max_width": 100,
                    "scope": "user"
                }
                image_url = f"/api/emby/image?{urlencode(query)}"

            u_data = {
                "server_id": sid,
                "server_name": u["_server_name"],
                "user_id": uid,
                "name": name,
                "image_url": image_url,
                "has_password": u.get("HasPassword", False),
                "is_disabled": policy.get("IsDisabled", False),
                "enable_playback": policy.get("EnableMediaPlayback", True),
                "enable_audio_transcoding": policy.get("EnableAudioPlaybackTranscoding", True),
                "enable_video_transcoding": policy.get("EnableVideoPlaybackTranscoding", True),
                "enable_remuxing": policy.get("EnablePlaybackRemuxing", True),
                "enable_downloading": policy.get("EnableContentDownloading", True),
                "last_login": u.get("LastLoginDate"),
                "is_admin": policy.get("IsAdministrator", False),
                "is_leader": db_is_leader
            }
            grouped_users[gid]["users"].append(u_data)
            
            # Update group name logic: Prefer "Master", then longest name
            current_name = grouped_users[gid]["name"]
            if name.lower() == "master" and current_name.lower() != "master":
                grouped_users[gid]["name"] = name
            elif len(name) > len(current_name) and current_name.lower() != "master":
                 grouped_users[gid]["name"] = name

        # Sort users within groups: Leader first, then Master, then Active, then Alphabetical
        for group in grouped_users.values():
            group["users"].sort(key=lambda x: (
                not x["is_leader"],
                x["name"].lower() != "master",
                x["is_disabled"],
                x["name"]
            ))

        return {
            "groups": list(grouped_users.values()),
            "servers": [{"id": s["id"], "name": s["name"]} for s in active_servers]
        }

    def toggle_playback_permissions(self, server_id: str, user_id: str, enable: bool) -> bool:
        """
        Toggles playback permissions for a user.
        Controls: EnableMediaPlayback, Transcoding (Audio/Video), Remuxing.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        details, err = _fetch_emby_user_details(server, user_id)
        if err or not details:
            return False
            
        policy = details.get("Policy", {})
        policy["EnableMediaPlayback"] = enable
        policy["EnableAudioPlaybackTranscoding"] = enable
        policy["EnableVideoPlaybackTranscoding"] = enable
        policy["EnablePlaybackRemuxing"] = enable
        
        success, _ = _update_emby_user_policy(server, user_id, policy)
        return success

    def toggle_download_permissions(self, server_id: str, user_id: str, enable: bool) -> bool:
        """
        Toggles download permissions for a user.
        Controls: EnableContentDownloading, EnableContentDownloadingWithTranscoding, EnableSyncTranscoding.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        details, err = _fetch_emby_user_details(server, user_id)
        if err or not details:
            return False
            
        policy = details.get("Policy", {})
        policy["EnableContentDownloading"] = enable
        policy["EnableContentDownloadingWithTranscoding"] = enable
        policy["EnableSyncTranscoding"] = enable
        
        success, _ = _update_emby_user_policy(server, user_id, policy)
        return success

    def link_users(self, links: List[Dict[str, Any]]) -> str:
        """
        Links multiple users into a single group.
        links: list of {"server_id": "...", "user_id": "...", "username": "...", "is_leader": bool}
        Returns the new group_id.
        """
        new_group_id = str(uuid.uuid4())
        
        # Check if any user is marked as leader in the request
        has_leader = any(l.get("is_leader") for l in links)
        
        for l in links:
            # If no explicit leader, try to auto-detect "Master"
            is_leader = l.get("is_leader", False)
            if not has_leader and l.get("username", "").lower() == "master":
                is_leader = True
                has_leader = True # Only one auto-master
            
            self.storage.set_user_link(
                l["server_id"], 
                l["user_id"], 
                new_group_id, 
                l.get("username"),
                is_leader=is_leader
            )
        return new_group_id

    def unlink_user(self, server_id: str, user_id: str) -> None:
        """Removes a user from their link group."""
        self.storage.remove_user_link(server_id, user_id)

    def toggle_user_active(self, server_id: str, user_id: str, active: bool) -> bool:
        """
        Enables or Disables a user on a specific server.
        active=True -> IsDisabled=False
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        # 1. Fetch current policy to not overwrite other settings
        details, err = _fetch_emby_user_details(server, user_id)
        if err or not details:
            return False
            
        policy = details.get("Policy", {})
        policy["IsDisabled"] = not active
        
        # 2. Update
        success, _ = _update_emby_user_policy(server, user_id, policy)
        return success

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

        # Fetch source data
        src_details, err = _fetch_emby_user_details(source_server, source_user_id)
        if err or not src_details:
            return {"error": f"Failed to fetch source user: {err}"}

        src_policy = src_details.get("Policy", {})
        src_config = src_details.get("Configuration", {})
        
        # Fields to EXCLUDE from sync (preserve Target's value)
        # These contain server-specific IDs or critical access rights
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
                
            # Fetch target current state (to merge into)
            tgt_details, err_t = _fetch_emby_user_details(tgt_server, tgt_uid)
            if err_t or not tgt_details:
                results["failed"].append(f"{tgt_server['name']}: Failed to fetch target")
                continue

            # Backup target first
            self._backup_user(tgt_server, tgt_uid, "full_sync_pre")

            # Merge Policy
            tgt_policy = tgt_details.get("Policy", {})
            for k, v in src_policy.items():
                if k not in POLICY_EXCLUDE:
                    tgt_policy[k] = v
            
            # Merge Configuration
            tgt_config = tgt_details.get("Configuration", {})
            for k, v in src_config.items():
                if k not in CONFIG_EXCLUDE:
                    tgt_config[k] = v

            # Update Policy
            ok_p, err_p = _update_emby_user_policy(tgt_server, tgt_uid, tgt_policy)
            # Update Config
            ok_c, err_c = _update_emby_user_configuration(tgt_server, tgt_uid, tgt_config)
            
            if ok_p and ok_c:
                results["success"].append(f"{tgt_server['name']} ({tgt_uid})")
            else:
                results["failed"].append(f"{tgt_server['name']}: Policy={ok_p}, Config={ok_c}")
                
        return results

    def sync_user_playstate(self, source_server_id: str, source_user_id: str, target_tuples: List[tuple]) -> Dict[str, Any]:
        """
        Syncs watched status (playstate) from source to targets.
        Matches items by ProviderIds (TMDB, IMDB, TVDB) or fallback key.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}

        # 1. Get Source Items
        src_items, err = _fetch_emby_user_items_for_sync(source_server, source_user_id)
        if err:
            return {"error": f"Failed to fetch source items: {err}"}

        # Index source items by Provider IDs or fallback keys
        src_map = {}
        for item in src_items:
            ud = item.get("UserData", {})
            if not ud.get("Played"):
                continue
                
            keys = self._get_item_sync_keys(item)
            for key in keys:
                src_map[key] = {
                    "last_played": ud.get("LastPlayedDate")
                }
        
        results = {"success": [], "failed": [], "counts": {}}

        # 2. Apply to targets
        for tgt_srv_id, tgt_uid in target_tuples:
            tgt_server = self._get_server_by_id(tgt_srv_id)
            if not tgt_server:
                continue

            # We need to find the corresponding ItemIds on the target server.
            # We fetch all generic items to match IDs
            all_items, err = self._fetch_all_media_for_user(tgt_server, tgt_uid)
            if err:
                results["failed"].append(f"{tgt_server['name']}: Fetch error")
                continue
                
            updated_count = 0
            for item in all_items:
                ud = item.get("UserData", {})
                if ud.get("Played"):
                    continue # Already played
                
                keys = self._get_item_sync_keys(item)
                
                # Check match
                match = None
                for key in keys:
                    if key in src_map:
                        match = src_map[key]
                        break
                    
                if match:
                    # Match found! Mark as played.
                    ok, _ = _mark_emby_item_played(
                        tgt_server, 
                        tgt_uid, 
                        item["Id"], 
                        date_played=match["last_played"]
                    )
                    if ok:
                        updated_count += 1
            
            results["success"].append(tgt_server['name'])
            results["counts"][tgt_server['name']] = updated_count
            
        return results

    def sync_merge_playstate(self, targets: List[tuple]) -> Dict[str, Any]:
        """
        Bidirectional sync: Merges played status from ALL targets and applies to ALL.
        targets: list of (server_id, user_id)
        """
        global_played_map = {} # Key -> {last_played: date}
        
        # 1. Gather phase
        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server: continue
            
            items, err = _fetch_emby_user_items_for_sync(server, uid)
            if err: continue
            
            for item in items:
                ud = item.get("UserData", {})
                if not ud.get("Played"): continue
                
                keys = self._get_item_sync_keys(item)
                date_played = ud.get("LastPlayedDate")
                
                for key in keys:
                    if key not in global_played_map:
                        global_played_map[key] = {"last_played": date_played}
                    else:
                        # Compare dates string ISO
                        current = global_played_map[key]["last_played"]
                        if date_played and (not current or date_played > current):
                            global_played_map[key]["last_played"] = date_played

        results = {"success": [], "failed": [], "counts": {}}

        # 2. Apply phase
        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server: continue
            
            all_items, err = self._fetch_all_media_for_user(server, uid)
            if err:
                results["failed"].append(f"{server['name']}")
                continue
                
            updated_count = 0
            for item in all_items:
                ud = item.get("UserData", {})
                if ud.get("Played"): continue # Already played locally
                
                keys = self._get_item_sync_keys(item)
                
                # Check match
                match = None
                for key in keys:
                    if key in global_played_map:
                        match = global_played_map[key]
                        break
                
                if match:
                    # Mark as played
                    ok, _ = _mark_emby_item_played(
                        server, uid, item["Id"], 
                        date_played=match["last_played"]
                    )
                    if ok: updated_count += 1
            
            results["success"].append(server['name'])
            results["counts"][server['name']] = updated_count
            
        return results

    def clone_user(self, source_server_id: str, source_user_id: str, target_server_id: str) -> Dict[str, Any]:
        """
        Clones a user from source to target server.
        Creates the user if missing (matching by Name).
        Syncs Config, Policy and Playstate.
        """
        src_server = self._get_server_by_id(source_server_id)
        tgt_server = self._get_server_by_id(target_server_id)
        if not src_server or not tgt_server:
            return {"error": "Server not found"}
            
        # 1. Fetch Source
        src_user, err = _fetch_emby_user_details(src_server, source_user_id)
        if not src_user:
            return {"error": "Source user not found"}
            
        username = src_user["Name"]
        
        # 2. Check/Create Target
        # Fetch target user list
        tgt_users, _ = _fetch_emby_users_list(tgt_server)
        target_user = next((u for u in tgt_users if u["Name"].lower() == username.lower()), None)
        
        tgt_user_id = None
        if target_user:
            tgt_user_id = target_user["Id"]
            logger.info(f"User {username} exists on target, syncing...")
        else:
            logger.info(f"Creating user {username} on target...")
            ok, res = _create_emby_user(tgt_server, username)
            if not ok:
                return {"error": f"Failed to create user: {res}"}
            tgt_user_id = res.get("Id")
            
        if not tgt_user_id:
            return {"error": "Failed to resolve target user ID"}
            
        # 3. Sync Config & Policy (Safe)
        self.sync_user_config(source_server_id, source_user_id, [(target_server_id, tgt_user_id)])
        
        # 4. Sync Playstate (One-way Source -> Target)
        res_play = self.sync_user_playstate(source_server_id, source_user_id, [(target_server_id, tgt_user_id)])
        
        return {"ok": True, "target_user_id": tgt_user_id, "playstate_stats": res_play}

    def _fetch_all_media_for_user(self, server, user_id):
        # Fetch ALL generic items (Movie, Episode) to match IDs
        # We need ProviderIds and UserData
        from api_clients import _call_emby_api
        params = {
            "Recursive": "true",
            "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
            "IncludeItemTypes": "Movie,Episode",
            "IsPlayed": "false" # Optimization: Only fetch unplayed to mark them?
            # Actually, if we want full map we need all. 
            # But for merge/sync we only need to act on unplayed items that SHOULD be played.
            # So fetching "IsPlayed=false" is enough for the target application phase!
        }
        success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=params)
        if not success:
            return [], payload
        return payload.get("Items", []), None

    def _get_item_sync_keys(self, item: Dict[str, Any]) -> List[str]:
        """
        Generates a list of unique keys for an item to be used for sync matching.
        Priority: TMDB, IMDB, TVDB, Name/Year/Index fallback.
        """
        keys = []
        pids = item.get("ProviderIds", {})
        
        # 1. External IDs
        if pids.get("Tmdb"): keys.append(f"tmdb:{pids['Tmdb']}")
        if pids.get("Imdb"): keys.append(f"imdb:{pids['Imdb']}")
        if pids.get("Tvdb"): keys.append(f"tvdb:{pids['Tvdb']}")
        
        # 2. Fallback: Name matching
        name = (item.get("Name") or "").lower().strip()
        original_name = (item.get("OriginalTitle") or "").lower().strip()
        year = item.get("ProductionYear")
        
        # For Episodes: SeriesName + Season + Episode
        series_name = (item.get("SeriesName") or "").lower().strip()
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        
        if series_name and season is not None and episode is not None:
            # Episode key
            keys.append(f"ep:{series_name}:s{season}:e{episode}")
            
            # Robust fallback: Normalize series name (remove year, special chars)
            # e.g. "The Series (2024)" -> "the series"
            import re
            
            def normalize(s):
                # Remove (Year) pattern
                s = re.sub(r'\(\d{4}\)', '', s)
                # Remove special chars
                s = re.sub(r'[^a-z0-9\s]', '', s)
                return s.strip()
                
            norm_series = normalize(series_name)
            if norm_series != series_name:
                keys.append(f"ep:{norm_series}:s{season}:e{episode}")
                
        elif name and year:
            # Movie key
            keys.append(f"mov:{name}:{year}")
            if original_name and original_name != name:
                keys.append(f"mov:{original_name}:{year}")
                
        return keys

    def _backup_user(self, server: Dict[str, Any], user_id: str, reason: str):
        """
        Creates a DB backup of the user's current state.
        """
        details, err = _fetch_emby_user_details(server, user_id)
        if details:
            self.storage.create_user_backup(
                server["id"],
                user_id,
                details.get("Name", "Unknown"),
                f"full_{reason}",
                details
            )