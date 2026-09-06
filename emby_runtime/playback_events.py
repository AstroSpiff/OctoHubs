"""Normalize Emby playback events used by runtime monitoring features."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


PLAYBACK_EVENT_OUTCOMES = {
    "time_update": "aggiornamento posizione",
    "exit": "uscito",
    "play": "riproduzione",
    "pause": "pausa",
    "unpause": "ripresa",
    "volume_change": "cambio volume",
    "repeat_mode_change": "cambio ripetizione",
    "quality_change": "cambio qualità",
    "audio_change": "cambio audio",
    "subtitle_change": "cambio sottotitoli",
    "playlist_item_move": "playlist: spostamento",
    "playlist_item_remove": "playlist: rimozione",
    "playlist_item_add": "playlist: aggiunta",
    "state_change": "cambio stato",
    "subtitle_offset_change": "cambio offset sottotitoli",
    "playback_rate_change": "cambio velocità",
    "shuffle_change": "cambio shuffle",
    "sleep_timer_change": "cambio sleep timer",
    "player_event": "evento player",
    "plugin_event": "evento plugin",
}
PLUGIN_SOURCE_ALIASES = {
    "plugin",
    "emby_plugin",
    "octohubs_plugin",
    "octohubs_event_bridge",
    "octohubs.eventbridge",
    "event_bridge",
}


def normalize_emby_playback_event(server_id: str, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return OctoHubs' internal playback event shape for Emby WebSocket events."""
    events = normalize_emby_playback_events(server_id, event_data)
    return events[0] if events else None


