export type EmbyLiveServerMeta = {
  id: string;
  name: string;
  enabled: boolean;
  icon?: string;
  icon_style?: string;
  icon_color?: string;
  url?: string;
  last_action?: { name: string; timestamp: string; result: string };
};

export type EmbyLiveStatus = {
  ok: boolean;
  version?: string | null;
  name?: string | null;
  last_check?: string | null;
  error?: string | null;
};

export type EmbyLiveTask = {
  id?: string;
  name?: string;
  state?: string;
  progress?: number;
};

export type EmbyLiveTranscodeGuard = {
  enabled?: boolean;
  category?: string;
  label?: string;
  reason?: string;
  severity?: string;
  should_enforce?: boolean;
  state?: string;
  mode?: string;
  rule_id?: string;
  rule_name?: string;
};

export type EmbyLiveStream = {
  session_id: string;
  title: string;
  media_type?: string;
  series_name?: string;
  season_number?: number;
  episode_number?: number;
  episode_title?: string;
  year?: string | number;
  user: string;
  device: string;
  client: string;
  app_version?: string;
  ip?: string;
  protocol?: string;
  state: string;
  paused: boolean;
  play_method?: string;
  video_mode: string;
  audio_mode: string;
  video_label: string;
  audio_label: string;
  container?: string;
  stream_container?: string;
  transcode_container?: string;
  bitrate?: number;
  transcode_bitrate?: number;
  transcode_percent?: number | null;
  position: string;
  duration: string;
  playback_percent: number | null;
  transcode_reasons: string[];
  transcode_guard?: EmbyLiveTranscodeGuard;
};

export type EmbyLiveServer = {
  server: EmbyLiveServerMeta;
  status: EmbyLiveStatus;
  running_tasks: EmbyLiveTask[];
  tasks_error: string | null;
  streams: EmbyLiveStream[];
  streams_error: string | null;
  probe_status?: Record<string, unknown>;
};

export type EmbyLiveSnapshot = {
  success: boolean;
  servers: Record<string, EmbyLiveServer>;
};

export type LiveConnectionState = "loading" | "connected" | "fallback" | "reconnecting";
