"""Rule normalization and stream classification for Transcode Guard."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any, Dict, Iterable, List, Optional, Tuple


TRANSCODE_GUARD_MODES = {"monitor", "warn", "stop", "warn_then_stop"}
_LEGACY_MODE_ALIASES = {
    "pause": "stop",
    "warn_then_pause": "warn_then_stop",
}
TRANSCODE_GUARD_RULE_TYPES = {"rule"}
TRANSCODE_GUARD_RULE_PROFILES = {
    "video_transcode_threshold",
    "any_video_transcode",
    "any_transcode",
    "video_audio_transcode",
    "audio_transcode",
    "browser_playback",
    "remux",
}
TRANSCODE_GUARD_STREAM_STATES = {"any", "transcode", "direct"}
TRANSCODE_GUARD_REMUX_STATES = {"any", "present", "absent"}
TRANSCODE_GUARD_TRANSFORMATION_STATES = {"any", "present", "absent"}
TRANSCODE_GUARD_QUALITY_THRESHOLDS = {0, 480, 576, 720, 1080, 1440, 2160}

_LEGACY_PROFILE_CRITERIA: Dict[str, Dict[str, Any]] = {
    "video_transcode_threshold": {
        "video_state": "transcode",
        "audio_state": "any",
        "remux_state": "any",
        "transformation_state": "any",
        "min_source_height": 2160,
    },
    "any_video_transcode": {
        "video_state": "transcode",
        "audio_state": "any",
        "remux_state": "any",
        "transformation_state": "any",
        "min_source_height": 0,
    },
    "any_transcode": {
        "video_state": "any",
        "audio_state": "any",
        "remux_state": "any",
        "transformation_state": "present",
        "min_source_height": 0,
    },
    "video_audio_transcode": {
        "video_state": "transcode",
        "audio_state": "transcode",
        "remux_state": "any",
        "transformation_state": "any",
        "min_source_height": 0,
    },
    "audio_transcode": {
        "video_state": "direct",
        "audio_state": "transcode",
        "remux_state": "any",
        "transformation_state": "any",
        "min_source_height": 0,
    },
    "browser_playback": {
        "video_state": "any",
        "audio_state": "any",
        "remux_state": "any",
        "transformation_state": "any",
        "min_source_height": 0,
    },
    "remux": {
        "video_state": "direct",
        "audio_state": "direct",
        "remux_state": "present",
        "transformation_state": "any",
        "min_source_height": 0,
    },
}

DEFAULT_TRANSCODE_GUARD_RULE: Dict[str, Any] = {
    "id": "legacy-video-transcode",
    "name": "Transcode video sopra soglia",
    "type": "rule",
    "enabled": True,
    "profile": "video_transcode_threshold",
    "mode": "monitor",
    "video_state": "transcode",
    "audio_state": "any",
    "remux_state": "any",
    "transformation_state": "any",
    "min_source_height": 2160,
    "grace_seconds": 0,
    "correction_window_seconds": 60,
    "message_display_mode": "toast",
    "warning_timeout_ms": 45000,
    "max_warnings": 3,
    "message_cooldown_seconds": 30,
    "allow_audio_only_transcode": True,
    "allow_container_remux": True,
    "ignore_paused": True,
    "server_ids": [],
    "excluded_users": [],
    "excluded_clients": [],
    "excluded_devices": [],
    "excluded_ips": [],
    "message_header": "OctoHubs Transcode Guard",
    "message_text": (
        "{title} è in transcodifica video su {server}. "
        "Controlla qualità di riproduzione, versione o client per evitare perdita di qualità."
    ),
    "stop_processing": True,
    "children": [],
}

DEFAULT_TRANSCODE_GUARD_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "mode": "monitor",
    "video_state": "transcode",
    "audio_state": "any",
    "remux_state": "any",
    "transformation_state": "any",
    "min_source_height": 2160,
    "grace_seconds": 0,
    "correction_window_seconds": 60,
    "poll_interval_seconds": 5,
    "stream_history_retention_days": 0,
    "message_display_mode": "toast",
    "warning_timeout_ms": 45000,
    "max_warnings": 3,
    "message_cooldown_seconds": 30,
    "allow_audio_only_transcode": True,
    "allow_container_remux": True,
    "ignore_paused": True,
    "server_ids": [],
    "excluded_users": [],
    "excluded_clients": [],
    "excluded_devices": [],
    "excluded_ips": [],
    "message_header": DEFAULT_TRANSCODE_GUARD_RULE["message_header"],
    "message_text": DEFAULT_TRANSCODE_GUARD_RULE["message_text"],
    "rules": [],
}


def normalize_transcode_guard_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return safe Transcode Guard settings from persisted or API input."""

    raw = raw if isinstance(raw, dict) else {}
    settings = dict(DEFAULT_TRANSCODE_GUARD_SETTINGS)
    settings["enabled"] = _to_bool(raw.get("enabled"), settings["enabled"])
    settings["poll_interval_seconds"] = _bounded_int(
        raw.get("poll_interval_seconds"),
        2,
        120,
        settings["poll_interval_seconds"],
    )
    settings["stream_history_retention_days"] = _bounded_int(
        raw.get("stream_history_retention_days"),
        0,
        3650,
        settings["stream_history_retention_days"],
    )

    for key in ("server_ids", "excluded_users", "excluded_clients", "excluded_devices", "excluded_ips"):
        settings[key] = _normalize_string_list(raw.get(key))

    rules_raw = raw.get("rules")
    if isinstance(rules_raw, list) and rules_raw:
        rules: List[Dict[str, Any]] = []
        for index, item in enumerate(rules_raw):
            if not isinstance(item, dict):
                continue
            rules.extend(_normalize_transcode_guard_rule_entries(item, fallback_id=f"rule-{index + 1}"))
        settings["rules"] = rules
    else:
        settings["rules"] = [_legacy_rule_from_settings(raw)]

    if not settings["rules"]:
        settings["rules"] = [_legacy_rule_from_settings({})]

    _copy_primary_rule_compat_fields(settings)
    return settings


