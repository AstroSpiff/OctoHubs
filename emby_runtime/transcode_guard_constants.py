"""Constants shared by the Transcode Guard runtime modules."""

from __future__ import annotations

TRANSCODE_GUARD_SETTINGS_KEY = "octohubs_transcode_guard:settings:v1"
TRANSCODE_GUARD_STATE_KEY = "octohubs_transcode_guard:state:v1"
TRANSCODE_GUARD_EVENTS_KEY = "octohubs_transcode_guard:events:v1"
TRANSCODE_GUARD_STREAM_LOG_KEY = "octohubs_transcode_guard:stream_log:v1"
TRANSCODE_GUARD_PLAYBACK_EVENTS_KEY = "octohubs_transcode_guard:playback_events:v1"
TRANSCODE_GUARD_EXIT_SETTLE_SECONDS = 4
TRANSCODE_GUARD_STREAM_LOG_LIMIT = 1000
TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_LIMIT = 1000
TRANSCODE_GUARD_PLAYBACK_EVENT_LOG_MAX_BYTES = 1024 * 1024
TRANSCODE_GUARD_STREAM_STATUS_LIMIT = 160
PLUGIN_PLAYBACK_SOURCE_ALIASES = {
    "plugin",
    "emby_plugin",
    "octohubs_plugin",
    "octohubs_event_bridge",
    "octohubs.eventbridge",
    "event_bridge",
}
PROXY_PLAYBACK_SOURCE_ALIASES = {
    "proxy",
    "reverse_proxy",
    "octohubs_proxy",
}

TRANSCODE_GUARD_ACTION_LABELS = {
    "play": "riproduzione",
    "time_update": "aggiornamento posizione",
    "warn": "avviso",
    "warning_error": "errore avviso",
    "stop": "stop",
    "pause": "pausa",
    "unpause": "ripresa",
    "volume_change": "cambio volume",
    "repeat_mode_change": "cambio ripetizione",
    "resolved": "risolto",
    "partial_resolved": "Risolto Parz.",
    "resolution_change": "Cambio Ris.",
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
    "exit": "uscito",
    "resolved_later": "risolto in seguito",
    "relapse": "ricaduta",
}
