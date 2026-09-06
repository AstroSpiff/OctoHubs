export type ResearchMediaType = "movie" | "tv" | "unknown";

export type ResearchNotice = {
  message: string;
  tone: "success" | "error" | "warning";
};

export type ResearchRefreshStatus = {
  running: boolean;
  last_status?: string | null;
  last_error?: string | null;
  last_warning?: string | null;
  last_warning_at?: string | null;
  completed_at?: string | null;
  counts?: Record<string, number> | null;
};

export type ResearchSearchRules = {
  use_prowlarr?: boolean;
  use_jackett?: boolean;
  use_original_title?: boolean;
  use_alt_titles_original?: boolean;
  use_alt_titles_language?: boolean;
  alt_titles_language?: string;
  query_languages?: string[];
  query_terms?: string[];
  include_target_lang_base?: boolean;
  season_templates?: string[];
  filter_terms?: string[];
  min_seeders?: number;
  require_audio_language?: boolean;
  search_episode_variants?: boolean;
  skip_season_queries_when_episode_search?: boolean;
  sanitize_titles?: boolean;
  ignore_year_for_tv?: boolean;
  skip_available_content?: boolean;
  skip_unreleased_content?: boolean;
  movie_sort_primary?: string;
  movie_sort_secondary?: string;
  tv_sort_primary?: string;
  tv_sort_secondary?: string;
};

export type ResearchRequest = {
  id?: string | number;
  request_id?: string | number;
  title?: string;
  year?: string | number;
  media_type?: string;
  poster_url?: string;
  is_available?: boolean;
  is_unreleased?: boolean;
  will_skip?: boolean;
  justwatch_available?: boolean;
  justwatch_providers?: string[];
  season_status?: Array<Record<string, unknown>>;
  rules?: RequestRuleSource;
  [key: string]: unknown;
};

export type RequestSearchRule = {
  request_id: string | number;
  enabled: boolean;
  query_terms: string;
  filter_terms: string;
  exclude_terms: string;
  use_original_title: boolean;
  use_alt_titles_original: boolean;
  use_alt_titles_language: boolean;
  alt_titles_language: string;
  year_variance: number;
};

export type RequestRuleSource = Omit<
  Partial<RequestSearchRule>,
  "query_terms" | "filter_terms" | "exclude_terms"
> & {
  query_terms?: string | string[];
  filter_terms?: string | string[];
  exclude_terms?: string | string[];
};

export type ScanTarget = {
  request_id: string | number;
  seasons: number[] | null;
  force: boolean;
};

export type ScanSummaryItem = {
  request_id: string | number;
  title?: string;
  year?: string | number;
  media_type?: string;
  season?: number | null;
  results_found?: number;
  results?: SearchResult[];
  top_results?: SearchResult[];
  queries?: Array<{ query?: string; results_found?: number }>;
  excluded?: Array<{ title?: string; reason?: string; indexer?: string }>;
  updated_at?: string;
  is_stale?: boolean;
};

export type ResearchOverview = {
  success: boolean;
  has_config: boolean;
  qbittorrent_available: boolean;
  scan: Record<string, unknown>;
  results: {
    generated_at?: string;
    items?: SearchResult[];
    [key: string]: unknown;
  };
  requests: ResearchRequest[];
  movie_requests: ResearchRequest[];
  tv_requests: ResearchRequest[];
  all_requests?: ResearchRequest[];
  all_movie_requests?: ResearchRequest[];
  all_tv_requests?: ResearchRequest[];
  requests_updated_at?: string | null;
  search_rules: ResearchSearchRules;
  search_defaults: { target_languages: string[]; exclude_tags: string[] };
  movie_sort_options: SortOption[];
  tv_sort_options: SortOption[];
  variant_estimate?: { base?: number; episodes?: number };
  auto_tasks: Record<string, unknown>;
  requests_refresh_warning?: string | null;
  requests_refresh_warning_at?: string | null;
  probe_counts: { blacklist: number; incomplete: number };
};

export type SortOption = { value: string; label: string; group: string };

export type TmdbSearchResult = {
  tmdb_id: number;
  title: string;
  original_title?: string;
  year?: string | number;
  media_type: Exclude<ResearchMediaType, "unknown">;
  poster_path?: string;
  overview?: string;
};

export type TmdbSeason = {
  season_number: number;
  name?: string;
  episode_count?: number;
};

export type TmdbTvDetails = { seasons?: TmdbSeason[] };

export type AvailabilityEntry = {
  label?: string;
  server_id?: string;
  server_name?: string;
  item_id?: string;
  item_name?: string;
  status_label?: string;
  icon?: string;
  server_icon?: string;
  icon_color?: string;
  server_icon_color?: string;
};

export type EmbyMovieVersion = {
  item_id?: string;
  name?: string;
  resolutions?: string[];
};

export type EmbySeason = {
  season_id?: string;
  season_number?: number;
  name?: string;
  episode_count?: number;
};

export type EmbyEpisode = {
  episode_id?: string;
  episode_number?: number;
  name?: string;
  resolutions?: Array<{ label?: string; item_id?: string }>;
};

export type EmbyItemDetails = {
  title?: string;
  year?: string | number;
  server?: string;
  resolution?: string;
  video_codec?: string;
  audio_codec?: string;
  bitrate_mbps?: number;
  path?: string;
  audio_tracks?: string[];
};

export type SearchResult = {
  title?: string;
  year?: string | number;
  indexer?: string;
  seeders?: number;
  leechers?: number;
  size_gb?: number;
  resolution?: string;
  resolution_bucket?: string;
  season_number?: number;
  season_label?: string;
  episode_code?: string;
  in_library?: boolean;
  magnet?: string;
  magnetUri?: string;
  magnetUrl?: string;
  torrent?: string;
  magnet_ref?: string;
  torrent_ref?: string;
  source_id?: string;
  has_magnet?: boolean;
  has_torrent?: boolean;
  web?: string;
  link?: string;
  guid?: string;
  duplicates?: SearchResult[];
  [key: string]: unknown;
};

export type CustomSearchRules = {
  search_rules: ResearchSearchRules;
  target_languages: string[];
  exclude_tags: string[];
};

export type StreamingSearchInput = {
  query: string;
  mediaType: ResearchMediaType;
  indexers: Array<"prowlarr" | "jackett">;
  tmdbId?: number;
  seasons: number[];
  customRules?: CustomSearchRules;
};

export type StreamingSearchProgress = {
  completedQueries: number;
  totalQueries?: number;
  latestQuery?: string;
  latestIndexer?: string;
};

export type ManualSearchContext = {
  query?: string;
  media_type?: ResearchMediaType | "mixed";
  indexers?: Array<"prowlarr" | "jackett">;
  tmdb_id?: string | number;
  seasons?: number[];
  custom_rules?: CustomSearchRules;
};

export type ManualSearchHistoryEntry = {
  id: number;
  generated_at?: string;
  search_context?: ManualSearchContext;
  items?: Array<{
    title?: string;
    media_type?: string;
    results_found?: number;
    results?: SearchResult[];
    queries?: Array<{ query?: string; indexer?: string }>;
    [key: string]: unknown;
  }>;
};
