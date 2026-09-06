export type ProbeScope = "libraries" | "recent";

export type ProbeServer = {
  id: string;
  name: string;
  icon?: string;
  icon_style?: string;
  icon_color?: string;
};

export type ProbeLibrary = {
  id: string;
  name: string;
  collection_type?: string;
};

export type ProbeLibrariesPayload = {
  success: boolean;
  servers: Record<
    string,
    { ok: boolean; libraries: ProbeLibrary[]; error?: string }
  >;
};

export type ProbeActionResponse = {
  success: boolean;
  message: string;
};

export type ProbeConfig = {
  window_size: number;
  window_threshold: number;
  max_days: number;
  max_items: number;
  safety_margin_days: number;
  probe_parallelism: number;
  media_policy: "strm_only" | "missing_media_info";
};

export type ProbeQueueItem = {
  id?: number;
  server_id?: string;
  library_id?: string;
  item_id: string;
  media_source_id?: string;
  display_name?: string;
  name?: string;
  library_name?: string;
  series_name?: string;
  season_number?: number;
  episode_number?: number;
  year?: number;
  media_type?: string;
  path?: string;
  status?: string;
  retry_count?: number;
  created_at?: string;
  updated_at?: string;
  completed_at?: string;
  failed_at?: string;
  error_type?: string;
  reason?: string;
};

export type ProbeHistoryItem = {
  id?: number;
  server_id?: string;
  library_id?: string;
  item_id: string;
  media_source_id?: string;
  display_name?: string;
  item_name?: string;
  library_name?: string;
  path?: string;
  series_name?: string;
  season_number?: number;
  episode_number?: number;
  year?: number;
  status?: string;
  error_type?: string;
  reason?: string;
  error_details?: string;
  retry_count?: number;
  duration_ms?: number;
  processed_at?: string;
  completed_at?: string;
  created_at?: string;
  updated_at?: string;
  failed_at?: string;
};

export type ProbeBlacklistItem = ProbeHistoryItem & {
  failed_at?: string;
};

export type ProbeWorkerStatus = {
  running?: boolean;
  phase?: "discovery" | "processing" | string;
  found?: number;
  total_scanned?: number;
  processed?: number;
  incomplete?: number;
  errors?: number;
  total?: number;
  current_item?: string;
  last_log?: string;
  queue?: ProbeComboTask[];
  last_run?: ProbeComboLastRun;
  board_reset?: boolean;
};

export type ProbeComboTask = {
  id?: string;
  type?: "discovery" | "processing" | string;
  server_id?: string;
  server_name?: string;
  library_id?: string;
  library_name?: string;
  result?: "success" | "warning" | "error" | "skipped" | string;
  note?: string;
};

export type ProbeComboLastRun = {
  finished_at?: string;
  status?: "completed" | "interrupted" | string;
  tasks?: ProbeComboTask[];
};

export type ProbeServerStatus = {
  discovery?: ProbeWorkerStatus;
  processing?: ProbeWorkerStatus;
  recent_discovery?: ProbeWorkerStatus;
  recent_processing?: ProbeWorkerStatus;
  combo_libraries?: ProbeWorkerStatus;
  combo_recent?: ProbeWorkerStatus;
};
