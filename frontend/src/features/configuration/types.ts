export type EmbyServerSettings = {
  id: string;
  name: string;
  original_name: string;
  alias: string;
  url: string;
  enabled: boolean;
  notes: string;
  icon: string;
  icon_color: string;
  icon_style: "solid" | "regular" | string;
  api_key_configured: boolean;
};

export type EmbyServerInput = {
  alias: string;
  url: string;
  api_key?: string;
  clear_api_key?: boolean;
  enabled: boolean;
  notes: string;
  icon: string;
  icon_color: string;
  icon_style: "solid" | "regular";
};

export type EmbyServersPayload = {
  success: boolean;
  servers: EmbyServerSettings[];
};

export type EmbyServerMutationPayload = {
  success: boolean;
  message: string;
  server: EmbyServerSettings;
};

export type AutomationTaskId = "scan" | "refresh" | "workflow" | "sync";

export type AutomationTask = {
  enabled: boolean;
  mode: "interval" | "fixed";
  interval_minutes: number;
  times: string[];
};

export type CollectionAutomation = AutomationTask;

export type ConfigurationAutomations = {
  tasks: Record<AutomationTaskId, AutomationTask>;
  collections: CollectionAutomation;
};

export type RequestRefreshStatus = {
  running: boolean;
  last_status: "success" | "error" | "skipped" | "running" | string | null;
  last_warning: string | null;
  last_warning_at: string | null;
  last_error: string | null;
  completed_at: string | null;
};

export type ConfigurationServices = {
  database: {
    enabled: boolean;
    host: string;
    port: string;
    name: string;
    user: string;
    driver: string;
    url_configured: boolean;
    params: string;
    password_configured: boolean;
  };
  connections: {
    jellyseerr: ServiceConnection;
    prowlarr: ServiceConnection;
    jackett: ServiceConnection;
    qbittorrent: ServiceConnection & { username: string; password_configured: boolean };
    tmdb: { language: string; api_key_configured: boolean };
    mdblist: { api_keys_configured: number };
    omdb: { api_keys_configured: number };
  };
  trakt: {
    enabled: boolean;
    client_id: string;
    client_secret_configured: boolean;
    access_token_configured: boolean;
    expires_at: string;
  };
  justwatch: { enabled: boolean; locale: string };
};

export type ServiceConnection = { url: string; api_key_configured: boolean };

export type ServiceSettingsInput = {
  database: {
    host: string;
    port: string;
    name: string;
    user: string;
    driver: string;
    params: string;
    password?: string;
    url?: string;
    clear_password?: boolean;
    clear_url?: boolean;
  };
  connections: {
    jellyseerr: { url: string; api_key?: string; clear_api_key?: boolean };
    prowlarr: { url: string; api_key?: string; clear_api_key?: boolean };
    jackett: { url: string; api_key?: string; clear_api_key?: boolean };
    qbittorrent: { url: string; username: string; password?: string; clear_password?: boolean };
    tmdb: { language: string; api_key?: string; clear_api_key?: boolean };
    mdblist: { api_keys?: string[]; clear_api_keys?: boolean };
    omdb: { api_keys?: string[]; clear_api_keys?: boolean };
  };
  trakt: { enabled: boolean; client_id: string; client_secret?: string; clear_client_secret?: boolean; access_token?: string };
  justwatch: { enabled: boolean; locale: string };
};

export type ConnectionCheckPayload = {
  success: boolean;
  statuses: Record<string, { ok: boolean; message: string; configured?: boolean }>;
};

export type TraktDeviceStart = {
  success: boolean;
  device_code: string;
  user_code: string;
  verification_url: string;
  expires_in: number;
  interval: number;
};

export type TraktDevicePoll = {
  status: "pending" | "authorized";
  expires_at?: string;
};

export type ConfigurationSettingsPayload = {
  success: boolean;
  has_config: boolean;
  automations: ConfigurationAutomations;
  request_refresh: RequestRefreshStatus;
  services: ConfigurationServices;
  message?: string;
};

export type TelegramBot = {
  id: string;
  alias: string;
  original_name: string;
  username: string;
  verified: boolean;
  verified_at: string;
  last_check: string;
  last_error: string;
  token_configured: boolean;
};

export type TelegramChat = {
  id: string;
  alias: string;
  original_name: string;
  chat_id: string;
  verified: boolean;
  verified_at: string;
  last_check: string;
  last_error: string;
};

export type TelegramPreset = {
  id: string;
  name: string;
  bot_ids: string[];
  group_ids: string[];
  channel_ids: string[];
  alerts: Record<string, Record<string, Array<{ status?: string; message?: string }>>>;
  last_check: string;
  last_error: string;
};

export type TelegramSettingsPayload = {
  success: boolean;
  ready: boolean;
  bots: TelegramBot[];
  groups: TelegramChat[];
  channels: TelegramChat[];
  presets: TelegramPreset[];
  alerts: Record<string, Record<string, unknown>>;
  message?: string;
};

export type TelegramAction =
  | { action: "bot.save"; data: { id?: string; alias: string; token?: string } }
  | { action: "bot.verify" | "bot.remove"; data: { id: string } }
  | { action: "chat.save"; data: { id?: string; kind: "group" | "channel"; alias: string; chat_id: string } }
  | { action: "chat.verify"; data: { id: string; kind: "group" | "channel"; bot_id?: string } }
  | { action: "chat.remove"; data: { id: string; kind: "group" | "channel" } }
  | { action: "preset.save"; data: { id?: string; name: string; bot_id: string; group_ids: string[]; channel_ids: string[] } }
  | { action: "preset.remove"; data: { id: string } };