def normalize_transcode_guard_rule(raw: Optional[Dict[str, Any]], *, fallback_id: str = "rule-1") -> Dict[str, Any]:
    """Normalize one policy rule."""

    raw = raw if isinstance(raw, dict) else {}
    rule = dict(DEFAULT_TRANSCODE_GUARD_RULE)
    rule["id"] = _clean_identifier(raw.get("id"), fallback_id)
    rule["name"] = _clean_text(raw.get("name"), "Regola Transcode Guard")
    rule["type"] = "rule"

    profile = str(raw.get("profile") or rule["profile"]).strip()
    rule["profile"] = profile if profile in TRANSCODE_GUARD_RULE_PROFILES else "video_transcode_threshold"
    legacy_criteria = _legacy_profile_criteria(rule["profile"])

    rule["mode"] = _normalize_mode(raw.get("mode"), DEFAULT_TRANSCODE_GUARD_RULE["mode"])
    rule["enabled"] = _to_bool(raw.get("enabled"), rule["enabled"])
    rule["stop_processing"] = _to_bool(raw.get("stop_processing"), rule["stop_processing"])
    rule["video_state"] = _normalize_stream_state(raw.get("video_state"), legacy_criteria["video_state"])
    rule["audio_state"] = _normalize_stream_state(raw.get("audio_state"), legacy_criteria["audio_state"])
    rule["remux_state"] = _normalize_remux_state(raw.get("remux_state"), legacy_criteria["remux_state"])
    rule["transformation_state"] = _normalize_transformation_state(
        raw.get("transformation_state"),
        legacy_criteria["transformation_state"],
    )
    min_source_default = legacy_criteria["min_source_height"]
    rule["min_source_height"] = _normalize_quality_threshold(raw.get("min_source_height"), min_source_default)
    rule["grace_seconds"] = 0
    rule["correction_window_seconds"] = _bounded_int(
        raw.get("correction_window_seconds"),
        0,
        1800,
        rule["correction_window_seconds"],
    )
    message_display_mode = str(raw.get("message_display_mode") or rule["message_display_mode"]).strip()
    rule["message_display_mode"] = message_display_mode if message_display_mode in {"toast", "confirmation"} else "toast"
    rule["warning_timeout_ms"] = _bounded_int(raw.get("warning_timeout_ms"), 1000, 300000, rule["warning_timeout_ms"])
    rule["max_warnings"] = _bounded_int(raw.get("max_warnings"), 1, 10, rule["max_warnings"])
    rule["message_cooldown_seconds"] = _bounded_int(
        raw.get("message_cooldown_seconds"),
        0,
        3600,
        rule["message_cooldown_seconds"],
    )

    for key in ("allow_audio_only_transcode", "allow_container_remux", "ignore_paused"):
        rule[key] = _to_bool(raw.get(key), rule[key])

    for key in ("server_ids", "excluded_users", "excluded_clients", "excluded_devices", "excluded_ips"):
        rule[key] = _normalize_string_list(raw.get(key))

    for key in ("message_header", "message_text"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            rule[key] = value.strip()

    rule["children"] = []
    return rule


def classify_stream(stream: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Classify an active Emby stream for Transcode Guard enforcement."""

    resolved = normalize_transcode_guard_settings(settings or {})
    features = _stream_features(stream)

    rule_decision = _evaluate_rules(stream, resolved, features)
    if rule_decision:
        return rule_decision

    return _fallback_decision(stream, resolved, features)


def _legacy_rule_from_settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(DEFAULT_TRANSCODE_GUARD_RULE)
    for key in (
        "mode",
        "video_state",
        "audio_state",
        "remux_state",
        "transformation_state",
        "min_source_height",
        "grace_seconds",
        "correction_window_seconds",
        "message_display_mode",
        "warning_timeout_ms",
        "max_warnings",
        "message_cooldown_seconds",
        "allow_audio_only_transcode",
        "allow_container_remux",
        "ignore_paused",
        "server_ids",
        "excluded_users",
        "excluded_clients",
        "excluded_devices",
        "excluded_ips",
        "message_header",
        "message_text",
    ):
        if key in raw:
            payload[key] = raw.get(key)
    return normalize_transcode_guard_rule(payload, fallback_id="legacy-video-transcode")


_GROUP_INHERITED_RULE_FIELDS = (
    "profile",
    "video_state",
    "audio_state",
    "remux_state",
    "transformation_state",
    "min_source_height",
    "mode",
    "grace_seconds",
    "correction_window_seconds",
    "message_display_mode",
    "warning_timeout_ms",
    "max_warnings",
    "message_cooldown_seconds",
    "allow_audio_only_transcode",
    "allow_container_remux",
    "ignore_paused",
    "message_header",
    "message_text",
    "stop_processing",
)


def _normalize_transcode_guard_rule_entries(raw: Dict[str, Any], *, fallback_id: str) -> List[Dict[str, Any]]:
    rule_type = str(raw.get("type") or "rule").strip().lower()
    if rule_type != "group":
        payload = dict(raw)
        payload["type"] = "rule"
        payload["children"] = []
        return [normalize_transcode_guard_rule(payload, fallback_id=fallback_id)]

    children = raw.get("children")
    if not isinstance(children, list) or not children:
        payload = dict(raw)
        payload["type"] = "rule"
        payload["children"] = []
        return [normalize_transcode_guard_rule(payload, fallback_id=fallback_id)]

    rules: List[Dict[str, Any]] = []
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            continue
        rules.extend(
            _normalize_transcode_guard_rule_entries(
                _inherit_group_fields(raw, child),
                fallback_id=f"{fallback_id}-child-{index + 1}",
            )
        )
    return rules


def _inherit_group_fields(group: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(child)
    if group.get("enabled") is False:
        merged["enabled"] = False
    elif "enabled" not in merged and "enabled" in group:
        merged["enabled"] = group.get("enabled")

    for key in _GROUP_INHERITED_RULE_FIELDS:
        if key == "enabled" or key not in group:
            continue
        if _has_rule_value(merged.get(key)):
            continue
        merged[key] = group.get(key)
    return merged


def _has_rule_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(_normalize_string_list(value))
    return value is not None


def _normalize_mode(value: Any, default: str) -> str:
    mode = str(value or default).strip()
    mode = _LEGACY_MODE_ALIASES.get(mode, mode)
    return mode if mode in TRANSCODE_GUARD_MODES else default


def _legacy_profile_criteria(profile: str) -> Dict[str, Any]:
    return dict(_LEGACY_PROFILE_CRITERIA.get(profile) or _LEGACY_PROFILE_CRITERIA["video_transcode_threshold"])


def _normalize_stream_state(value: Any, default: str) -> str:
    state = str(value or default).strip().lower()
    return state if state in TRANSCODE_GUARD_STREAM_STATES else default


def _normalize_remux_state(value: Any, default: str) -> str:
    state = str(value or default).strip().lower()
    return state if state in TRANSCODE_GUARD_REMUX_STATES else default


def _normalize_transformation_state(value: Any, default: str) -> str:
    state = str(value or default).strip().lower()
    return state if state in TRANSCODE_GUARD_TRANSFORMATION_STATES else default


def _normalize_quality_threshold(value: Any, default: int) -> int:
    try:
        threshold = int(value)
    except (TypeError, ValueError):
        threshold = int(default)
    if threshold <= 0:
        return 0
    if threshold in TRANSCODE_GUARD_QUALITY_THRESHOLDS:
        return threshold
    return _bounded_int(threshold, 360, 4320, int(default))


def _copy_primary_rule_compat_fields(settings: Dict[str, Any]) -> None:
    primary = _first_rule(settings.get("rules") or []) or DEFAULT_TRANSCODE_GUARD_RULE
    for key in (
        "mode",
        "video_state",
        "audio_state",
        "remux_state",
        "transformation_state",
        "min_source_height",
        "grace_seconds",
        "correction_window_seconds",
        "message_display_mode",
        "warning_timeout_ms",
        "max_warnings",
        "message_cooldown_seconds",
        "allow_audio_only_transcode",
        "allow_container_remux",
        "ignore_paused",
        "server_ids",
        "excluded_users",
        "excluded_clients",
        "excluded_devices",
        "excluded_ips",
        "message_header",
        "message_text",
    ):
        settings[key] = primary.get(key, DEFAULT_TRANSCODE_GUARD_SETTINGS.get(key))


def _first_rule(rules: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        return rule
    return None


def _evaluate_rules(stream: Dict[str, Any], settings: Dict[str, Any], features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    skipped_decision: Optional[Dict[str, Any]] = None
    for rule in settings.get("rules") or []:
        decision = _evaluate_rule(rule, stream, settings, features, [])
        if decision:
            if decision.pop("_continue", False):
                skipped_decision = decision
                continue
            return decision
    return skipped_decision


def _evaluate_rule(
    rule: Dict[str, Any],
    stream: Dict[str, Any],
    settings: Dict[str, Any],
    features: Dict[str, Any],
    path: List[str],
) -> Optional[Dict[str, Any]]:
    if not rule.get("enabled", True):
        return None

    current_path = [*path, str(rule.get("name") or rule.get("id") or "Regola")]
    if not _rule_applies_to_server(rule, features):
        return None
    if features["paused"] and _effective_setting(rule, "ignore_paused", True):
        decision = _decision(
            "paused",
            "In pausa",
            "muted",
            False,
            stream,
            _rule_settings(settings, rule),
            features["video_height"],
            features["source_quality_tier"],
            rule=rule,
            rule_path=current_path,
        )
        decision["_continue"] = True
        return decision
    exclusion_reason = _rule_exclusion_reason(rule, features)
    if exclusion_reason:
        decision = _decision(
            "excluded",
            exclusion_reason,
            "muted",
            False,
            stream,
            _rule_settings(settings, rule),
            features["video_height"],
            features["source_quality_tier"],
            rule=rule,
            rule_path=current_path,
        )
        decision["_continue"] = True
        return decision

    matched, category, label, severity = _rule_matches(rule, features)
    if not matched:
        return None

    return _decision(
        category,
        label,
        severity,
        _rule_enforces(rule),
        stream,
        _rule_settings(settings, rule),
        features["video_height"],
        features["source_quality_tier"],
        rule=rule,
        rule_path=current_path,
    )


def _rule_applies_to_server(rule: Dict[str, Any], features: Dict[str, Any]) -> bool:
    selected = _normalize_string_list(rule.get("server_ids"))
    server_id = str(features.get("server_id") or "").strip()
    if not server_id:
        return True
    return server_id in {str(item) for item in selected}


def _rule_exclusion_reason(rule: Dict[str, Any], features: Dict[str, Any]) -> str:
    if _matches_any(features["user"], rule.get("excluded_users")):
        return "Utente escluso"
    if _matches_any(features["client"], rule.get("excluded_clients")):
        return "Client escluso"
    if _matches_any(features["device"], rule.get("excluded_devices")):
        return "Device escluso"
    if _ip_matches_any(features["ip"], rule.get("excluded_ips")):
        return "IP escluso"
    return ""


def _rule_matches(rule: Dict[str, Any], features: Dict[str, Any]) -> Tuple[bool, str, str, str]:
    profile = str(rule.get("profile") or "video_transcode_threshold")
    video_direct = features["video_direct"]
    audio_direct = features["audio_direct"]
    video_transcode = not video_direct
    audio_transcode = not audio_direct
    remux = bool(features["remux"])

    if profile == "browser_playback" and not _looks_like_browser(features["client"], features["device"]):
        return False, "", "", "ok"

    if not _stream_state_matches(rule.get("video_state"), video_transcode):
        return False, "", "", "ok"
    if not _stream_state_matches(rule.get("audio_state"), audio_transcode):
        return False, "", "", "ok"
    if not _remux_state_matches(rule.get("remux_state"), remux):
        return False, "", "", "ok"
    if not _transformation_state_matches(rule.get("transformation_state"), video_transcode or audio_transcode or remux):
        return False, "", "", "ok"

    threshold = int(rule.get("min_source_height") or 0)
    if threshold > 0:
        quality_tier = features["source_quality_tier"]
        if quality_tier is None:
            return False, "unknown", "Altezza video sorgente non disponibile", "warning"
        if quality_tier < threshold:
            return False, "", "", "ok"

    if profile == "browser_playback":
        return True, "browser_playback", "Riproduzione da browser", "warning"
    if video_transcode and audio_transcode:
        return True, "video_audio_transcode", "Transcodifica video e audio", "danger"
    if video_transcode:
        if _has_subtitle_burn_reason(features["reasons"]):
            return True, "subtitle_burnin", "Sottotitoli impressi", "danger"
        return True, "video_transcode", "Transcodifica video", "danger"
    if audio_transcode:
        return True, "audio_transcode", "Solo audio transcode", "warning"
    if remux:
        return True, "container_remux", "Remux contenitore", "warning"

    return True, "stream_match", "Regola stream", "warning"


def _rule_enforces(rule: Dict[str, Any]) -> bool:
    return True


def _rule_settings(settings: Dict[str, Any], rule: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(settings)
    for key in (
        "mode",
        "video_state",
        "audio_state",
        "remux_state",
        "transformation_state",
        "min_source_height",
        "grace_seconds",
        "correction_window_seconds",
        "message_display_mode",
        "warning_timeout_ms",
        "max_warnings",
        "message_cooldown_seconds",
        "allow_audio_only_transcode",
        "allow_container_remux",
        "ignore_paused",
        "server_ids",
        "excluded_users",
        "excluded_clients",
        "excluded_devices",
        "excluded_ips",
        "message_header",
        "message_text",
    ):
        if key in rule:
            merged[key] = rule.get(key)
    return merged


def _stream_features(stream: Dict[str, Any]) -> Dict[str, Any]:
    video_direct = _is_direct_mode(stream.get("video_mode"))
    audio_direct = _is_direct_mode(stream.get("audio_mode"))
    video_height = _extract_video_height(stream)
    video_width = _extract_video_width(stream)
    return {
        "title": str(stream.get("title") or "Stream"),
        "server_id": str(stream.get("server_id") or ""),
        "user": str(stream.get("user") or ""),
        "client": str(stream.get("client") or ""),
        "device": str(stream.get("device") or ""),
        "ip": str(stream.get("ip") or ""),
        "video_direct": video_direct,
        "audio_direct": audio_direct,
        "video_height": video_height,
        "video_width": video_width,
        "source_quality_tier": _source_quality_tier(stream, video_width, video_height),
        "reasons": _normalize_string_list(stream.get("transcode_reasons")),
        "paused": bool(stream.get("paused")),
        "remux": _looks_like_remux(stream),
    }


def _fallback_decision(stream: Dict[str, Any], settings: Dict[str, Any], features: Dict[str, Any]) -> Dict[str, Any]:
    video_direct = features["video_direct"]
    audio_direct = features["audio_direct"]
    video_height = features["video_height"]

    if video_height is None and not video_direct:
        return _decision("unknown", "Altezza video sorgente non disponibile", "warning", False, stream, settings, video_height, features["source_quality_tier"])

    if not video_direct:
        return _decision("video_transcode", "Transcodifica video", "warning", False, stream, settings, video_height, features["source_quality_tier"])

    if video_direct and not audio_direct:
        allow = _effective_setting(settings, "allow_audio_only_transcode", True)
        return _decision("audio_transcode", "Solo audio transcode", "ok" if allow else "warning", not allow, stream, settings, video_height, features["source_quality_tier"])

    if video_direct and audio_direct and features["remux"]:
        allow = _effective_setting(settings, "allow_container_remux", True)
        return _decision("container_remux", "Remux contenitore", "ok" if allow else "warning", not allow, stream, settings, video_height, features["source_quality_tier"])

    return _decision("direct", "Direct Play", "ok", False, stream, settings, video_height, features["source_quality_tier"])


def _decision(
    category: str,
    reason: str,
    severity: str,
    should_enforce: bool,
    stream: Dict[str, Any],
    settings: Dict[str, Any],
    video_height: Optional[int],
    source_quality_tier: Optional[int],
    *,
    rule: Optional[Dict[str, Any]] = None,
    rule_path: Optional[List[str]] = None,
) -> Dict[str, Any]:
    rule_id = str(rule.get("id") or "") if isinstance(rule, dict) else ""
    rule_name = str(rule.get("name") or "") if isinstance(rule, dict) else ""
    return {
        "category": category,
        "label": reason,
        "reason": reason,
        "severity": severity,
        "should_enforce": bool(should_enforce),
        "source_height": video_height,
        "source_quality_tier": source_quality_tier,
        "threshold": settings.get("min_source_height"),
        "mode": settings.get("mode"),
        "session_id": stream.get("session_id") or "",
        "rule_id": rule_id,
        "rule_name": rule_name,
        "rule_path": rule_path or ([rule_name] if rule_name else []),
        "profile": rule.get("profile") if isinstance(rule, dict) else "",
        "message_display_mode": settings.get("message_display_mode"),
        "warning_timeout_ms": settings.get("warning_timeout_ms"),
        "max_warnings": settings.get("max_warnings"),
        "message_cooldown_seconds": settings.get("message_cooldown_seconds"),
        "grace_seconds": settings.get("grace_seconds"),
        "correction_window_seconds": settings.get("correction_window_seconds"),
        "message_header": settings.get("message_header"),
        "message_text": settings.get("message_text"),
    }


def _effective_setting(settings: Dict[str, Any], key: str, default: Any) -> Any:
    value = settings.get(key)
    return default if value is None else value


def _looks_like_browser(client: str, device: str) -> bool:
    text = f"{client} {device}".lower()
    markers = ("browser", "web", "chrome", "safari", "firefox", "edge", "opera")
    return any(marker in text for marker in markers)


def _stream_state_matches(state: Any, is_transcoding: bool) -> bool:
    normalized = _normalize_stream_state(state, "any")
    if normalized == "any":
        return True
    if normalized == "transcode":
        return bool(is_transcoding)
    return not is_transcoding


def _remux_state_matches(state: Any, remux: bool) -> bool:
    normalized = _normalize_remux_state(state, "any")
    if normalized == "any":
        return True
    if normalized == "present":
        return bool(remux)
    return not remux


def _transformation_state_matches(state: Any, has_transformation: bool) -> bool:
    normalized = _normalize_transformation_state(state, "any")
    if normalized == "any":
        return True
    if normalized == "present":
        return bool(has_transformation)
    return not has_transformation


def _clean_identifier(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text.lower())
    clean = "-".join(part for part in clean.split("-") if part)
    return clean or fallback


def _clean_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _extract_video_height(stream: Dict[str, Any]) -> Optional[int]:
    for key in ("video_height", "height", "source_height"):
        value = stream.get(key)
        try:
            height = int(value)
        except (TypeError, ValueError):
            continue
        return height if height > 0 else None
    label = str(stream.get("video_label") or "")
    marker = "p"
    for part in label.replace("x", " ").replace("/", " ").split():
        cleaned = part.lower().strip()
        if cleaned.endswith(marker):
            cleaned = cleaned[:-1]
        try:
            height = int(cleaned)
        except ValueError:
            continue
        if 240 <= height <= 4320:
            return height
    return None


def _extract_video_width(stream: Dict[str, Any]) -> Optional[int]:
    for key in ("video_width", "width", "source_width"):
        value = stream.get(key)
        try:
            width = int(value)
        except (TypeError, ValueError):
            continue
        return width if width > 0 else None
    label = str(stream.get("video_label") or "")
    parts = label.replace("/", " ").split()
    for part in parts:
        if "x" not in part.lower():
            continue
        left = part.lower().split("x", 1)[0]
        try:
            width = int(left)
        except ValueError:
            continue
        if 240 <= width <= 8192:
            return width
    return None


def _source_quality_tier(stream: Dict[str, Any], width: Optional[int], height: Optional[int]) -> Optional[int]:
    label = str(stream.get("video_label") or stream.get("quality") or "").lower()
    if any(marker in label for marker in ("2160", "4k", "uhd")):
        return 2160
    if "1440" in label:
        return 1440
    if "1080" in label:
        return 1080
    if "720" in label:
        return 720
    if "576" in label:
        return 576
    if "480" in label:
        return 480

    if width is not None:
        if width >= 3000:
            return 2160
        if width >= 2200:
            return 1440
        if width >= 1600:
            return 1080
        if width >= 1100:
            return 720

    if height is not None:
        if height >= 1600:
            return 2160
        if height >= 1200:
            return 1440
        if height >= 900:
            return 1080
        if height >= 650:
            return 720
        if height >= 540:
            return 576
        if height >= 430:
            return 480
        return height
    return None


def _is_direct_mode(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"diretta", "direct", "directplay", "directstream", "direct play", "direct stream"}


def _looks_like_remux(stream: Dict[str, Any]) -> bool:
    source_container = _normalize_container_name(stream.get("container") or stream.get("stream_container"))
    output_container = _normalize_container_name(stream.get("transcode_container"))
    if output_container and source_container:
        return output_container != source_container
    stream_container = _normalize_container_name(stream.get("stream_container"))
    if stream_container and source_container:
        return stream_container != source_container
    return False


def _normalize_container_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "matroska": "mkv",
        "mpegts": "ts",
        "mpeg-ts": "ts",
        "m3u8": "hls",
    }
    return aliases.get(text, text)


def _has_subtitle_burn_reason(reasons: Iterable[str]) -> bool:
    return any("subtitle" in reason.lower() or "burn" in reason.lower() for reason in reasons)


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    value_norm = str(value or "").strip().lower()
    if not value_norm:
        return False
    return any(value_norm == str(pattern or "").strip().lower() for pattern in patterns or [])


def _ip_matches_any(value: str, patterns: Iterable[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    host = text
    if host.count(":") == 1 and "." in host:
        host = host.rsplit(":", 1)[0]
    try:
        address = ip_address(host)
    except ValueError:
        return _matches_any(text, patterns)
    for pattern in patterns or []:
        item = str(pattern or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                if address in ip_network(item, strict=False):
                    return True
            elif address == ip_address(item):
                return True
        except ValueError:
            if _matches_any(text, [item]):
                return True
    return False


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = [value]
    result = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sì"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(minimum, min(maximum, resolved))
