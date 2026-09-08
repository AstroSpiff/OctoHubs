"""Saved Emby user settings presets."""

from __future__ import annotations

import copy
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.storage.field_limits import (
    SETTINGS_PRESET_ID_MAX_LENGTH,
    require_bounded_text,
    require_key_value_key,
)
from .mutation_coordinator import UserMutationCoordinator


PRESET_KEY_PREFIX = "emby_user_settings_preset:"


class SettingsPresetManager:
    def __init__(self, storage, settings_manager, mutation_coordinator: UserMutationCoordinator | None = None):
        self.storage = storage
        self.settings_manager = settings_manager
        # Preset routes run in the thread pool; keep each read-modify-write atomic.
        self._mutation_lock = threading.RLock()
        self._mutation_coordinator = mutation_coordinator or UserMutationCoordinator(storage)

    def _mutation_guard(self):
        return self._mutation_coordinator.guard(["emby-user-settings-presets"])

    def _key(self, preset_id: str) -> str:
        bounded_id = require_bounded_text(
            preset_id,
            field="preset_id",
            max_length=SETTINGS_PRESET_ID_MAX_LENGTH,
        )
        return require_key_value_key(f"{PRESET_KEY_PREFIX}{bounded_id}")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_id(self, label: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]
        suffix = uuid.uuid4().hex[:8]
        return f"{slug or 'preset'}-{suffix}"

    def _normalize_label(self, label: str) -> str:
        return re.sub(r"\s+", " ", (label or "").strip()).lower()

    def _find_preset_by_label(
        self,
        label: str,
        exclude_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_label(label)
        if not normalized:
            return None
        for key in self.storage.get_keys_by_prefix(PRESET_KEY_PREFIX):
            value = self.storage.get_key_value(key)
            if not isinstance(value, dict):
                continue
            preset_id = str(value.get("id") or "")
            if exclude_id and preset_id == exclude_id:
                continue
            existing_label = value.get("label") or value.get("name") or ""
            if self._normalize_label(str(existing_label)) == normalized:
                return value
        return None

    def _sanitize_settings(self, settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return self.settings_manager._normalize_settings_payload(settings or {}, protect_fields=True)

    def list_presets(self) -> List[Dict[str, Any]]:
        presets: List[Dict[str, Any]] = []
        for key in self.storage.get_keys_by_prefix(PRESET_KEY_PREFIX):
            value = self.storage.get_key_value(key)
            if isinstance(value, dict) and value.get("id"):
                presets.append(self._public_payload(value, include_settings=False))
        presets.sort(key=lambda item: str(item.get("label") or "").lower())
        return presets

    def get_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        if not preset_id:
            return None
        value = self.storage.get_key_value(self._key(preset_id))
        if not isinstance(value, dict):
            return None
        return self._public_payload(value, include_settings=True)

    def save_preset(
        self,
        label: str,
        settings: Optional[Dict[str, Any]],
        preset_id: Optional[str] = None,
        description: str = "",
        apply_libraries: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if preset_id is not None:
            preset_id = require_bounded_text(
                preset_id,
                field="preset_id",
                max_length=SETTINGS_PRESET_ID_MAX_LENGTH,
            )
            self._key(preset_id)
        with self._mutation_lock:
            with self._mutation_guard() as acquired:
                if not acquired:
                    return {"ok": False, "busy": True, "error": "Modifica preset già in corso"}
                return self._save_preset_locked(
                    label,
                    settings,
                    preset_id,
                    description,
                    apply_libraries,
                )

    def _save_preset_locked(
        self,
        label: str,
        settings: Optional[Dict[str, Any]],
        preset_id: Optional[str],
        description: str,
        apply_libraries: Optional[bool],
    ) -> Dict[str, Any]:
        label = re.sub(r"\s+", " ", (label or "").strip())
        if not label:
            return {"ok": False, "error": "Nome preset mancante"}

        requested_id = (preset_id or "").strip()
        preset_id = requested_id or self._make_id(label)
        existing = self.storage.get_key_value(self._key(preset_id))
        if requested_id and not isinstance(existing, dict):
            return {"ok": False, "error": "Preset non trovato"}

        duplicate = self._find_preset_by_label(label, exclude_id=preset_id)
        if duplicate:
            return {"ok": False, "error": "Nome preset gia esistente"}

        if not isinstance(existing, dict):
            existing = {}

        now = self._now()
        if apply_libraries is None:
            apply_libraries = isinstance(settings, dict) and "libraries" in settings

        payload = {
            "id": preset_id,
            "label": label,
            "description": (description or "").strip(),
            "settings": self._sanitize_settings(settings),
            "apply_libraries": bool(apply_libraries),
            "schema_version": self.settings_manager.get_settings_schema().get("schema_version"),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self.storage.set_key_value(self._key(preset_id), payload)
        return {"ok": True, "preset": self._public_payload(payload, include_settings=True)}

    def duplicate_preset(self, preset_id: str, label: Optional[str] = None) -> Dict[str, Any]:
        preset_id = require_bounded_text(
            preset_id,
            field="preset_id",
            max_length=SETTINGS_PRESET_ID_MAX_LENGTH,
        )
        self._key(preset_id)
        with self._mutation_lock:
            with self._mutation_guard() as acquired:
                if not acquired:
                    return {"ok": False, "busy": True, "error": "Modifica preset già in corso"}
                preset = self.get_preset(preset_id)
                if not preset:
                    return {"ok": False, "error": "Preset non trovato"}
                new_label = (label or f"{preset.get('label') or 'Preset'} copia").strip()
                settings = copy.deepcopy(preset.get("settings") or {})
                return self._save_preset_locked(
                    new_label,
                    settings,
                    None,
                    "",
                    bool(preset.get("apply_libraries")),
                )

    def delete_preset(self, preset_id: str) -> Dict[str, Any]:
        preset_id = require_bounded_text(
            preset_id,
            field="preset_id",
            max_length=SETTINGS_PRESET_ID_MAX_LENGTH,
        )
        self._key(preset_id)
        with self._mutation_lock:
            with self._mutation_guard() as acquired:
                if not acquired:
                    return {"ok": False, "busy": True, "error": "Modifica preset già in corso"}
                if not self.get_preset(preset_id):
                    return {"ok": False, "error": "Preset non trovato"}
                self.storage.delete_key(self._key(preset_id))
                return {"ok": True}

    def _public_payload(self, payload: Dict[str, Any], include_settings: bool) -> Dict[str, Any]:
        public = {
            "id": payload.get("id"),
            "label": payload.get("label") or payload.get("name") or "Preset",
            "description": payload.get("description") or "",
            "apply_libraries": bool(payload.get("apply_libraries")),
            "schema_version": payload.get("schema_version"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }
        if include_settings:
            public["settings"] = self._sanitize_settings(payload.get("settings") or {})
        return public
