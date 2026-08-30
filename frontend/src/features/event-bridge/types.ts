export type EventBridgeSettings = {
  ENABLED: boolean;
  WEBSOCKET_ENABLED: boolean;
  HTTP_FALLBACK_ENABLED: boolean;
  WEBSOCKET_RECONNECT_SECONDS: number;
  CAPTURE_PLAYBACK_EVENTS: boolean;
  CAPTURE_SESSION_EVENTS: boolean;
  CAPTURE_PLUGIN_EVENTS: boolean;
  EVENT_BATCH_INTERVAL_SECONDS: number;
  HTTP_TIMEOUT_SECONDS: number;
  RETRY_COUNT: number;
  INCLUDE_RAW_PAYLOAD: boolean;
  PLAYBACK_EVENT_NAMES: string[];
  SESSION_EVENT_NAMES: string[];
  PLUGIN_EVENT_NAMES: string[];
};

export type EventBridgeServer = {
  id: string;
  name: string;
  icon?: string;
  icon_color?: string;
  icon_style?: string;
  settings_editable: boolean;
  credential: { configured: boolean; label: string; class_name: string };
  settings: EventBridgeSettings;
  transport: { label: string; class_name: string };
  config_ack: { label: string; class_name: string; title: string };
  diagnostics: {
    sync_status: string;
    sync_label: string;
    sync_class: string;
    plugin_version: string;
    plugin_version_label: string;
    last_seen_at: string;
    last_event: string;
    last_event_at: string;
    last_config_sent_at: string;
    last_config_ack_at: string;
    last_config_transport_label: string;
    last_config_ack_error: string;
    last_plugin_settings_at: string;
    target_count_label: string;
    plugin_targets: Array<{ name: string; url: string }>;
    diffs: Array<{ label: string; octohubs: string; plugin: string }>;
  };
};

export type EventBridgeStatus = { ok: boolean; connected: number; webhook_secret_configured: boolean; credential_configured: number; servers: EventBridgeServer[] };

export type EventBridgeSaveResult = {
  ok: boolean;
  message: string;
  settings_saved: boolean;
  push: { http_pushed: number; websocket_pushed: number; http_failed: string[]; error: string };
};

export type EventBridgeCredentialResult = { ok: boolean; server_id: string; configured: boolean; message: string };
