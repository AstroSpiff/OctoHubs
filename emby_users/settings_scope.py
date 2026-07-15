"""Selectable and protected user-settings sync scopes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set, Tuple


DEFAULT_CONFIG_CATEGORIES = {
    "profile",
    "access",
    "display",
    "home",
    "playback_prefs",
    "profile_pin",
    "subtitles",
}

PROTECTED_POLICY_FIELDS = {
    "IsAdministrator",
    "IsDisabled",
    "Authentication",
    "AuthenticationProviderId",
    "Password",
    "LockedOutDate",
    "InvalidLoginAttemptCount",
    "LoginAttemptsBeforeLockout",
    "EnableAllFolders",
    "EnabledFolders",
    "EnabledLibraryFolders",
    "EnabledMediaFolders",
    "ExcludedSubFolders",
    "BlockedTags",
    "BlockedMediaTags",
    "AccessSchedules",
    "MaxActiveSessions",
    "SyncPlayfield",
}

PROTECTED_CONFIG_FIELDS = {
    "GroupedFolders",
    "DashboardLayout",
    "HomePageSectionOrder",
    "LandingScreen",
}

PROTECTED_DISPLAY_PREF_FIELDS: Set[str] = set()


def normalize_config_categories(raw: Any) -> Set[str]:
    if raw is None:
        return set(DEFAULT_CONFIG_CATEGORIES)
    if isinstance(raw, str):
        items = [part.strip() for part in raw.replace("\n", ",").split(",")]
    elif isinstance(raw, Iterable):
        items = [str(part).strip() for part in raw]
    else:
        items = []
    return {item for item in items if item}


def build_allowed_fields(
    schema: list[Dict[str, Any]],
    categories: Optional[Set[str]]
) -> Tuple[Optional[Set[str]], Optional[Set[str]], Optional[Set[str]]]:
    if categories is None:
        return None, None, None
    policy_fields: Set[str] = set()
    config_fields: Set[str] = set()
    display_fields: Set[str] = set()
    category_ids = {item for item in categories if ":" not in item}

    for item in categories:
        scope, _, key = item.partition(":")
        if not key:
            continue
        if scope == "policy":
            policy_fields.add(key)
        elif scope == "config":
            config_fields.add(key)
        elif scope == "display_preferences":
            display_fields.add(key)

    for category in schema:
        if category.get("id") not in category_ids:
            continue
        policy_fields.update(field["key"] for field in category.get("policy", []) if field.get("key"))
        config_fields.update(field["key"] for field in category.get("config", []) if field.get("key"))
        display_fields.update(field["key"] for field in category.get("display_preferences", []) if field.get("key"))
    return policy_fields, config_fields, display_fields


def can_sync_policy_field(key: str, allowed_fields: Optional[Set[str]] = None) -> bool:
    if key in PROTECTED_POLICY_FIELDS:
        return False
    if allowed_fields is not None and key not in allowed_fields:
        return False
    return True


def can_sync_config_field(key: str, allowed_fields: Optional[Set[str]] = None) -> bool:
    if key in PROTECTED_CONFIG_FIELDS:
        return False
    if allowed_fields is not None and key not in allowed_fields:
        return False
    return True


def can_sync_display_field(key: str, allowed_fields: Optional[Set[str]] = None) -> bool:
    if key in PROTECTED_DISPLAY_PREF_FIELDS:
        return False
    if allowed_fields is None:
        return True
    if key in allowed_fields:
        return True
    if key.startswith("landing-") and "__library_landing__" in allowed_fields:
        return True
    if key == "localplayersubtitleappearance3":
        return any(field.startswith("localplayersubtitleappearance3.") for field in allowed_fields)
    return False
