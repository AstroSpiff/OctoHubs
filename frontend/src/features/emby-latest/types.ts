export type LatestChange = {
  kind?: string;
  quality?: string;
  video_codec?: string;
  audio_codec?: string;
  size?: number;
  added_at?: string;
  season_number?: number | string | null;
  episode_number?: number | string | null;
  episode_title?: string;
  [key: string]: unknown;
};

export type LatestItem = {
  item_id?: string;
  batch_id?: string;
  signature?: string;
  item_type?: string;
  update_type?: string;
  title?: string;
  year?: number | string;
  server_id?: string;
  server_name?: string;
  server_icon?: string;
  server_icon_style?: string;
  server_icon_color?: string;
  library_name?: string;
  library?: string;
  image_url?: string;
  overview?: string;
  genres?: string[];
  runtime_minutes?: number;
  community_rating?: number;
  official_rating?: string;
  added_at?: string;
  premiere_date?: string;
  child_count?: number;
  update_label?: string;
  jellyseerr_requested?: boolean;
  jellyseerr_request_status_label?: string;
  changes?: LatestChange[];
  [key: string]: unknown;
};

export type LatestSnapshot = {
  success: boolean;
  movies: LatestItem[];
  series: LatestItem[];
  errors: Array<{ server_id?: string; message?: string }>;
  cached: boolean;
  cached_at?: string | null;
  refreshing: boolean;
  progress: Record<string, unknown>;
  message?: string;
};

export type LatestRefreshResult = {
  success: boolean;
  refreshing: boolean;
  operation_id?: string;
  message?: string;
};

export type LatestProgress = {
  success: boolean;
  refreshing: boolean;
  progress: LatestProgressSnapshot;
};

export type LatestProgressSnapshot = {
  state?: string;
  total?: number;
  completed?: number;
  message?: string;
  [key: string]: unknown;
};

export type LatestServer = {
  id: string;
  name: string;
  icon?: string;
  icon_style?: string;
  icon_color?: string;
};

export type LatestPreset = {
  id: string;
  name: string;
  template: string;
  created_at?: string;
  updated_at?: string;
};

export type LatestPresetInput = {
  id?: string;
  name: string;
  template: string;
};

export type LatestTelegramPreset = { id: string; name: string };

export type LatestRule = {
  id: string;
  name: string;
  enabled: boolean;
  server_ids: string[];
  preset_id: string;
  telegram_config_id: string;
  server_names?: string[];
  preset_name?: string;
  telegram_name?: string;
  missing_label?: string;
  has_missing?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type LatestConfiguration = {
  success: boolean;
  servers: LatestServer[];
  presets: LatestPreset[];
  rules: LatestRule[];
  telegram_presets: LatestTelegramPreset[];
  settings: {
    limits: {
      max_movies?: number;
      max_series?: number;
      [key: string]: unknown;
    };
    active_preset_id: string;
    telegram_preset_ids: string[];
  };
  message?: string;
};

export type LatestPreview = {
  success: boolean;
  previews: Partial<
    Record<
      "movie" | "series",
      {
        message: string;
        image_url?: string;
        image_enabled?: boolean;
        error?: string | null;
      }
    >
  >;
};

export type LatestPreviewRequest = {
  template: string;
  items: Partial<Record<"movie" | "series", LatestItem>>;
};

export type LatestEnrichResult = { success: boolean; item: LatestItem };

export type LatestActionResult = {
  success: boolean;
  status?: "success" | "partial" | "error" | "busy";
  message?: string;
  sent?: number;
  failed?: number;
  errors?: string[];
};

export type LatestRuleInput = {
  id?: string;
  name: string;
  server_ids: string[];
  preset_id: string;
  telegram_config_id: string;
};
