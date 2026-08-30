import copy
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Callable

from .api_client import _fetch_emby_users_list

logger = logging.getLogger(__name__)


def _is_stale_running_sync(updated_at: Optional[str], max_age_minutes: int = 30) -> bool:
    if not updated_at:
        return False
    try:
        normalized = updated_at.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - timestamp).total_seconds() > max_age_minutes * 60
    except Exception:
        return False


class UsersDashboardManager:
    def __init__(
        self,
        storage,
        config: Dict[str, Any],
        password_manager,
        settings_manager,
        get_unlinked_group_id: Callable[[str, str], str],
    ):
        self.storage = storage
        self.config = config
        self.password_manager = password_manager
        self.settings_manager = settings_manager
        self._get_unlinked_group_id = get_unlinked_group_id

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

            users = copy.deepcopy(users)

            for u in users:
                u["_server_id"] = server["id"]
                u["_server_name"] = server["name"]
                all_users_raw.append(u)

        # 1b. Identify Server Owners (First Created Admin)
        server_oldest_admin_map = {}
        server_map = {s["id"]: s for s in active_servers}

        for u in all_users_raw:
            policy = u.get("Policy", {})
            if not policy.get("IsAdministrator"):
                continue

            sid = u["_server_id"]
            created_str = u.get("DateCreated")
            if not created_str:
                continue

            try:
                current = server_oldest_admin_map.get(sid)
                if not current or created_str < current["date"]:
                    server_oldest_admin_map[sid] = {"date": created_str, "uid": u["Id"]}
            except Exception as e:
                logger.warning(f"Error checking user date {u.get('Name')}: {e}")

        # 2. Get existing links from DB
        links = self.storage.get_user_links()
        link_map = {}
        for link in links:
            link_map[(link["server_id"], link["user_id"])] = {
                "group_id": link["group_id"],
                "is_leader": link.get("is_leader", False)
            }

        # 3. Group users
        grouped_users = {}
        owners_users = []
        password_map = {}
        password_plain_map: Dict[str, Optional[str]] = {}
        settings_group_map: Dict[str, Dict[str, Any]] = {}
        settings_user_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

        def _get_plain_password(group_id: str) -> Optional[str]:
            if group_id in password_plain_map:
                return password_plain_map[group_id]
            entry = password_map.get(group_id)
            if not entry or not entry.get("password_enc"):
                password_plain_map[group_id] = None
                return None
            password_plain_map[group_id] = self.password_manager.decrypt_saved_password(
                group_id,
                entry["password_enc"],
            )
            return password_plain_map[group_id]

        # Load custom group names and settings
        custom_names = {}
        group_settings = {}
        try:
            kv_keys = self.storage.get_keys_by_prefix("group_name:")
            for k in kv_keys:
                gid = k.split(":", 1)[1]
                val = self.storage.get_key_value(k)
                if val:
                    custom_names[gid] = val

            setting_keys = self.storage.get_keys_by_prefix("group_settings:")
            for k in setting_keys:
                gid = k.split(":", 1)[1]
                val = self.storage.get_key_value(k)
                if val:
                    group_settings[gid] = val

            for entry in self.storage.get_group_passwords():
                password_map[entry["group_id"]] = entry

            group_setting_keys = self.storage.get_keys_by_prefix("emby_group_settings:")
            for key in group_setting_keys:
                gid = key.split(":", 1)[1]
                entry = self.settings_manager.load_settings_entry(key)
                if entry:
                    settings_group_map[gid] = entry

            user_setting_keys = self.storage.get_keys_by_prefix("emby_user_settings:")
            for key in user_setting_keys:
                rest = key.split(":", 1)[1]
                parts = rest.split(":")
                if len(parts) >= 2:
                    sid = parts[0]
                    uid = parts[1]
                    entry = self.settings_manager.load_settings_entry(key)
                    if entry:
                        settings_user_map[(sid, uid)] = entry

        except Exception as e:
            logger.error(f"Error loading group names/settings: {e}")

        for u in all_users_raw:
            sid = u["_server_id"]
            uid = u["Id"]
            name = u["Name"]
            policy = u.get("Policy", {})
            is_admin = policy.get("IsAdministrator", False)

            current_server = server_map.get(sid, {})

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
                image_url = f"/api/v1/emby/image?{urlencode(query)}"

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
                "is_leader": False
            }

            is_server_owner = (sid in server_oldest_admin_map and server_oldest_admin_map[sid]["uid"] == uid)

            if is_admin and is_server_owner:
                owners_users.append(u_data)
                continue

            link_info = link_map.get((sid, uid))
            gid = link_info["group_id"] if link_info else f"unlinked_{sid}_{uid}"
            db_is_leader = link_info["is_leader"] if link_info else False
            u_data["is_leader"] = db_is_leader

            if gid not in grouped_users:
                g_settings = group_settings.get(gid) or {}
                pw_entry = password_map.get(gid)
                group_plain = _get_plain_password(gid)
                settings_entry = settings_group_map.get(gid)
                group_settings_saved = bool(settings_entry and settings_entry.get("settings"))
                last_sync_status = g_settings.get("last_sync_status")
                last_sync_at = g_settings.get("last_sync_at")
                last_sync_message = g_settings.get("last_sync_message")
                if last_sync_status == "running" and _is_stale_running_sync(last_sync_at):
                    last_sync_status = "interrupted"
                    last_sync_message = "Sincronizzazione interrotta o processo riavviato"

                grouped_users[gid] = {
                    "id": gid,
                    "name": custom_names.get(gid) or name,
                    "users": [],
                    "is_linked": not gid.startswith("unlinked_"),
                    "has_custom_name": gid in custom_names,
                    "auto_sync": g_settings.get("auto_sync", False),
                    "sync_type": g_settings.get("sync_type", "merge"),
                    "sync_resume": g_settings.get("sync_resume", False),
                    "sync_playstate": g_settings.get("sync_playstate", True),
                    "sync_config": g_settings.get("sync_config", False),
                    "sync_library_access": g_settings.get("sync_library_access", False),
                    "sync_favorites": g_settings.get("sync_favorites", False),
                    "sync_playlists": g_settings.get("sync_playlists", False),
                    "config_categories": g_settings.get("config_categories", []),
                    "playstate_bootstrap_done": g_settings.get("playstate_bootstrap_done", False),
                    "favorites_bootstrap_done": g_settings.get("favorites_bootstrap_done", False),
                    "playlists_bootstrap_done": g_settings.get("playlists_bootstrap_done", False),
                    "last_sync_at": last_sync_at,
                    "last_sync_status": last_sync_status,
                    "last_sync_message": last_sync_message,
                    "last_sync_results": g_settings.get("last_sync_results"),
                    "password_saved": bool(group_plain),
                    "password_updated_at": pw_entry.get("updated_at") if pw_entry else None,
                    "password_status": "saved" if group_plain else "missing",
                    "password_mismatch": False,
                    "password_mismatch_count": 0,
                    "settings_saved": group_settings_saved,
                    "settings_updated_at": settings_entry.get("updated_at") if settings_entry else None,
                    "settings_status": "saved" if group_settings_saved else "missing",
                    "settings_mismatch": False,
                    "settings_mismatch_count": 0
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

            settings_entry = settings_group_map.get(gid)
            group_settings_value = settings_entry.get("settings") if settings_entry else None
            user_settings_entry = settings_user_map.get((sid, uid))
            user_settings_value = user_settings_entry.get("settings") if user_settings_entry else None
            user_settings_saved = bool(user_settings_value)
            group_settings_saved = bool(group_settings_value)
            settings_mismatch = False
            if grouped_users[gid]["is_linked"]:
                if group_settings_saved:
                    if user_settings_saved and not self.settings_manager.settings_equal(user_settings_value, group_settings_value):
                        settings_mismatch = True
                        grouped_users[gid]["settings_mismatch"] = True
                        grouped_users[gid]["settings_mismatch_count"] += 1
                    if user_settings_saved:
                        settings_status = "mismatch" if settings_mismatch else "saved"
                    else:
                        settings_status = "missing"
                else:
                    settings_status = "mismatch" if user_settings_saved else "missing"
                    if user_settings_saved:
                        settings_mismatch = True
            else:
                settings_status = "saved" if user_settings_saved else "missing"

            u_data["settings_saved"] = settings_status == "saved"
            u_data["settings_status"] = settings_status
            u_data["settings_mismatch"] = settings_mismatch
            grouped_users[gid]["users"].append(u_data)

            if not grouped_users[gid].get("has_custom_name"):
                current_name = grouped_users[gid]["name"]
                if len(name) > len(current_name):
                    grouped_users[gid]["name"] = name

        # Sort users within regular groups
        for group in grouped_users.values():
            group["users"].sort(key=lambda x: (
                not x["is_leader"],
                x["is_disabled"],
                x["name"]
            ))
            if group.get("password_saved") and group.get("password_mismatch"):
                group["password_status"] = "mismatch"
            else:
                group["password_status"] = "saved" if group.get("password_saved") else "missing"

            if group.get("settings_saved") and group.get("settings_mismatch"):
                group["settings_status"] = "mismatch"
            else:
                group["settings_status"] = "saved" if group.get("settings_saved") else "missing"

        final_groups = list(grouped_users.values())

        if owners_users:
            owners_users.sort(key=lambda x: x["server_name"])
            owners_pw_plain = _get_plain_password("owners")
            owners_pw_entry = password_map.get("owners")
            for u in owners_users:
                u["password_saved"] = bool(owners_pw_plain)
                u["password_status"] = "saved" if owners_pw_plain else "missing"
                u["settings_saved"] = False
                u["settings_status"] = "missing"
                u["settings_mismatch"] = False
            final_groups.append({
                "id": "owners",
                "name": "Proprietari",
                "users": owners_users,
                "is_linked": False,
                "is_owners": True,
                "has_custom_name": True,
                "password_saved": bool(owners_pw_plain),
                "password_updated_at": owners_pw_entry.get("updated_at") if owners_pw_entry else None,
                "password_status": "saved" if owners_pw_plain else "missing",
                "password_mismatch": False,
                "password_mismatch_count": 0,
                "settings_saved": False,
                "settings_updated_at": None,
                "settings_status": "missing",
                "settings_mismatch": False,
                "settings_mismatch_count": 0
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
