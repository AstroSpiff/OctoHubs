export type GuardMode = "monitor" | "warn" | "stop" | "warn_then_stop";
export type StreamState = "any" | "transcode" | "direct";
export type PresenceState = "any" | "present" | "absent";

export type GuardRule = {
  id: string;
  name: string;
  type: "rule";
  enabled: boolean;
  profile: string;
  mode: GuardMode;
  video_state: StreamState;
  audio_state: StreamState;
  remux_state: PresenceState;
  transformation_state: PresenceState;
  min_source_height: number;
  correction_window_seconds: number;
  message_display_mode: "toast" | "confirmation";
  warning_timeout_ms: number;
  max_warnings: number;
  message_cooldown_seconds: number;
  allow_audio_only_transcode: boolean;
  allow_container_remux: boolean;
  ignore_paused: boolean;
  server_ids: string[];
  excluded_users: string[];
  excluded_clients: string[];
  excluded_devices: string[];
  excluded_ips: string[];
  message_header: string;
  message_text: string;
  stop_processing: boolean;
  children: [];
};

export type TranscodeGuardSettings = Record<string, unknown> & {
  enabled: boolean;
  poll_interval_seconds: number;
  stream_history_retention_days: number;
  rules: GuardRule[];
};

export type GuardServerOption = { id: string; name: string; enabled: boolean };

export type GuardSettingsResponse = {
  ok: boolean;
  settings: TranscodeGuardSettings;
  servers: GuardServerOption[];
};

export type GuardSettingsSaveResult = { ok: boolean; settings: TranscodeGuardSettings };