def normalize_emby_playback_events(server_id: str, event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all concrete playback events contained in an Emby WebSocket payload."""
    if not isinstance(event_data, dict):
        return []
    message_type = str(_first_value(event_data, "MessageType", "messageType", "message_type") or "").strip()
    if message_type == "Sessions":
        return [
            event
            for session in _extract_session_payloads(event_data)
            for event in [_normalize_single_event(server_id, event_data, session, message_type)]
            if event
        ]
    data = event_data.get("Data") if isinstance(event_data.get("Data"), dict) else {}
    event = _normalize_single_event(server_id, event_data, data, message_type)
    return [event] if event else []


def _normalize_single_event(
    server_id: str,
    event_data: Dict[str, Any],
    data: Dict[str, Any],
    message_type: str,
) -> Optional[Dict[str, Any]]:
    play_state = data.get("PlayState") if isinstance(data.get("PlayState"), dict) else {}
    explicit_event_name = str(
        _first_value(play_state, "EventName", "eventName", "event_name")
        or _first_value(data, "EventName", "eventName", "event_name")
        or _first_value(event_data, "EventName", "eventName", "event_name")
        or _first_value(play_state, "Name", "name")
        or _first_value(data, "Name", "name")
        or _first_value(event_data, "Name", "name")
        or _first_value(play_state, "Command", "command")
        or _first_value(data, "Command", "command")
        or _first_value(event_data, "Command", "command")
        or ""
    ).strip()
    event_name = str(
        explicit_event_name
        or message_type
        or ""
    ).strip()
    session_id = _extract_session_id(event_data, data, play_state)
    action = playback_event_action(event_name, message_type)
    if not action and explicit_event_name:
        action = "player_event"
    if not action or not session_id:
        return None
    return {
        "server_id": str(server_id or event_data.get("server_id") or data.get("server_id") or ""),
        "session_id": session_id,
        "event_name": event_name,
        "message_type": message_type,
        "action": action,
        "outcome": PLAYBACK_EVENT_OUTCOMES.get(action, action),
        "play_session_id": str(
            _first_value(play_state, "PlaySessionId", "playSessionId", "play_session_id")
            or _first_value(data, "PlaySessionId", "playSessionId", "play_session_id")
            or _first_value(event_data, "PlaySessionId", "playSessionId", "play_session_id")
            or ""
        ).strip(),
        "media_source_id": str(
            _first_value(play_state, "MediaSourceId", "mediaSourceId", "media_source_id")
            or _first_value(data, "MediaSourceId", "mediaSourceId", "media_source_id")
            or _first_value(event_data, "MediaSourceId", "mediaSourceId", "media_source_id")
            or ""
        ).strip(),
        "audio_stream_index": _first_present(play_state, data, event_data, keys=("AudioStreamIndex", "audioStreamIndex", "audio_stream_index")),
        "subtitle_stream_index": _first_present(play_state, data, event_data, keys=("SubtitleStreamIndex", "subtitleStreamIndex", "subtitle_stream_index")),
        "source": _event_source(event_data, data),
        "transport": _event_transport(event_data, data),
        "raw": event_data,
    }


def playback_event_action(event_name: str, message_type: str = "") -> str:
    """Map Emby event names to Transcode Guard action names."""
    key = str(event_name or "").strip().lower()
    message = str(message_type or "").strip().lower()
    combined = key or message
    if combined in {"stopped", "stop", "playbackstopped", "playbackstop"}:
        return "exit"
    if combined in {"play", "playing", "playbackstart", "playbackstarted"}:
        return "play"
    if combined in {"timeupdate", "progress"}:
        return "time_update"
    if combined in {"pause", "paused"}:
        return "pause"
    if combined in {"unpause", "unpaused", "resume", "resumed"}:
        return "unpause"
    if combined in {"volumechange", "volumechanged"}:
        return "volume_change"
    if combined in {"repeatmodechange", "repeatmodechanged"}:
        return "repeat_mode_change"
    if combined in {"qualitychange", "qualitychanged"}:
        return "quality_change"
    if combined in {"audiotrackchange", "audiotrackchanged", "audiochange"}:
        return "audio_change"
    if combined in {"subtitletrackchange", "subtitletrackchanged", "subtitlechange"}:
        return "subtitle_change"
    if combined in {"playlistitemmove", "playlistitemmoved"}:
        return "playlist_item_move"
    if combined in {"playlistitemremove", "playlistitemremoved"}:
        return "playlist_item_remove"
    if combined in {"playlistitemadd", "playlistitemadded"}:
        return "playlist_item_add"
    if combined in {"statechange", "statechanged"}:
        return "state_change"
    if combined in {"subtitleoffsetchange", "subtitleoffsetchanged"}:
        return "subtitle_offset_change"
    if combined in {"playbackratechange", "playbackratechanged"}:
        return "playback_rate_change"
    if combined in {"shufflechange", "shufflechanged"}:
        return "shuffle_change"
    if combined in {"sleeptimerchange", "sleeptimerchanged"}:
        return "sleep_timer_change"
    if message in {"playbackstopped", "playbackstop"}:
        return "exit"
    return ""

def _extract_session_payloads(event_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = event_data.get("Data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("Sessions", "Items", "SessionsInfo"):
            sessions = data.get(key)
            if isinstance(sessions, list):
                return [item for item in sessions if isinstance(item, dict)]
        return [data]
    return []


def _extract_session_id(event_data: Dict[str, Any], data: Dict[str, Any], play_state: Optional[Dict[str, Any]] = None) -> str:
    play_state = play_state or {}
    session_id = str(
        _first_value(play_state, "SessionId", "SessionID", "sessionId", "session_id", "Id", "id")
        or _first_value(data, "SessionId", "SessionID", "sessionId", "session_id", "Id", "id")
        or _first_value(event_data, "SessionId", "SessionID", "sessionId", "session_id", "Id", "id")
        or ""
    ).strip()
    if session_id:
        return session_id
    for candidate in (data.get("Session"), event_data.get("Session")):
        if isinstance(candidate, dict):
            session_id = str(candidate.get("Id") or candidate.get("SessionId") or "").strip()
            if session_id:
                return session_id
    return ""


def _first_value(source: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source:
            return source.get(key)
    return None


def _first_present(*sources: Dict[str, Any], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            if key in source:
                return source.get(key)
    return None


def _event_source(event_data: Dict[str, Any], data: Dict[str, Any]) -> str:
    source = str(
        _first_value(data, "source", "Source")
        or _first_value(event_data, "source", "Source")
        or ""
    ).strip().lower()
    if source in PLUGIN_SOURCE_ALIASES:
        return "plugin"
    return "player"


def _event_transport(event_data: Dict[str, Any], data: Dict[str, Any]) -> str:
    transport = str(
        _first_value(data, "eventBridgeTransport", "_eventBridgeTransport", "transport", "Transport")
        or _first_value(event_data, "eventBridgeTransport", "_eventBridgeTransport", "transport", "Transport")
        or ""
    ).strip().lower()
    if transport in {"websocket", "ws"}:
        return "websocket"
    if transport in {"http", "http_fallback", "fallback_http"}:
        return "http_fallback"
    return ""
