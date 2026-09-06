"""Event correlation helpers for Transcode Guard."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from emby_runtime.transcode_guard_values import _extract_video_height, _parse_datetime

def _decision(
    category: str,
    reason: str,
    severity: str,
    should_enforce: bool,
    stream: Dict[str, Any],
    settings: Dict[str, Any],
    video_height: Optional[int],
) -> Dict[str, Any]:
    return {
        "category": category,
        "label": reason,
        "reason": reason,
        "severity": severity,
        "should_enforce": bool(should_enforce),
        "source_height": video_height,
        "threshold": settings.get("min_source_height"),
        "mode": settings.get("mode"),
        "session_id": stream.get("session_id") or "",
    }


def _make_event_id(server_id: str, session_id: str, now: float) -> str:
    clean_server = _slug_part(server_id or "server")
    clean_session = _slug_part(session_id or "session")
    return f"{clean_server}:{clean_session}:{int(float(now) * 1000)}"


def _flatten_event_bridge_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    flattened = dict(payload)
    flattened.update({
        "source": "octohubs_event_bridge",
        "eventBridgeTransport": payload.get("_eventBridgeTransport") or payload.get("eventBridgeTransport") or "",
        "serverId": server.get("id") or payload.get("serverId") or payload.get("server_id") or "",
        "messageType": event.get("type") or payload.get("messageType") or payload.get("message_type") or "PluginPlaybackEvent",
        "eventName": event.get("name") or payload.get("eventName") or payload.get("event_name") or "",
        "sessionId": session.get("id") or payload.get("sessionId") or payload.get("session_id") or "",
        "playSessionId": session.get("playSessionId") or payload.get("playSessionId") or payload.get("play_session_id") or "",
        "mediaSourceId": media.get("mediaSourceId") or payload.get("mediaSourceId") or payload.get("media_source_id") or "",
        "audioStreamIndex": media.get("audioStreamIndex") if "audioStreamIndex" in media else payload.get("audioStreamIndex"),
        "subtitleStreamIndex": media.get("subtitleStreamIndex") if "subtitleStreamIndex" in media else payload.get("subtitleStreamIndex"),
        "itemId": item.get("id") or payload.get("itemId") or payload.get("item_id") or "",
    })
    return flattened


def _playback_key(server_id: str, stream: Dict[str, Any]) -> str:
    user = _slug_part(stream.get("user") or "user")
    device = _slug_part(stream.get("device_id") or stream.get("device") or stream.get("client") or "device")
    content = _content_key(stream)
    if not content:
        return ""
    return "|".join([str(server_id or ""), user, device, content])


def _content_key(stream: Dict[str, Any]) -> str:
    media_type = str(stream.get("media_type") or "").strip().lower()
    series = str(stream.get("series_name") or "").strip()
    season = stream.get("season_number")
    episode = stream.get("episode_number")
    if (media_type == "episode" or series) and season is not None and episode is not None:
        return "episode:" + "|".join([
            _slug_part(series or stream.get("title") or "series"),
            _slug_part(season if season is not None else ""),
            _slug_part(episode if episode is not None else ""),
        ])
    item_id = str(stream.get("item_id") or "").strip()
    if item_id:
        return f"item:{item_id}"
    title = str(stream.get("title") or "").strip()
    year = str(stream.get("year") or "").strip()
    if not title:
        return ""
    return "title:" + "|".join([_slug_part(title), _slug_part(year)])


def _matching_other_violation(
    matches: Optional[List[Dict[str, Any]]],
    current_key: str,
) -> Optional[Dict[str, Any]]:
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("key") or "") != str(current_key or ""):
            return match
    return None


def _matching_other_rule_violation(
    match: Optional[Dict[str, Any]],
    current_rule_id: Any,
) -> Optional[Dict[str, Any]]:
    if not isinstance(match, dict):
        return None
    decision = match.get("decision") if isinstance(match.get("decision"), dict) else {}
    if str(decision.get("rule_id") or "") == str(current_rule_id or ""):
        return None
    return match


def _resolved_action_for_stream(previous: Dict[str, Any], stream: Dict[str, Any]) -> Tuple[str, str]:
    if _same_source_resolution(previous, stream):
        return "resolved", "Risolta"
    return "resolution_change", "Cambio risoluzione"


def _later_success_action_for_stream(previous: Dict[str, Any], stream: Dict[str, Any]) -> Tuple[str, str]:
    if _same_source_resolution(previous, stream):
        return "resolved_later", "Risolto in seguito"
    return "resolution_change", "Cambio risoluzione"


def _same_source_resolution(previous: Dict[str, Any], stream: Dict[str, Any]) -> bool:
    previous_height = _extract_video_height(previous)
    current_height = _extract_video_height(stream)
    if previous_height is None or current_height is None:
        return True
    return abs(previous_height - current_height) <= 80


def _observed_stream_change_actions(
    previous: Dict[str, Any],
    stream: Dict[str, Any],
    decision: Dict[str, Any],
) -> List[Tuple[str, str]]:
    actions: List[Tuple[str, str]] = []
    previous_source = str(previous.get("media_source_id") or "").strip()
    current_source = str(stream.get("media_source_id") or "").strip()
    previous_height = _extract_video_height(previous)
    current_height = decision.get("source_height") or _extract_video_height(stream)
    source_changed = bool(
        previous.get("media_source_id_known")
        and previous_source
        and current_source
        and previous_source != current_source
    )
    height_changed = bool(
        previous.get("video_height_known")
        and
        previous_height is not None
        and current_height is not None
        and not _same_source_resolution(previous, {"video_height": current_height})
    )
    if source_changed or height_changed:
        actions.append(("quality_change", "Cambio qualità"))

    if (
        previous.get("audio_stream_index_known")
        and "audio_stream_index" in stream
        and _stream_value_changed(previous.get("audio_stream_index"), stream.get("audio_stream_index"))
    ):
        actions.append(("audio_change", "Cambio audio"))
    if (
        previous.get("subtitle_stream_index_known")
        and "subtitle_stream_index" in stream
        and _stream_value_changed(previous.get("subtitle_stream_index"), stream.get("subtitle_stream_index"))
    ):
        actions.append(("subtitle_change", "Cambio sottotitoli"))
    return actions


def _stream_value_changed(previous: Any, current: Any) -> bool:
    previous_value = "" if previous is None else str(previous)
    current_value = "" if current is None else str(current)
    return previous_value != current_value


def _is_duplicate_playback_event(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
    keys = (
        "server_id",
        "session_id",
        "play_session_id",
        "media_source_id",
        "event_name",
        "message_type",
        "action",
        "audio_stream_index",
        "subtitle_stream_index",
    )
    if any(str(previous.get(key) or "") != str(current.get(key) or "") for key in keys):
        return False
    previous_at = _parse_datetime(previous.get("at"))
    current_at = _parse_datetime(current.get("at"))
    if previous_at is None or current_at is None:
        return True
    return abs((current_at - previous_at).total_seconds()) <= 2


def _append_stream_action(row: Dict[str, Any], action_entry: Dict[str, Any]) -> None:
    actions = row.setdefault("actions", [])
    action = str(action_entry.get("action") or "")
    if actions and isinstance(actions[-1], dict) and actions[-1].get("action") == action:
        actions[-1].update(action_entry)
    else:
        actions.append(action_entry)


def _camel_action(action: str) -> str:
    return "".join(part.capitalize() for part in str(action or "").split("_") if part)


def _slug_part(value: Any) -> str:
    return str(value or "").strip().lower().replace("|", " ").replace(":", " ")


def _is_corrected_playback(decision: Dict[str, Any]) -> bool:
    if decision.get("should_enforce"):
        return False
    return str(decision.get("category") or "") in {"direct", "container_remux", "remux", "audio_transcode"}
