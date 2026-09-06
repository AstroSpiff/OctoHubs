"""Stream semantics and policy-state helpers for Transcode Guard."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from emby_runtime.transcode_guard_constants import (
    TRANSCODE_GUARD_ACTION_LABELS,
)
from emby_runtime.transcode_guard_values import (
    _extract_video_height,
    _has_subtitle_burn_reason,
    _server_label,
)

def _stream_identity_fields(server: Dict[str, Any], stream: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    server_id = str(server.get("id") or stream.get("server_id") or "")
    session_id = str(stream.get("session_id") or "")
    position_seconds = _ticks_to_seconds(stream.get("position_ticks") or stream.get("playback_position_ticks"))
    duration_seconds = _ticks_to_seconds(stream.get("runtime_ticks") or stream.get("duration_ticks"))
    playback_percent = None
    if position_seconds is not None and duration_seconds:
        playback_percent = round(min(100.0, max(0.0, position_seconds / duration_seconds * 100.0)), 2)
    source_height = decision.get("source_height") or _extract_video_height(stream)
    return {
        "server_id": server_id,
        "server_name": _server_label(server),
        "session_id": session_id,
        "session_key": str(stream.get("session_key") or f"{server_id}:{session_id}" if session_id else ""),
        "play_session_id": stream.get("play_session_id") or "",
        "media_source_id": stream.get("media_source_id") or "",
        "audio_stream_index": stream.get("audio_stream_index"),
        "subtitle_stream_index": stream.get("subtitle_stream_index"),
        "media_source_id_known": bool(str(stream.get("media_source_id") or "").strip()),
        "audio_stream_index_known": "audio_stream_index" in stream,
        "subtitle_stream_index_known": "subtitle_stream_index" in stream,
        "video_height_known": _extract_video_height(stream) is not None,
        "playback_event_name": stream.get("playback_event_name") or "",
        "item_id": stream.get("item_id") or "",
        "title": stream.get("title") or "Stream",
        "user": stream.get("user") or "",
        "client": stream.get("client") or "",
        "device": stream.get("device") or "",
        "device_id": stream.get("device_id") or "",
        "ip": stream.get("ip") or stream.get("remote_address") or "",
        "media_type": stream.get("media_type") or "",
        "series_name": stream.get("series_name") or "",
        "season_number": stream.get("season_number"),
        "episode_number": stream.get("episode_number"),
        "year": stream.get("year") or "",
        "source_height": source_height,
        "video_height": _extract_video_height(stream),
        "video_width": _to_int_or_none(stream.get("video_width") or stream.get("width")),
        "source_quality_tier": decision.get("source_quality_tier") or "",
        "quality": f"{source_height}p" if source_height else "",
        "video_mode": stream.get("video_mode") or "",
        "audio_mode": stream.get("audio_mode") or "",
        "play_method": stream.get("play_method") or "",
        "container": stream.get("container") or "",
        "stream_container": stream.get("stream_container") or "",
        "transcode_container": stream.get("transcode_container") or "",
        "video_codec": stream.get("video_codec") or "",
        "audio_codec": stream.get("audio_codec") or "",
        "video_label": stream.get("video_label") or "",
        "audio_label": stream.get("audio_label") or "",
        "bitrate": stream.get("bitrate") or stream.get("media_bitrate") or "",
        "transcode_bitrate": stream.get("transcode_bitrate") or "",
        "position_seconds": position_seconds,
        "duration_seconds": duration_seconds,
        "playback_percent": playback_percent,
        "paused": bool(stream.get("paused") or stream.get("is_paused")),
        "transcode_reasons": _normalize_reason_list(stream.get("transcode_reasons") or stream.get("reasons")),
    }


def _stream_observation_tags(stream: Dict[str, Any], decision: Dict[str, Any]) -> List[str]:
    category = str(decision.get("category") or "")
    tags: List[str] = []
    technical = _stream_technical_violations(stream, decision)
    direct_container_remux = category in {"container_remux", "remux"} and not technical
    if direct_container_remux:
        tags.extend(["container remux", "direct stream"])
        if not decision.get("should_enforce"):
            tags.append("corretta")
    elif category == "direct" and not technical and not decision.get("should_enforce"):
        tags.extend(["corretta", "direct play"])
    if "video_transcode" in technical:
        tags.append("transcode video")
    if "audio_transcode" in technical:
        tags.append("transcode audio")
    if "subtitle_burnin" in technical:
        tags.append("sottotitoli burn-in")
    if "remux" in technical:
        tags.append("remux")
    if "browser_playback" in technical:
        tags.append("browser")
    if category == "unknown":
        tags.append("metadati incompleti")
    if bool(stream.get("paused") or stream.get("is_paused")):
        tags.append("pausa")
    if decision.get("should_enforce"):
        tags.append("violazione")
    elif technical:
        tags.append("non monitorata")
    return _unique_ordered(tags)


def _stream_action_tags(action: Optional[Dict[str, Any]]) -> List[str]:
    if not action:
        return []
    label = TRANSCODE_GUARD_ACTION_LABELS.get(str(action.get("action") or ""), str(action.get("action") or ""))
    return [label] if label else []


def _stream_technical_violations(stream: Dict[str, Any], decision: Dict[str, Any]) -> List[str]:
    category = str(decision.get("category") or "")
    violations: List[str] = []
    video_mode = str(stream.get("video_mode") or "").strip().lower()
    audio_mode = str(stream.get("audio_mode") or "").strip().lower()
    reasons = _normalize_reason_list(stream.get("transcode_reasons") or stream.get("reasons"))
    if category in {"video_transcode", "video_audio_transcode", "subtitle_burnin"} or video_mode in {"transcodifica", "transcode"}:
        violations.append("video_transcode")
    if category in {"audio_transcode", "video_audio_transcode"} or audio_mode in {"transcodifica", "transcode"}:
        violations.append("audio_transcode")
    if category == "subtitle_burnin" or _has_subtitle_burn_reason(reasons):
        violations.append("subtitle_burnin")
    if category == "remux":
        violations.append("remux")
    if category == "browser_playback" or _looks_like_browser_playback(stream):
        violations.append("browser_playback")
    if category == "unknown":
        violations.append("unknown_height")
    return _unique_ordered(violations)


def _stream_row_is_correct(row: Dict[str, Any]) -> bool:
    return "corretta" in (row.get("tags") or []) and not row.get("violations_committed")


def _looks_like_browser_playback(stream: Dict[str, Any]) -> bool:
    client = str(stream.get("client") or "").lower()
    return any(token in client for token in ("web", "browser", "chrome", "safari", "firefox", "edge"))


def _normalize_reason_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [value] if "," not in value else value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = [value]
    return _unique_ordered(str(part or "").strip() for part in parts)


def _unique_ordered(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ticks_to_seconds(value: Any) -> Optional[float]:
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return round(ticks / 10_000_000, 3)


def _action_label(actions: List[Dict[str, Any]]) -> str:
    labels = []
    for action in actions:
        key = str(action.get("action") or "")
        label = TRANSCODE_GUARD_ACTION_LABELS.get(key, key or "evento")
        if label and (not labels or labels[-1] != label):
            labels.append(label)
    return " - ".join(labels)


def _last_action(row: Dict[str, Any]) -> str:
    action = _last_action_entry(row)
    return str(action.get("action") or "") if action else str(row.get("action") or "")


def _last_action_entry(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    actions = row.get("actions")
    if isinstance(actions, list) and actions:
        last = actions[-1]
        if isinstance(last, dict):
            return last
    return None


def _is_player_playback_action(action: Dict[str, Any]) -> bool:
    return str(action.get("source") or "guard").strip().lower() in {"player", "plugin", "proxy"}


def _is_terminal_action(action: Optional[Dict[str, Any]]) -> bool:
    if not action:
        return False
    key = str(action.get("action") or "")
    return key in {"exit", "stop"} or (key == "pause" and not _is_player_playback_action(action))


def _terminal_row_has_open_problem(row: Dict[str, Any]) -> bool:
    actions = row.get("actions")
    if not isinstance(actions, list) or not actions:
        return False
    last_action = _last_action_entry(row)
    if not _is_terminal_action(last_action):
        return False
    if str(last_action.get("action") or "") == "stop":
        return True
    for action in reversed(actions[:-1]):
        if not isinstance(action, dict):
            continue
        key = str(action.get("action") or "")
        if _is_terminal_action(action):
            continue
        return key in {"warn", "warning_error", "relapse", "partial_resolved"}
    return False


def _validate_transcode_guard_settings(settings: Dict[str, Any]) -> None:
    for rule in settings.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        if rule.get("server_ids"):
            continue
        name = str(rule.get("name") or "Regola").strip() or "Regola"
        raise ValueError(f'Seleziona almeno un server per "{name}" o disattiva la regola.')
