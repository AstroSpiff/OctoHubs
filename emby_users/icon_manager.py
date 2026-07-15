import base64
import logging
import os
import uuid
from typing import Dict, Any, Optional, Tuple, Callable

import requests

from emby_runtime.api_clients import _emby_base_url
from core.utils import get_nested

logger = logging.getLogger(__name__)


class IconManager:
    def __init__(
        self,
        storage,
        get_users_dashboard_data: Callable[[], Dict[str, Any]],
        get_server_by_id: Callable[[str], Optional[Dict[str, Any]]],
    ):
        self.storage = storage
        self._get_users_dashboard_data = get_users_dashboard_data
        self._get_server_by_id = get_server_by_id

    def migrate_icons_to_db(self) -> None:
        """
        Migrates existing file-based icons to the database.
        """
        try:
            rules = self.storage.get_icon_rules()
            for rule in rules:
                if not rule.get("has_data") and rule.get("icon_path"):
                    path = rule["icon_path"]
                    if path.startswith("user_icons/"):
                        full_path = os.path.join(os.getcwd(), "static", path)
                        if os.path.exists(full_path):
                            try:
                                with open(full_path, "rb") as f:
                                    data = f.read()
                                mime = "image/png"
                                if full_path.lower().endswith(".jpg") or full_path.lower().endswith(".jpeg"):
                                    mime = "image/jpeg"

                                new_path = f"/api/emby/icons/image/{rule['profile_id']}/{rule['column_key']}"
                                self.storage.save_icon_rule(rule['profile_id'], rule['column_key'], new_path, data, mime)
                                logger.info("Migrated icon to DB: %s", full_path)
                            except Exception as exc:
                                logger.error("Failed to migrate icon %s: %s", full_path, exc)
        except Exception as exc:
            logger.error("Migration error: %s", exc)

    def get_icon_dashboard_data(self) -> Dict[str, Any]:
        """
        Returns all data needed to render the Icon Matrix UI.
        """
        profiles = self.storage.get_icon_profiles()
        profiles.sort(key=lambda p: p['label'].lower())
        rules = self.storage.get_icon_rules()
        bindings = self.storage.get_icon_bindings()

        matrix = {}
        for r in rules:
            if r["profile_id"] not in matrix:
                matrix[r["profile_id"]] = {}
            matrix[r["profile_id"]][r["column_key"]] = r["icon_path"]

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
        self.storage.save_icon_profile(profile_id, label, is_group_profile)
        return profile_id

    def delete_icon_profile(self, profile_id: str) -> None:
        self.storage.delete_icon_profile(profile_id)

    def save_icon_binding(self, target_type: str, target_id: str, profile_id: str) -> None:
        """
        Binds a User or Group to a Profile and triggers sync.
        An empty profile removes the binding without changing the Emby image.
        """
        if not (profile_id or "").strip():
            self.storage.delete_icon_binding(target_type, target_id)
            return
        self.storage.save_icon_binding(target_type, target_id, profile_id)
        self._sync_icons_for_binding(target_type, target_id)

    def save_icon_rule(self, profile_id: str, column_key: str, file_storage) -> str:
        """
        Saves an uploaded icon file to DB and creates the rule. Triggers sync.
        file_storage: FastAPI UploadFile or similar
        """
        file_storage.file.seek(0)
        data = file_storage.file.read()

        filename = file_storage.filename or "icon.png"
        mime_type = file_storage.content_type or "image/png"

        ext = os.path.splitext(filename)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            mime_type = "image/jpeg"
        elif ext == '.png':
            mime_type = "image/png"

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

    def _sync_icons_for_rule(self, profile_id: str, column_key: str) -> None:
        self._apply_icon_logic(filter_profile_id=profile_id, filter_column_key=column_key)

    def _sync_icons_for_binding(self, target_type: str, target_id: str) -> None:
        self._apply_icon_logic(filter_target_type=target_type, filter_target_id=target_id)

    def _apply_icon_logic(self, filter_profile_id=None, filter_column_key=None, filter_target_type=None, filter_target_id=None) -> None:
        dashboard_data = self._get_users_dashboard_data()
        groups = dashboard_data["groups"]
        bindings = self.storage.get_icon_bindings()

        binding_map = {f"{b['target_type']}:{b['target_id']}": b['profile_id'] for b in bindings}

        rules = self.storage.get_icon_rules()
        rule_map = {}
        for r in rules:
            if r['profile_id'] not in rule_map:
                rule_map[r['profile_id']] = {}
            rule_map[r['profile_id']][r['column_key']] = r['icon_path']

        for group in groups:
            group_id = group["id"]
            group_profile_id = binding_map.get(f"group:{group_id}")
            leader_user = next((u for u in group["users"] if u.get("is_leader")), None)
            group_ref_server_id = leader_user["server_id"] if leader_user else None

            for user in group["users"]:
                server_id = user["server_id"]
                user_id = user["user_id"]

                if filter_target_type == "group" and filter_target_id != group_id:
                    continue
                if filter_target_type == "user" and filter_target_id != f"{server_id}:{user_id}":
                    continue

                profile_id = None
                reference_server_id = None
                is_group_application = False
                user_binding_key = ""

                if group_profile_id:
                    if not group_ref_server_id:
                        logger.warning("[ICON_LOGIC] Group %s (%s) has binding but NO LEADER. Skipping.", group['name'], group_id)
                        continue
                    profile_id = group_profile_id
                    reference_server_id = group_ref_server_id
                    is_group_application = True
                else:
                    user_binding_key = f"user:{server_id}:{user_id}"
                    user_profile_id = binding_map.get(user_binding_key)
                    if user_profile_id:
                        profile_id = user_profile_id
                        reference_server_id = server_id
                        is_group_application = False

                if not is_group_application:
                    logger.info("[ICON_DEBUG] Check User: %s | Key=%s | Profile=%s", user['name'], user_binding_key, profile_id)

                if not profile_id:
                    continue

                if filter_profile_id and filter_profile_id != profile_id:
                    continue

                if filter_column_key and filter_column_key != reference_server_id:
                    continue

                icon_path = get_nested(rule_map, profile_id, reference_server_id)

                if is_group_application:
                    logger.info(
                        "[ICON_DEBUG] Group Apply: Group=%s | Leader=%s@%s | Member=%s@%s | Profile=%s | RefServer=%s | Icon=%s",
                        group['name'],
                        (leader_user['name'] if leader_user else 'Unknown'),
                        group_ref_server_id,
                        user['name'],
                        server_id,
                        profile_id,
                        reference_server_id,
                        'FOUND' if icon_path else 'EMPTY'
                    )

                if icon_path:
                    self._upload_icon_to_emby(server_id, user_id, profile_id, str(reference_server_id))

    def _upload_icon_to_emby(self, server_id: str, user_id: str, profile_id: str, column_key: str) -> None:
        server = self._get_server_by_id(server_id)
        if not server:
            logger.error("[ICON_UPLOAD] Server not found: %s", server_id)
            return

        try:
            data_tuple = self.get_icon_image(profile_id, column_key)
            if not data_tuple:
                logger.error("[ICON_UPLOAD] Icon data not found for %s/%s", profile_id, column_key)
                return

            raw_bytes, mime_type = data_tuple
            b64_data = base64.b64encode(raw_bytes)
        except Exception as exc:
            logger.error("[ICON_UPLOAD] Failed to read file: %s", exc)
            return

        base_url = _emby_base_url(server)
        token = server.get("api_key")

        user_url = f"{base_url}/Users/{user_id}"
        image_url = f"{base_url}/Users/{user_id}/Images/Primary"
        headers = {"X-Emby-Token": token}

        old_tag = "N/A"
        try:
            r = requests.get(user_url, headers=headers, timeout=10)
            if r.ok:
                old_tag = r.json().get("PrimaryImageTag", "None")
            logger.info("[ICON_UPLOAD] Pre-check %s@%s: OldTag=%s", user_id, server['name'], old_tag)
        except Exception as exc:
            logger.warning("[ICON_UPLOAD] Pre-check failed: %s", exc)

        headers["Content-Type"] = mime_type
        try:
            logger.info("[ICON_UPLOAD] Uploading Base64 to %s (Original Size: %s)", image_url, len(raw_bytes))
            response = requests.post(image_url, headers=headers, data=b64_data, timeout=30)
            if not response.ok:
                logger.error("[ICON_UPLOAD] Status: %s - %s", response.status_code, response.text)
            response.raise_for_status()
        except Exception as exc:
            logger.error("[ICON_UPLOAD] Upload Failed: %s", exc)
            return

        try:
            r = requests.get(user_url, headers={"X-Emby-Token": token}, timeout=10)
            new_tag = "N/A"
            if r.ok:
                new_tag = r.json().get("PrimaryImageTag", "None")

            logger.info("[ICON_UPLOAD] Post-check: NewTag=%s", new_tag)

            if new_tag != old_tag:
                logger.info("[ICON_UPLOAD] SUCCESS: Tag changed %s -> %s", old_tag, new_tag)
            elif new_tag == "None":
                logger.warning("[ICON_UPLOAD] FAILURE: Tag is None (Image not set?)")
        except Exception as exc:
            logger.warning("[ICON_UPLOAD] Verify failed: %s", exc)
