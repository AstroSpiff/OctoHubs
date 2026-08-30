export type StatsPeriod = "24h" | "7d" | "30d" | "all";
export type StatsSort = "issues_desc" | "streams_desc" | "recent_desc" | "user_asc";

export type StreamStatsFilters = {
  period: StatsPeriod;
  server_id: string;
  user: string;
  client: string;
  issues_only: boolean;
  sort: StatsSort;
  limit: number;
};

export type StatsFacet = { id: string; name: string; count: number };

export type StreamStatsTrendItem = {
  id?: string;
  status: string;
  label: string;
  at: string;
  title: string;
  server: string;
  client: string;
  device: string;
  quality: string;
};

export type StatsSummary = {
  users: number;
  streams: number;
  correct: number;
  issue_streams: number;
  technical_issues: number;
  warnings: number;
  stops: number;
  resolved: number;
  exits: number;
  resolution_changes: number;
  relapses: number;
  active: number;
  problem_rate: number;
};

export type StreamStatsUser = {
  user: string;
  streams: number;
  correct: number;
  issue_streams: number;
  technical_issues: number;
  warnings: number;
  stops: number;
  resolved: number;
  exits: number;
  resolution_changes: number;
  relapses: number;
  active: number;
  problem_rate: number;
  risk_score: number;
  last_seen_at: string;
  clients: StatsFacet[];
  servers: StatsFacet[];
  trend: StreamStatsTrendItem[];
};

export type StreamStatsHistory = {
  id: string;
  at: string;
  started_at?: string;
  ended_at?: string;
  user: string;
  title: string;
  server_name: string;
  client: string;
  device: string;
  quality: string;
  outcome: string;
  tags: string[];
  violations_committed: string[];
  actions: string[];
  action_records?: Array<{ action: string; source?: string; at?: string }>;
  duration_seconds?: number | null;
  playback_percent?: number | null;
  rule_name?: string;
  reason?: string;
};

export type StreamStats = {
  ok: boolean;
  filters: StreamStatsFilters;
  summary: StatsSummary;
  users: StreamStatsUser[];
  history: StreamStatsHistory[];
  facets: { servers: StatsFacet[]; users: StatsFacet[]; clients: StatsFacet[] };
};

export type StreamStatsStreamDetail = {
  ok: boolean;
  stream: StreamStatsHistory;
};
