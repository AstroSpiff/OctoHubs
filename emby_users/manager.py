"""
Manager for Emby Users, handling sync, policies, and multi-server orchestration.
"""
import uuid
import logging
import os
import copy
import time
import base64
import hashlib
from typing import List, Dict, Any, Optional, Tuple

from .api_client import (
    _fetch_emby_users_list,
    _fetch_emby_user_details,
    _update_emby_user_policy,
    _update_emby_user_configuration,
    _rename_emby_user,
    _update_emby_user_password,
    _fetch_emby_user_last_playback,
    _fetch_emby_user_items_for_sync,
    _fetch_emby_items_by_provider_ids,
    _mark_emby_item_played,
    _set_emby_item_resume,
    _create_emby_user
)
from api_clients import _emby_base_url
from storage import DatabaseStorage
from utils import normalize_string, get_nested
import requests
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

class EmbyUserManager:
    def __init__(self, storage: DatabaseStorage, config: Dict[str, Any]):
        self.storage = storage
        self.config = config
        self._password_cipher: Optional[Fernet] = None
        self._ensure_icon_dir()
        self._migrate_icons_to_db()

    def _ensure_icon_dir(self):
        self.icon_dir = os.path.join(os.getcwd(), "static", "user_icons")
        os.makedirs(self.icon_dir, exist_ok=True)

    def _migrate_icons_to_db(self):
        """
        Migrates existing file-based icons to the database.
        """
        try:
            rules = self.storage.get_icon_rules()
            for rule in rules:
                if not rule.get("has_data") and rule.get("icon_path"):
                    # It has a path but no data in DB. Try to load from file.
                    path = rule["icon_path"]
                    # If path starts with /api/, it's already migrated URL but maybe no data? 
                    # No, if it was migrated, has_data should be true.
                    # Current path format: "user_icons/filename"
                    if path.startswith("user_icons/"):
                        full_path = os.path.join(os.getcwd(), "static", path)
                        if os.path.exists(full_path):
                            try:
                                with open(full_path, "rb") as f:
                                    data = f.read()
                                mime = "image/png"
                                if full_path.lower().endswith(".jpg") or full_path.lower().endswith(".jpeg"):
                                    mime = "image/jpeg"
                                
                                # Update DB
                                # Use new URL format for path
                                new_path = f"/api/emby/icons/image/{rule['profile_id']}/{rule['column_key']}"
                                self.storage.save_icon_rule(rule['profile_id'], rule['column_key'], new_path, data, mime)
                                logger.info(f"Migrated icon to DB: {full_path}")
                            except Exception as e:
                                logger.error(f"Failed to migrate icon {full_path}: {e}")
        except Exception as e:
             logger.error(f"Migration error: {e}")

    def _get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        servers = self.config.get("EMBY", {}).get("SERVERS", [])
        for s in servers:
            if s.get("id") == server_id:
                return s
        return None

    # --- ICON MANAGEMENT START ---

    def get_icon_dashboard_data(self) -> Dict[str, Any]:
        """
        Returns all data needed to render the Icon Matrix UI.
        """
        profiles = self.storage.get_icon_profiles()
        profiles.sort(key=lambda p: p['label'].lower())
        rules = self.storage.get_icon_rules()
        bindings = self.storage.get_icon_bindings()
        
        # Organize rules into a matrix structure: {profile_id: {column_key: icon_path}}
        matrix = {}
        for r in rules:
            if r["profile_id"] not in matrix:
                matrix[r["profile_id"]] = {}
            # Return the stored path (which should be the API URL now)
            matrix[r["profile_id"]][r["column_key"]] = r["icon_path"]

        # Organize bindings: {target_key: profile_id}
        # target_key for single user: "user:server_id:user_id" -> Wait, actually "user:user_id"
        # target_key for group: "group:group_id"
        binding_map = {}
        for b in bindings:
            key = f"{b['target_type']}:{b['target_id']}"
            binding_map[key] = b["profile_id"]

        return {
            "profiles": profiles,
            "matrix": matrix,
            "bindings": binding_map
        }

    def save_icon_profile(self, label: str, is_group_profile: bool = False, profile_id: Optional[str] = None) -> str:
        if not profile_id:
            profile_id = str(uuid.uuid4())
        self.storage.save_icon_profile(profile_id, label, False) # Universal template (is_group_profile ignored/false)
        return profile_id

    def delete_icon_profile(self, profile_id: str) -> None:
        self.storage.delete_icon_profile(profile_id)

    def save_icon_binding(self, target_type: str, target_id: str, profile_id: str) -> None:
        """
        Binds a User or Group to a Profile and triggers sync.
        """
        self.storage.save_icon_binding(target_type, target_id, profile_id)
        self._sync_icons_for_binding(target_type, target_id)

    def save_icon_rule(self, profile_id: str, column_key: str, file_storage) -> str:
        """
        Saves an uploaded icon file to DB and creates the rule. Triggers sync.
        file_storage: FastAPI UploadFile or similar
        """
        # Read file content
        file_storage.file.seek(0)
        data = file_storage.file.read()
        
        filename = file_storage.filename or "icon.png"
        mime_type = file_storage.content_type or "image/png"
        
        # Determine strict mime from extension if content_type is generic
        ext = os.path.splitext(filename)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            mime_type = "image/jpeg"
        elif ext == '.png':
            mime_type = "image/png"
            
        # New API URL Path
        rel_path = f"/api/emby/icons/image/{profile_id}/{column_key}"
        
        self.storage.save_icon_rule(profile_id, column_key, rel_path, data, mime_type)
        self._sync_icons_for_rule(profile_id, column_key)
        return rel_path

    def delete_icon_rule(self, profile_id: str, column_key: str) -> None:
        """
        Deletes a rule (cell) and data from DB.
        Note: Does NOT revert the icon on Emby (per specs "No action if empty").
        """
        self.storage.delete_icon_rule(profile_id, column_key)

    def get_icon_image(self, profile_id: str, column_key: str) -> Optional[Tuple[bytes, str]]:
        """
        Retrieves the binary image data and mime type.
        """
        return self.storage.get_icon_rule_data(profile_id, column_key)

    def _sync_icons_for_rule(self, profile_id: str, column_key: str):
        """
        Syncs all users affected by a specific rule change (cell change).
        """
        self._apply_icon_logic(filter_profile_id=profile_id, filter_column_key=column_key)

    def _sync_icons_for_binding(self, target_type: str, target_id: str):
        """
        Syncs users affected by a binding change.
        """
        self._apply_icon_logic(filter_target_type=target_type, filter_target_id=target_id)

    def sync_all_icons(self):
        """
        Syncs everything.
        """
        self._apply_icon_logic()

    def _apply_icon_logic(self, filter_profile_id=None, filter_column_key=None, filter_target_type=None, filter_target_id=None):
        """
        Core logic to determine and upload icons.
        Refactored to follow the deterministic model:
        Profile x ReferenceServer -> Icon
        """
        # 1. Get all context data
        dashboard_data = self.get_users_dashboard_data()
        groups = dashboard_data["groups"]
        bindings = self.storage.get_icon_bindings()
        
        # Map bindings for quick lookup
        # group binding: "group:GROUP_ID" -> profile_id
        # user binding: "user:SERVER_ID:USER_ID" -> profile_id
        binding_map = {f"{b['target_type']}:{b['target_id']}": b['profile_id'] for b in bindings}
        
        # Map rules: profile_id -> { col_key: icon_path }
        rules = self.storage.get_icon_rules()
        rule_map = {}
        for r in rules:
            if r['profile_id'] not in rule_map:
                rule_map[r['profile_id']] = {}
            rule_map[r['profile_id']][r['column_key']] = r['icon_path']

        # 2. Iterate all users in all groups
        for group in groups:
            group_id = group["id"]
            
            # Determine Group Profile
            group_profile_id = binding_map.get(f"group:{group_id}")
            
            # Determine Group Reference Server (from Leader)
            leader_user = next((u for u in group["users"] if u.get("is_leader")), None)
            
            group_ref_server_id = leader_user["server_id"] if leader_user else None

            for user in group["users"]:
                server_id = user["server_id"]
                user_id = user["user_id"]
                
                # Check filters (optimization)
                if filter_target_type == "group" and filter_target_id != group_id:
                    continue
                if filter_target_type == "user" and filter_target_id != f"{server_id}:{user_id}":
                    continue
                
                # ALGORITHM: Determine Profile & Reference Server
                profile_id = None
                reference_server_id = None
                is_group_application = False
                user_binding_key = ""

                if group_profile_id:
                    # Group Binding
                    if not group_ref_server_id:
                        logger.warning(f"[ICON_LOGIC] Group {group['name']} ({group_id}) has binding but NO LEADER. Skipping.")
                        continue
                    profile_id = group_profile_id
                    reference_server_id = group_ref_server_id
                    is_group_application = True

                else:
                    # User Binding
                    user_binding_key = f"user:{server_id}:{user_id}"
                    user_profile_id = binding_map.get(user_binding_key)
                    if user_profile_id:
                        profile_id = user_profile_id
                        reference_server_id = server_id
                        is_group_application = False
                
                # Debug logging for single users (or all)
                if not is_group_application:
                   logger.info(f"[ICON_DEBUG] Check User: {user['name']} | Key={user_binding_key} | Profile={profile_id}")

                if not profile_id:
                    continue

                if filter_profile_id and filter_profile_id != profile_id:
                    continue

                # Filter by Column Key (Reference Server)
                # We only proceed if the changed column matches our reference server
                if filter_column_key and filter_column_key != reference_server_id:
                    continue

                # Resolve Icon
                # icon = matrix[profile_id][reference_server_id]
                icon_path = get_nested(rule_map, profile_id, reference_server_id)
                
                # Debug Logging (Mandatory for Groups)
                if is_group_application:
                    logger.info(
                        f"[ICON_DEBUG] Group Apply: "
                        f"Group={group['name']} | "
                        f"Leader={(leader_user['name'] if leader_user else 'Unknown')}@{group_ref_server_id} | "
                        f"Member={user['name']}@{server_id} | "
                        f"Profile={profile_id} | "
                        f"RefServer={reference_server_id} | "
                        f"Icon={'FOUND' if icon_path else 'EMPTY'}"
                    )
 
                # Apply         
                if icon_path:
                    # Upload to the USER'S server (upload_server_id = user.server_id)
                    # Use profile_id and reference_server_id (column_key) to fetch data
                    self._upload_icon_to_emby(server_id, user_id, profile_id, str(reference_server_id))

    def _upload_icon_to_emby(self, server_id: str, user_id: str, profile_id: str, column_key: str):
        import base64
        
        server = self._get_server_by_id(server_id)
        if not server:
            logger.error(f"[ICON_UPLOAD] Server not found: {server_id}")
            return

        # 1. READ from DB
        try:
            data_tuple = self.get_icon_image(profile_id, column_key)
            if not data_tuple:
                 logger.error(f"[ICON_UPLOAD] Icon data not found for {profile_id}/{column_key}")
                 return
            
            raw_bytes, mime_type = data_tuple
            # Emby expects BASE64 String in the body for /Images/Primary (despite some docs saying otherwise)
            b64_data = base64.b64encode(raw_bytes)
        except Exception as e:
            logger.error(f"[ICON_UPLOAD] Failed to read file: {e}")
            return

        base_url = _emby_base_url(server)
        token = server.get("api_key")
        
        user_url = f"{base_url}/Users/{user_id}"
        image_url = f"{base_url}/Users/{user_id}/Images/Primary"
        headers = {"X-Emby-Token": token}

        # 2. PRE-CHECK
        old_tag = "N/A"
        try:
            r = requests.get(user_url, headers=headers, timeout=10)
            if r.ok:
                old_tag = r.json().get("PrimaryImageTag", "None")
            logger.info(f"[ICON_UPLOAD] Pre-check {user_id}@{server['name']}: OldTag={old_tag}")
        except Exception as e:
            logger.warning(f"[ICON_UPLOAD] Pre-check failed: {e}")

        # 3. DELETE (Robustness)
        # try:
        #     r_del = requests.delete(image_url, headers=headers, timeout=10)
        # except Exception as e:
        #     pass

        # 4. UPLOAD (POST Base64)
        headers["Content-Type"] = mime_type # e.g. image/png or image/jpeg
        
        try:
            logger.info(f"[ICON_UPLOAD] Uploading Base64 to {image_url} (Original Size: {len(raw_bytes)})")
            
            response = requests.post(image_url, headers=headers, data=b64_data, timeout=30)
            
            if not response.ok:
                logger.error(f"[ICON_UPLOAD] Status: {response.status_code} - {response.text}")
            
            response.raise_for_status()
            
        except Exception as e:
            logger.error(f"[ICON_UPLOAD] Upload Failed: {e}")
            return

        # 5. VERIFY
        try:
            r = requests.get(user_url, headers={"X-Emby-Token": token}, timeout=10)
            new_tag = "N/A"
            if r.ok:
                new_tag = r.json().get("PrimaryImageTag", "None")
            
            logger.info(f"[ICON_UPLOAD] Post-check: NewTag={new_tag}")

            if new_tag != old_tag:
                 logger.info(f"[ICON_UPLOAD] SUCCESS: Tag changed {old_tag} -> {new_tag}")
            elif new_tag == "None":
                 logger.warning("[ICON_UPLOAD] FAILURE: Tag is None (Image not set?)")
            else:
                 pass # Same tag is possible if same image?
                 
        except Exception as e:
            logger.warning(f"[ICON_UPLOAD] Verify failed: {e}")

    # --- ICON MANAGEMENT END ---

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
            
            # Defensive copy to ensure no shared references
            users = copy.deepcopy(users)
            
            for u in users:
                u["_server_id"] = server["id"]
                u["_server_name"] = server["name"]
                # Debug log to verify assignment
                # logger.debug(f"User {u.get('Name')} assigned to server {server.get('alias') or server['name']} ({server['id']})")
                all_users_raw.append(u)

        # 1b. Identify Server Owners (First Created Admin)
        # Map: server_id -> {date: str, uid: str}
        server_oldest_admin_map = {} 
        server_map = {s["id"]: s for s in active_servers}

        for u in all_users_raw:
            # ONLY consider Administrators for ownership
            policy = u.get("Policy", {})
            if not policy.get("IsAdministrator"):
                continue

            sid = u["_server_id"]
            created_str = u.get("DateCreated")
            if not created_str:
                continue
            
            try:
                # Check current oldest admin for this server
                current = server_oldest_admin_map.get(sid)
                if not current or created_str < current["date"]:
                    server_oldest_admin_map[sid] = {"date": created_str, "uid": u["Id"]}
            except Exception as e:
                logger.warning(f"Error checking user date {u.get('Name')}: {e}")

        # 2. Get existing links from DB
        links = self.storage.get_user_links()
        # Map: (server_id, user_id) -> {group_id, is_leader}
        link_map = {}
        for link in links:
            link_map[(link["server_id"], link["user_id"])] = {
                "group_id": link["group_id"],
                "is_leader": link.get("is_leader", False)
            }

        # 3. Group users
        grouped_users = {} # group_id -> list of user entries
        owners_users = [] # Special list for admins/owners
        password_map = {}
        password_plain_map: Dict[str, Optional[str]] = {}

        def _get_plain_password(group_id: str) -> Optional[str]:
            if group_id in password_plain_map:
                return password_plain_map[group_id]
            entry = password_map.get(group_id)
            if not entry or not entry.get("password_enc"):
                password_plain_map[group_id] = None
                return None
            password_plain_map[group_id] = self._decrypt_password(entry["password_enc"])
            return password_plain_map[group_id]
        
        # Load custom group names and settings
        custom_names = {}
        group_settings = {}
        try:
            # Keys are "group_name:UUID"
            kv_keys = self.storage.get_keys_by_prefix("group_name:")
            for k in kv_keys:
                gid = k.split(":", 1)[1]
                val = self.storage.get_key_value(k)
                if val:
                    custom_names[gid] = val
            
            # Keys are "group_settings:UUID"
            setting_keys = self.storage.get_keys_by_prefix("group_settings:")
            for k in setting_keys:
                gid = k.split(":", 1)[1]
                val = self.storage.get_key_value(k)
                if val:
                    group_settings[gid] = val

            for entry in self.storage.get_group_passwords():
                password_map[entry["group_id"]] = entry

        except Exception as e:
            logger.error(f"Error loading group names/settings: {e}")

        for u in all_users_raw:
            sid = u["_server_id"]
            uid = u["Id"]
            name = u["Name"]
            policy = u.get("Policy", {})
            is_admin = policy.get("IsAdministrator", False)
            
            # Resolve server correctly
            current_server = server_map.get(sid, {})
            
            # Enrich user object
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

            is_user_disabled = policy.get("IsDisabled", False)
            enable_remote_access = policy.get("EnableRemoteAccess", True)
            is_remote_disabled = not enable_remote_access

            u_data = {
                "server_id": sid,
                "server_name": u["_server_name"],
                "server_alias": current_server.get("alias"),
                "server_icon": current_server.get("icon", "fa-server"),
                "server_icon_color": current_server.get("icon_color", "#3b82f6"),
                "server_icon_style": current_server.get("icon_style", "solid"),
                "user_id": uid,
                "name": name,
                "image_url": image_url,
                "has_password": u.get("HasPassword", False),
                # NOTE: "is_disabled" is used by the UI to represent remote access disabled.
                "is_disabled": is_remote_disabled,
                "is_user_disabled": is_user_disabled,
                "is_remote_disabled": is_remote_disabled,
                "enable_remote_access": enable_remote_access,
                "enable_audio_transcoding": policy.get("EnableAudioPlaybackTranscoding", True),
                "enable_video_transcoding": policy.get("EnableVideoPlaybackTranscoding", True),
                "enable_remuxing": policy.get("EnablePlaybackRemuxing", True),
                "enable_downloading": policy.get("EnableContentDownloading", True),
                "last_login": u.get("LastLoginDate"),
                "is_admin": is_admin,
                "is_leader": False # Will be updated later if in regular group
            }

            # Check if Owner/Admin -> Special Group
            # Criteria: Is Admin AND Is First ADMIN Created on Server
            is_server_owner = (sid in server_oldest_admin_map and server_oldest_admin_map[sid]["uid"] == uid)
            
            if is_admin and is_server_owner:
                owners_users.append(u_data)
                continue # Skip regular grouping

            link_info = link_map.get((sid, uid))
            gid = link_info["group_id"] if link_info else f"unlinked_{sid}_{uid}"
            db_is_leader = link_info["is_leader"] if link_info else False
            u_data["is_leader"] = db_is_leader
                
            if gid not in grouped_users:
                g_settings = group_settings.get(gid) or {}
                pw_entry = password_map.get(gid)
                group_plain = _get_plain_password(gid)
                grouped_users[gid] = {
                    "id": gid,
                    "name": custom_names.get(gid) or name, # Use custom name if exists, else user name
                    "users": [],
                    "is_linked": not gid.startswith("unlinked_"),
                    "has_custom_name": gid in custom_names,
                    "auto_sync": g_settings.get("auto_sync", False),
                    "sync_type": g_settings.get("sync_type", "merge"),
                    "sync_resume": g_settings.get("sync_resume", False),
                    "password_saved": bool(group_plain),
                    "password_updated_at": pw_entry.get("updated_at") if pw_entry else None,
                    "password_status": "saved" if group_plain else "missing",
                    "password_mismatch": False,
                    "password_mismatch_count": 0
                }
            user_plain = _get_plain_password(self._get_unlinked_group_id(sid, uid))
            user_saved = bool(user_plain)
            group_plain = _get_plain_password(gid)
            group_mismatch = False
            user_mismatch = False

            if grouped_users[gid]["is_linked"]:
                if user_plain:
                    if group_plain:
                        if user_plain != group_plain:
                            group_mismatch = True
                            user_mismatch = True
                    else:
                        user_mismatch = True
                    status = "mismatch" if user_mismatch else "saved"
                else:
                    status = "missing"

                if group_mismatch:
                    grouped_users[gid]["password_mismatch"] = True
                    grouped_users[gid]["password_mismatch_count"] += 1
            else:
                status = "saved" if user_saved else "missing"

            u_data["password_saved"] = status == "saved"
            u_data["password_status"] = status
            u_data["password_mismatch"] = user_mismatch
            grouped_users[gid]["users"].append(u_data)
            
            # Update group name logic if NO custom name is set
            if not grouped_users[gid].get("has_custom_name"):
                current_name = grouped_users[gid]["name"]
                if name.lower() == "master" and current_name.lower() != "master":
                    grouped_users[gid]["name"] = name
                elif len(name) > len(current_name) and current_name.lower() != "master":
                     grouped_users[gid]["name"] = name

        # Sort users within regular groups
        for group in grouped_users.values():
            group["users"].sort(key=lambda x: (
                not x["is_leader"],
                x["name"].lower() != "master",
                x["is_disabled"],
                x["name"]
            ))
            if group.get("password_saved") and group.get("password_mismatch"):
                group["password_status"] = "mismatch"
            else:
                group["password_status"] = "saved" if group.get("password_saved") else "missing"
            
        # Prepare final list
        final_groups = list(grouped_users.values())
        
        # Add Owners group at the end if any
        if owners_users:
            owners_users.sort(key=lambda x: x["server_name"]) # Sort by server name
            owners_pw_plain = _get_plain_password("owners")
            owners_pw_entry = password_map.get("owners")
            for u in owners_users:
                u["password_saved"] = bool(owners_pw_plain)
                u["password_status"] = "saved" if owners_pw_plain else "missing"
            final_groups.append({
                "id": "owners",
                "name": "Proprietari",
                "users": owners_users,
                "is_linked": False, # Owners are just a visual group, not a sync group
                "is_owners": True, # Flag for UI special handling if needed
                "has_custom_name": True,
                "password_saved": bool(owners_pw_plain),
                "password_updated_at": owners_pw_entry.get("updated_at") if owners_pw_entry else None,
                "password_status": "saved" if owners_pw_plain else "missing",
                "password_mismatch": False,
                "password_mismatch_count": 0
            })

        return {
            "groups": final_groups,
            "servers": [{
                "id": s["id"], 
                "name": s.get("alias") or s["name"],
                "icon": s.get("icon", "fa-server"),
                "icon_color": s.get("icon_color", "#3b82f6"),
                "icon_style": s.get("icon_style", "solid")
            } for s in active_servers]
        }

    def rename_group(self, group_id: str, new_name: str) -> bool:
        """
        Renames a group.
        If group_id is 'unlinked_...', creates a new single-user group first.
        """
        target_group_id = group_id
        
        if group_id.startswith("unlinked_"):
            # Format: unlinked_{server_id}_{user_id}
            parts = group_id.split("_", 2)
            if len(parts) == 3:
                sid, uid = parts[1], parts[2]
                # Fetch user name for link
                # We need to find the user details... assuming we can just link without name or fetch it.
                # link_users expects username.
                
                # Simple fetch from dashboard data logic or just generic
                # Actually, link_users stores username but it's optional? No, uses it.
                # Let's just pass "User" if missing, it will be updated on next sync/fetch
                target_group_id = self.link_users([{
                    "server_id": sid,
                    "user_id": uid,
                    "username": new_name, # Use new name as username hint
                    "is_leader": True
                }])
            else:
                return False
        
        # Save custom name
        self.storage.set_key_value(f"group_name:{target_group_id}", new_name)
        return True

    def save_group_settings(self, group_id: str, auto_sync: bool, sync_type: str, sync_resume: bool) -> bool:
        """
        Saves group settings (auto_sync, sync_type, sync_resume).
        """
        if group_id.startswith("unlinked_"):
            return False # Cannot save settings for unlinked groups yet
        
        settings = {
            "auto_sync": auto_sync,
            "sync_type": sync_type,
            "sync_resume": sync_resume
        }
        self.storage.set_key_value(f"group_settings:{group_id}", settings)
        return True

    def run_auto_sync(self):
        """
        Executes auto-sync for all enabled groups.
        """
        logger.info("[AUTO_SYNC] Starting user auto-sync...")
        
        # 1. Fetch dashboard data to get fully formed groups
        dashboard_data = self.get_users_dashboard_data()
        groups = dashboard_data.get("groups", [])
        
        count = 0
        for group in groups:
            if not group.get("auto_sync"):
                continue
                
            gid = group["id"]
            sync_type = group.get("sync_type", "merge")
            sync_resume = group.get("sync_resume", False)
            users = group.get("users", [])
            
            if len(users) < 2:
                continue
                
            logger.info(f"[AUTO_SYNC] Processing group {group['name']} ({gid}) - Type: {sync_type}")
            
            # Prepare targets tuple list
            targets = [(u["server_id"], u["user_id"]) for u in users]
            
            try:
                if sync_type == "merge":
                    # Bidirectional merge
                    res = self.sync_merge_playstate(targets, include_resume=sync_resume)
                    logger.info(f"[AUTO_SYNC] Merge result for {group['name']}: {res.get('counts')}")
                    
                elif sync_type == "one_way":
                    # One-way from Leader -> Others
                    leader = next((u for u in users if u.get("is_leader")), None)
                    if not leader:
                        # Fallback to first user if no leader
                        leader = users[0]
                        
                    source_server_id = leader["server_id"]
                    source_user_id = leader["user_id"]
                    
                    # Filter targets (exclude leader)
                    dest_targets = [(t[0], t[1]) for t in targets if not (t[0] == source_server_id and t[1] == source_user_id)]
                    
                    if dest_targets:
                        res = self.sync_user_playstate(source_server_id, source_user_id, dest_targets, include_resume=sync_resume)
                        logger.info(f"[AUTO_SYNC] One-way result for {group['name']}: {res.get('counts')}")
                
                count += 1
            except Exception as e:
                logger.error(f"[AUTO_SYNC] Error processing group {group['name']}: {e}")
                
        logger.info(f"[AUTO_SYNC] Completed. Processed {count} groups.")

    def rename_user(self, server_id: str, user_id: str, new_name: str) -> bool:
        """
        Renames a user on the specified server.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        success, _ = _rename_emby_user(server, user_id, new_name)
        return success

    def get_user_extended_details(self, server_id: str, user_id: str) -> Dict[str, Any]:
        server = self._get_server_by_id(server_id)
        if not server:
            return {"error": "Server not found"}
            
        details, err = _fetch_emby_user_details(server, user_id)
        if err or not details:
            return {"error": "User details not found"}
            
        last_played_item = _fetch_emby_user_last_playback(server, user_id)
        
        last_played_text = "Mai"
        last_played_date = None
        
        if last_played_item:
            ud = last_played_item.get("UserData", {})
            last_played_date = ud.get("LastPlayedDate")
            name = last_played_item.get("Name")
            series = last_played_item.get("SeriesName")
            if series:
                last_played_text = f"{series} - {name}"
            else:
                last_played_text = name
                
        return {
            "last_activity_date": details.get("LastActivityDate"),
            "date_created": details.get("DateCreated"),
            "last_played_date": last_played_date,
            "last_played_title": last_played_text,
            "has_password": details.get("HasPassword", False),
            # Add other interesting details
            "connect_user_name": details.get("ConnectUserName"),
            "connect_link_type": details.get("ConnectLinkType")
        }

    def toggle_remote_access(self, server_id: str, user_id: str, enable: bool) -> bool:
        """
        Toggles remote access for a user.
        Controls: EnableRemoteAccess.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        details, err = _fetch_emby_user_details(server, user_id)
        if err or not details:
            return False
            
        policy = details.get("Policy", {})
        policy["EnableRemoteAccess"] = enable
        
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

    def link_users(self, links: List[Dict[str, Any]], group_id: Optional[str] = None) -> str:
        """
        Links multiple users into a single group.
        links: list of {"server_id": "...", "user_id": "...", "username": "...", "is_leader": bool}
        Returns the new group_id.
        """
        if group_id:
            reassign_groups: set[str] = set()
            for link in links:
                existing_links = self.storage.get_user_links(
                    server_id=link["server_id"],
                    user_id=link["user_id"]
                )
                if existing_links:
                    old_group_id = existing_links[0]["group_id"]
                    was_leader = existing_links[0].get("is_leader", False)
                    if old_group_id != group_id and was_leader:
                        reassign_groups.add(old_group_id)
                self.storage.set_user_link(
                    link["server_id"],
                    link["user_id"],
                    group_id,
                    link.get("username"),
                    is_leader=link.get("is_leader", False)
                )
                self._ensure_user_password_inherits_group(
                    group_id,
                    link["server_id"],
                    link["user_id"]
                )
            group_entry = self.storage.get_group_password(group_id)
            if not group_entry or not group_entry.get("password_enc"):
                leader_link = next((link_item for link_item in links if link_item.get("is_leader")), None)
                if leader_link:
                    chosen_password = self._get_user_plain_password(
                        leader_link["server_id"],
                        leader_link["user_id"]
                    )
                    if chosen_password:
                        enc = self._encrypt_password(chosen_password)
                        self.storage.save_group_password(group_id, enc)
                        logger.info(
                            "[PASSWORD] Inherited group password from leader for group: %s",
                            group_id
                        )
                        for link in links:
                            self._ensure_user_password_inherits_group(
                                group_id,
                                link["server_id"],
                                link["user_id"]
                            )
                    else:
                        logger.info(
                            "[PASSWORD] Group %s has no password; leader selected but no saved password.",
                            group_id
                        )
                else:
                    logger.info(
                        "[PASSWORD] Group %s has no password; no leader selected, skipping inheritance.",
                        group_id
                    )

            for old_group_id in reassign_groups:
                self._promote_next_group_leader(old_group_id)
            return group_id

        existing_group_ids = set()
        reassign_groups: set[str] = set()
        for link in links:
            current_links = self.storage.get_user_links(
                server_id=link["server_id"],
                user_id=link["user_id"]
            )
            if current_links:
                existing_group_ids.add(current_links[0]["group_id"])
                if current_links[0].get("is_leader", False):
                    reassign_groups.add(current_links[0]["group_id"])
        source_group_id = existing_group_ids.pop() if len(existing_group_ids) == 1 else None

        new_group_id = str(uuid.uuid4())

        # Check if any user is marked as leader in the request
        has_leader = any(link.get("is_leader") for link in links)

        for link in links:
            # If no explicit leader, try to auto-detect "Master"
            is_leader = link.get("is_leader", False)
            if not has_leader and link.get("username", "").lower() == "master":
                is_leader = True
                has_leader = True # Only one auto-master

            self.storage.set_user_link(
                link["server_id"],
                link["user_id"],
                new_group_id,
                link.get("username"),
                is_leader=is_leader
            )

        group_password_enc = None
        if source_group_id:
            entry = self.storage.get_group_password(source_group_id)
            if entry and entry.get("password_enc"):
                group_password_enc = entry["password_enc"]
                self.storage.save_group_password(new_group_id, group_password_enc)
                logger.info(
                    "[PASSWORD] Migrated group password: %s -> %s",
                    source_group_id,
                    new_group_id
                )
        else:
            candidates = {}
            for link in links:
                candidate = self._get_user_plain_password(link["server_id"], link["user_id"])
                if candidate:
                    candidates[(link["server_id"], link["user_id"])] = candidate
            unique_candidates = set(candidates.values())
            chosen_password = None
            if len(unique_candidates) == 1:
                chosen_password = next(iter(unique_candidates))
                logger.info(
                    "[PASSWORD] Inherited group password from linked users: %s",
                    new_group_id
                )
            elif len(unique_candidates) > 1:
                leader_link = next((link_item for link_item in links if link_item.get("is_leader")), None)
                if leader_link:
                    chosen_password = candidates.get((leader_link["server_id"], leader_link["user_id"]))
                if chosen_password:
                    logger.info(
                        "[PASSWORD] Inherited group password from leader: %s",
                        new_group_id
                    )
            if chosen_password:
                group_password_enc = self._encrypt_password(chosen_password)
                self.storage.save_group_password(new_group_id, group_password_enc)

        if group_password_enc:
            for link in links:
                self._ensure_user_password_inherits_group(
                    new_group_id,
                    link["server_id"],
                    link["user_id"]
                )
        for old_group_id in reassign_groups:
            if old_group_id != new_group_id:
                self._promote_next_group_leader(old_group_id)
        return new_group_id

    def _link_clone_to_source_group(
        self,
        source_server_id: str,
        source_user_id: str,
        source_username: Optional[str],
        target_server_id: str,
        target_user_id: str,
        target_username: Optional[str]
    ) -> str:
        """
        Links cloned target user to the same group as the source.
        If the source has no group, create a new one with source + target.
        Returns the group_id used/created.
        """
        links = self.storage.get_user_links(server_id=source_server_id, user_id=source_user_id)
        if links:
            group_id = links[0]["group_id"]
            logger.info(
                "[CLONE][2/4] Source already linked, adding target to group: %s",
                group_id
            )
            self.storage.set_user_link(
                target_server_id,
                target_user_id,
                group_id,
                target_username,
                is_leader=False
            )
            self._ensure_user_password_inherits_group(
                group_id,
                target_server_id,
                target_user_id
            )
            return group_id

        # Source not linked: create a new group with source + target
        logger.info(
            "[CLONE][2/4] Source not linked, creating new group with source + target"
        )
        source_name = source_username or "User"
        payload = [
            {
                "server_id": source_server_id,
                "user_id": source_user_id,
                "username": source_name,
                "is_leader": True
            },
            {
                "server_id": target_server_id,
                "user_id": target_user_id,
                "username": target_username or "User",
                "is_leader": False
            }
        ]
        group_id = self.link_users(payload)
        logger.info(
            "[CLONE][2/4] New group created for clone link: %s",
            group_id
        )
        return group_id

    def unlink_user(self, server_id: str, user_id: str) -> None:
        """Removes a user from their link group. If only one user remains, dissolve group."""
        # 1. Find current group
        links = self.storage.get_user_links(server_id=server_id, user_id=user_id)

        was_leader = False
        if links:
            group_id = links[0]["group_id"]
            was_leader = bool(links[0].get("is_leader", False))
            self._ensure_user_password_inherits_group(group_id, server_id, user_id)
        
        # 2. Remove the user
        self.storage.remove_user_link(server_id, user_id)
        
        # 3. Check remaining users in the group
        if links:
            group_id = links[0]["group_id"]
            remaining = self.storage.get_user_links(group_id=group_id)
            if len(remaining) == 1:
                # Dissolve: Remove the last user too
                last_user = remaining[0]
                self._ensure_user_password_inherits_group(
                    group_id,
                    last_user["server_id"],
                    last_user["user_id"]
                )
                self.storage.remove_user_link(last_user["server_id"], last_user["user_id"])
            elif remaining and was_leader:
                self._promote_next_group_leader(group_id)

    def _promote_next_group_leader(self, group_id: str) -> None:
        if group_id.startswith("unlinked_") or group_id == "owners":
            return
        dashboard = self.get_users_dashboard_data()
        group = next((g for g in dashboard.get("groups", []) if g.get("id") == group_id), None)
        if not group:
            return
        users = group.get("users", [])
        if not users:
            return
        new_leader = users[0]
        leader_key = (new_leader["server_id"], new_leader["user_id"])
        for user in users:
            is_leader = (user["server_id"], user["user_id"]) == leader_key
            self.storage.set_user_link(
                user["server_id"],
                user["user_id"],
                group_id,
                user.get("name"),
                is_leader=is_leader
            )
        logger.info(
            "[GROUP] Promoted new leader for group %s: %s/%s",
            group_id,
            new_leader["server_id"],
            new_leader["user_id"]
        )

    def _get_password_cipher(self) -> Fernet:
        if self._password_cipher is not None:
            return self._password_cipher
        secret = os.environ.get("PASSWORD_SECRET") or os.environ.get("SECRET_KEY") or "change-this-secret-key"
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        self._password_cipher = Fernet(key)
        return self._password_cipher

    def _encrypt_password(self, plaintext: str) -> str:
        cipher = self._get_password_cipher()
        token = cipher.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def _decrypt_password(self, token: str) -> Optional[str]:
        try:
            cipher = self._get_password_cipher()
            return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            logger.error("[PASSWORD] Decrypt failed: %s", exc)
            return None

    def _resolve_group_id_for_user(self, server_id: str, user_id: str) -> str:
        links = self.storage.get_user_links(server_id=server_id, user_id=user_id)
        if links:
            return links[0]["group_id"]
        return f"unlinked_{server_id}_{user_id}"

    def _get_unlinked_group_id(self, server_id: str, user_id: str) -> str:
        return f"unlinked_{server_id}_{user_id}"

    def _get_user_password_entry(self, server_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self.storage.get_group_password(self._get_unlinked_group_id(server_id, user_id))

    def _get_user_plain_password(self, server_id: str, user_id: str) -> Optional[str]:
        entry = self._get_user_password_entry(server_id, user_id)
        if not entry or not entry.get("password_enc"):
            return None
        return self._decrypt_password(entry["password_enc"])

    def _ensure_user_password_inherits_group(self, group_id: str, server_id: str, user_id: str) -> None:
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
        return

    def _get_group_users(self, group_id: str) -> List[Tuple[str, str, Optional[str]]]:
        if group_id == "owners":
            data = self.get_users_dashboard_data()
            owners = next((g for g in data.get("groups", []) if g.get("id") == "owners"), None)
            if not owners:
                return []
            return [(u["server_id"], u["user_id"], u.get("name")) for u in owners.get("users", [])]

        if group_id.startswith("unlinked_"):
            rest = group_id[len("unlinked_"):]
            if "_" in rest:
                server_id, user_id = rest.split("_", 1)
                return [(server_id, user_id, None)]
            return []

        links = self.storage.get_user_links(group_id=group_id)
        return [(link["server_id"], link["user_id"], link.get("username")) for link in links]

    def get_group_password_info(self, group_id: str) -> Dict[str, Any]:
        entry = self.storage.get_group_password(group_id)
        if not entry:
            logger.info("[PASSWORD] Read: group=%s saved=false", group_id)
            return {"ok": True, "group_id": group_id, "saved": False, "password": None, "updated_at": None}
        password = self._decrypt_password(entry["password_enc"]) if entry.get("password_enc") else None
        logger.info("[PASSWORD] Read: group=%s saved=%s", group_id, bool(password))
        return {
            "ok": True,
            "group_id": group_id,
            "saved": bool(password),
            "password": password,
            "updated_at": entry.get("updated_at")
        }

    def get_password_info(self, group_id: Optional[str] = None, server_id: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        if not group_id:
            if not server_id or not user_id:
                return {"ok": False, "error": "Missing target"}
            group_id = self._get_unlinked_group_id(server_id, user_id)
        return self.get_group_password_info(group_id)

    def set_group_password(self, group_id: str, new_password: str) -> Dict[str, Any]:
        new_password = new_password or ""
        users = self._get_group_users(group_id)
        if not users:
            return {"ok": False, "error": "Group has no users", "group_id": group_id}

        logger.info("[PASSWORD] Apply: group=%s users=%s", group_id, len(users))
        failures = []
        applied = 0
        for server_id, user_id, username in users:
            server = self._get_server_by_id(server_id)
            if not server:
                failures.append({"server_id": server_id, "user_id": user_id, "error": "Server not found"})
                continue
            ok, _ = _update_emby_user_password(server, user_id, new_password)
            if ok:
                applied += 1
            else:
                failures.append({"server_id": server_id, "user_id": user_id, "error": "Update failed"})

        if failures:
            logger.error("[PASSWORD] Group update failed for %s: %s", group_id, failures)
            return {"ok": False, "group_id": group_id, "applied": applied, "failed": failures}

        if new_password:
            enc = self._encrypt_password(new_password)
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
        ok, _ = _update_emby_user_password(server, user_id, new_password or "")
        if not ok:
            return {"ok": False, "error": "Update failed"}

        user_password_id = self._get_unlinked_group_id(server_id, user_id)
        if new_password:
            enc = self._encrypt_password(new_password)
            self.storage.save_group_password(user_password_id, enc)
            logger.info("[PASSWORD] Saved user password: %s/%s", server_id, user_id)
        else:
            self.storage.delete_group_password(user_password_id)
            logger.info("[PASSWORD] Cleared user password: %s/%s", server_id, user_id)

        return {"ok": True, "server_id": server_id, "user_id": user_id}

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

    def sync_user_playstate(self, source_server_id: str, source_user_id: str, target_tuples: List[tuple], include_resume: bool = False) -> Dict[str, Any]:
        """
        Syncs watched status (playstate) from source to targets.
        Matches items by ProviderIds (TMDB, IMDB, TVDB) or fallback key.
        """
        source_server = self._get_server_by_id(source_server_id)
        if not source_server:
            return {"error": "Source server not found"}
        try:
            src_user, _ = _fetch_emby_user_details(source_server, source_user_id)
            src_name = src_user.get("Name") if isinstance(src_user, dict) else None
            logger.info(
                "[SYNC][PLAYSTATE][SRC] %s user=%s (%s)",
                source_server.get("alias") or source_server.get("name") or source_server.get("id"),
                src_name,
                source_user_id
            )
        except Exception:
            pass

        # 1. Get Source Items
        src_items, err = _fetch_emby_user_items_for_sync(source_server, source_user_id, include_resume=include_resume)
        if err:
            return {"error": f"Failed to fetch source items: {err}"}

        # Index source items by Provider IDs or fallback keys
        src_map = {}
        resume_map = {}
        resume_source_items = 0
        played_items = 0
        provider_keys = set()
        fallback_keys_no_provider = set()
        fallback_items_no_provider = []

        def _is_provider_key(key: str) -> bool:
            return key.startswith(("tmdb:", "imdb:", "tvdb:"))
        for item in src_items:
            ud = item.get("UserData", {})
            keys = self._get_item_sync_keys(item)
            if not keys:
                continue

            provider_item_keys = [k for k in keys if _is_provider_key(k)]
            if provider_item_keys:
                provider_keys.update(provider_item_keys)
            else:
                for k in keys:
                    fallback_keys_no_provider.add(k)
                if len(fallback_items_no_provider) < 200:
                    try:
                        fallback_items_no_provider.append({
                            "name": item.get("Name"),
                            "series": item.get("SeriesName"),
                            "season": item.get("ParentIndexNumber"),
                            "episode": item.get("IndexNumber"),
                            "year": item.get("ProductionYear"),
                            "provider_ids": item.get("ProviderIds", {}),
                            "keys": keys
                        })
                    except Exception:
                        pass

            # Track resume position even if item is not fully played
            if include_resume and ud.get("PlaybackPositionTicks"):
                resume_source_items += 1
                for key in keys:
                    resume_map[key] = {
                        "position": ud.get("PlaybackPositionTicks"),
                        "last_played": ud.get("LastPlayedDate")
                    }

            if not ud.get("Played"):
                continue
            played_items += 1

            for key in keys:
                src_map[key] = {
                    "last_played": ud.get("LastPlayedDate")
                }

        try:
            logger.info(
                "[SYNC][PLAYSTATE] source: items=%s played=%s resume_items=%s resume_keys=%s provider_keys=%s fallback_keys=%s include_resume=%s",
                len(src_items),
                played_items,
                resume_source_items,
                len(resume_map),
                len(provider_keys),
                len(fallback_keys_no_provider),
                include_resume
            )
            if fallback_items_no_provider:
                logger.info(
                    "[SYNC][PLAYSTATE] fallback items (no provider ids): count=%s items=%s",
                    len(fallback_items_no_provider),
                    fallback_items_no_provider
                )
        except Exception:
            pass

        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}}

        # 2. Apply to targets
        for tgt_srv_id, tgt_uid in target_tuples:
            tgt_server = self._get_server_by_id(tgt_srv_id)
            if not tgt_server:
                continue
            try:
                tgt_user, _ = _fetch_emby_user_details(tgt_server, tgt_uid)
                tgt_name = tgt_user.get("Name") if isinstance(tgt_user, dict) else None
                logger.info(
                    "[SYNC][PLAYSTATE][TGT] %s user=%s (%s)",
                    tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id"),
                    tgt_name,
                    tgt_uid
                )
            except Exception:
                pass

            target_label = tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id")

            # Resolve target items by provider IDs (fast path)
            provider_items = []
            provider_err = None
            if provider_keys:
                provider_items, provider_err = _fetch_emby_items_by_provider_ids(
                    tgt_server,
                    tgt_uid,
                    list(provider_keys),
                    include_played=False
                )
                if provider_err:
                    logger.warning(
                        "[SYNC][PLAYSTATE] provider lookup failed on %s: %s",
                        target_label,
                        provider_err
                    )
                else:
                    try:
                        logger.info(
                            "[SYNC][PLAYSTATE] target resolved by providers: keys=%s items=%s on %s",
                            len(provider_keys),
                            len(provider_items),
                            target_label
                        )
                    except Exception:
                        pass

            items_to_process = []
            provider_item_ids = {it.get("Id") for it in provider_items if it.get("Id")}
            use_full_scan = bool(provider_err)

            # Fallback scan only for items without provider IDs (or if provider lookup failed)
            if use_full_scan or fallback_keys_no_provider:
                all_items, err = self._fetch_all_media_for_user(tgt_server, tgt_uid)
                if err:
                    results["failed"].append(f"{tgt_server['name']}: Fetch error")
                    continue
                if use_full_scan:
                    items_to_process = all_items
                    try:
                        logger.info(
                            "[SYNC][PLAYSTATE] target items fetched: %s items on %s",
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
                else:
                    fallback_items = []
                    for item in all_items:
                        it_id = item.get("Id")
                        if it_id in provider_item_ids:
                            continue
                        keys = self._get_item_sync_keys(item)
                        if not keys:
                            continue
                        if any(k in fallback_keys_no_provider for k in keys):
                            fallback_items.append(item)
                    items_to_process = provider_items + fallback_items
                    try:
                        logger.info(
                            "[SYNC][PLAYSTATE] fallback scan: keys=%s matched=%s from %s items on %s",
                            len(fallback_keys_no_provider),
                            len(fallback_items),
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
            else:
                items_to_process = provider_items

            updated_count = 0
            resume_count = 0
            processed = 0
            apply_started = time.monotonic()
            try:
                logger.info(
                    "[SYNC][PLAYSTATE] apply start: total=%s on %s",
                    len(items_to_process),
                    target_label
                )
            except Exception:
                pass
            for item in items_to_process:
                processed += 1
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

                # Apply resume even if played (if resume info exists)
                if include_resume:
                    rmatch = None
                    for key in keys:
                        if key in resume_map:
                            rmatch = resume_map[key]
                            break
                    if rmatch:
                        ok, _ = _set_emby_item_resume(
                            tgt_server,
                            tgt_uid,
                            item["Id"],
                            rmatch["position"]
                        )
                        if ok:
                            updated_count += 1
                            resume_count += 1

                if processed % 5000 == 0:
                    try:
                        elapsed = time.monotonic() - apply_started
                        logger.info(
                            "[SYNC][PLAYSTATE] progress: %s/%s processed, played=%s resume=%s, elapsed=%.1fs",
                            processed,
                            len(items_to_process),
                            updated_count - resume_count,
                            resume_count,
                            elapsed
                        )
                    except Exception:
                        pass
            
            results["success"].append(tgt_server['name'])
            results["counts"][tgt_server['name']] = updated_count
            results["resume_counts"][tgt_server['name']] = resume_count
            try:
                logger.info(
                    "[SYNC][PLAYSTATE] applied: played=%s resume=%s on %s",
                    updated_count - resume_count,
                    resume_count,
                    tgt_server.get("alias") or tgt_server.get("name") or tgt_server.get("id")
                )
            except Exception:
                pass
            
        return results

    def sync_merge_playstate(self, targets: List[tuple], include_resume: bool = False) -> Dict[str, Any]:
        """
        Bidirectional sync: Merges played status from ALL targets and applies to ALL.
        targets: list of (server_id, user_id)
        """
        global_played_map = {} # Key -> {last_played: date}
        global_resume_map = {} # Key -> {position: ticks, last_played: date}
        provider_keys = set()
        fallback_keys_no_provider = set()

        def _is_provider_key(key: str) -> bool:
            return key.startswith(("tmdb:", "imdb:", "tvdb:"))
        
        # 1. Gather phase
        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server:
                continue
            
            items, err = _fetch_emby_user_items_for_sync(server, uid, include_resume=include_resume)
            if err:
                continue
            
            for item in items:
                ud = item.get("UserData", {})
                keys = self._get_item_sync_keys(item)
                if not keys:
                    continue

                provider_item_keys = [k for k in keys if _is_provider_key(k)]
                if provider_item_keys:
                    provider_keys.update(provider_item_keys)
                else:
                    for k in keys:
                        fallback_keys_no_provider.add(k)

                if not ud.get("Played"):
                    # Still track resume if enabled
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        for key in keys:
                            existing = global_resume_map.get(key)
                            current = {
                                "position": ud.get("PlaybackPositionTicks"),
                                "last_played": ud.get("LastPlayedDate")
                            }
                            if not existing:
                                global_resume_map[key] = current
                            else:
                                if current["position"] and (not existing["position"] or current["position"] > existing["position"]):
                                    global_resume_map[key] = current
                    continue

                date_played = ud.get("LastPlayedDate")
                
                for key in keys:
                    if key not in global_played_map:
                        global_played_map[key] = {"last_played": date_played}
                    else:
                        # Compare dates string ISO
                        current = global_played_map[key]["last_played"]
                        if date_played and (not current or date_played > current):
                            global_played_map[key]["last_played"] = date_played
                    if include_resume and ud.get("PlaybackPositionTicks"):
                        existing = global_resume_map.get(key)
                        current_resume = {
                            "position": ud.get("PlaybackPositionTicks"),
                            "last_played": ud.get("LastPlayedDate")
                        }
                        if not existing:
                            global_resume_map[key] = current_resume
                        else:
                            if current_resume["position"] and (not existing["position"] or current_resume["position"] > existing["position"]):
                                global_resume_map[key] = current_resume

        results = {"success": [], "failed": [], "counts": {}, "resume_counts": {}}

        # 2. Apply phase
        for srv_id, uid in targets:
            server = self._get_server_by_id(srv_id)
            if not server:
                continue
            
            target_label = server.get("alias") or server.get("name") or server.get("id")

            provider_items = []
            provider_err = None
            if provider_keys:
                provider_items, provider_err = _fetch_emby_items_by_provider_ids(
                    server,
                    uid,
                    list(provider_keys),
                    include_played=False
                )
                if provider_err:
                    logger.warning(
                        "[SYNC][MERGE] provider lookup failed on %s: %s",
                        target_label,
                        provider_err
                    )
                else:
                    try:
                        logger.info(
                            "[SYNC][MERGE] target resolved by providers: keys=%s items=%s on %s",
                            len(provider_keys),
                            len(provider_items),
                            target_label
                        )
                    except Exception:
                        pass

            provider_item_ids = {it.get("Id") for it in provider_items if it.get("Id")}
            use_full_scan = bool(provider_err)

            if use_full_scan or fallback_keys_no_provider:
                all_items, err = self._fetch_all_media_for_user(server, uid)
                if err:
                    results["failed"].append(f"{server['name']}")
                    continue
                if use_full_scan:
                    items_to_process = all_items
                    try:
                        logger.info(
                            "[SYNC][MERGE] target items fetched: %s items on %s",
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
                else:
                    fallback_items = []
                    for item in all_items:
                        it_id = item.get("Id")
                        if it_id in provider_item_ids:
                            continue
                        keys = self._get_item_sync_keys(item)
                        if not keys:
                            continue
                        if any(k in fallback_keys_no_provider for k in keys):
                            fallback_items.append(item)
                    items_to_process = provider_items + fallback_items
                    try:
                        logger.info(
                            "[SYNC][MERGE] fallback scan: keys=%s matched=%s from %s items on %s",
                            len(fallback_keys_no_provider),
                            len(fallback_items),
                            len(all_items),
                            target_label
                        )
                    except Exception:
                        pass
            else:
                items_to_process = provider_items
                
            updated_count = 0
            resume_count = 0
            for item in items_to_process:
                ud = item.get("UserData", {})
                if ud.get("Played") and not include_resume:
                    continue # Already played locally
                
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
                    if ok:
                        updated_count += 1

                if include_resume:
                    rmatch = None
                    for key in keys:
                        if key in global_resume_map:
                            rmatch = global_resume_map[key]
                            break
                    if rmatch:
                        ok, _ = _set_emby_item_resume(
                            server,
                            uid,
                            item["Id"],
                            rmatch["position"]
                        )
                        if ok:
                            updated_count += 1
                            resume_count += 1
            
            results["success"].append(server['name'])
            results["counts"][server['name']] = updated_count
            results["resume_counts"][server['name']] = resume_count
            
        return results

    def check_user_exists(self, server_id: str, username: str) -> bool:
        """
        Checks if a user with the given name exists on the specified server.
        """
        server = self._get_server_by_id(server_id)
        if not server:
            return False
            
        users, err = _fetch_emby_users_list(server)
        if err:
            return False
            
        return any(u["Name"].lower() == username.lower() for u in users)

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
            
        # 1. Fetch Source
        src_user, err = _fetch_emby_user_details(src_server, source_user_id)
        if not src_user:
            return {"error": "Source user not found"}
        logger.info(
            "[CLONE][2/4] Source resolved: %s -> user=%s (%s)",
            _srv_label(src_server),
            src_user.get("Name"),
            source_user_id
        )
            
        # Use provided username or fallback to source name
        target_username = new_username.strip() if new_username and new_username.strip() else src_user["Name"]
        if new_username and new_username.strip() and new_username.strip() != src_user.get("Name"):
            logger.info(
                "[CLONE][2/4] Target username override: '%s' -> '%s'",
                src_user.get("Name"),
                target_username
            )
        
        # 2. Check/Create Target
        # Fetch target user list
        tgt_users, _ = _fetch_emby_users_list(tgt_server)
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
            ok, res = _create_emby_user(tgt_server, target_username)
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
                group_id = self._link_clone_to_source_group(
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
            except Exception as e:
                logger.error("[CLONE][2/4] Failed to link target to group: %s", e)
        else:
            logger.info("[CLONE][2/4] Group link skipped (link_group=False)")
            
        # 3. Sync Config & Policy (Safe)
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
        
        # 4. Sync Playstate (One-way Source -> Target)
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
            res_play = self.sync_user_playstate(
                source_server_id,
                source_user_id,
                [(target_server_id, tgt_user_id)],
                include_resume=sync_resume
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

    def _fetch_all_media_for_user(self, server, user_id):
        # Fetch ALL generic items (Movie, Episode) to match IDs
        # We need ProviderIds and UserData
        from .api_client import _call_emby_api
        params = {
            "Recursive": "true",
            "Fields": "ProviderIds,UserData,SeriesName,ParentIndexNumber,IndexNumber,ProductionYear,Name,OriginalTitle",
            "IncludeItemTypes": "Movie,Episode",
            "IsPlayed": "false" # Optimization: Only fetch unplayed to mark them?
            # Actually, if we want full map we need all. 
            # But for merge/sync we only need to act on unplayed items that SHOULD be played.
            # So fetching "IsPlayed=false" is enough for the target application phase!
        }
        items = []
        start_index = 0
        page_size = 200

        while True:
            page_params = dict(params)
            page_params["StartIndex"] = str(start_index)
            page_params["Limit"] = str(page_size)

            success, payload = _call_emby_api(server, f"Users/{user_id}/Items", params=page_params)
            if not success:
                return [], payload

            if not isinstance(payload, dict):
                return [], "Risposta Emby inattesa"

            page_items = payload.get("Items", []) or []
            items.extend(page_items)

            total = payload.get("TotalRecordCount")
            if total is None:
                if len(page_items) < page_size:
                    break
            else:
                if start_index + len(page_items) >= total:
                    break

            if len(page_items) == 0:
                break

            start_index += len(page_items)

        try:
            name = server.get("name") or server.get("alias") or server.get("id") or "server"
            logger.info(
                "[Emby Sync] unplayed: fetched %s items for user %s on %s",
                len(items),
                user_id,
                name
            )
        except Exception:
            pass

        return items, None

    def _get_item_sync_keys(self, item: Dict[str, Any]) -> List[str]:
        """
        Generates a list of unique keys for an item to be used for sync matching.
        Priority: TMDB, IMDB, TVDB, Name/Year/Index fallback.
        """
        keys = []
        pids = item.get("ProviderIds", {}) or {}
        if isinstance(pids, dict):
            pids = {str(k).lower(): v for k, v in pids.items() if v}
        else:
            pids = {}

        # 1. External IDs
        if pids.get("tmdb"):
            keys.append(f"tmdb:{pids['tmdb']}")
        if pids.get("imdb"):
            keys.append(f"imdb:{pids['imdb']}")
        if pids.get("tvdb"):
            keys.append(f"tvdb:{pids['tvdb']}")
        
        # 2. Fallback: Name matching
        name = normalize_string(item.get("Name") or "")
        original_name = normalize_string(item.get("OriginalTitle") or "")
        year = item.get("ProductionYear")

        # For Episodes: SeriesName + Season + Episode
        series_name = normalize_string(item.get("SeriesName") or "")
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
