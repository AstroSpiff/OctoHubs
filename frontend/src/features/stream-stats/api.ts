import { request } from "@/lib/http";
import type { StreamStats, StreamStatsFilters, StreamStatsStreamDetail } from "@/features/stream-stats/types";

export function getStreamStats(filters: StreamStatsFilters): Promise<StreamStats> {
  const parameters = new URLSearchParams({
    period: filters.period,
    server_id: filters.server_id,
    user: filters.user,
    client: filters.client,
    issues_only: String(filters.issues_only),
    sort: filters.sort,
    limit: String(filters.limit),
  });
  return request<StreamStats>(`/api/v1/emby/transcode-guard/stats?${parameters.toString()}`);
}

export function getStreamStatsStreamDetail(streamId: string): Promise<StreamStatsStreamDetail> {
  return request<StreamStatsStreamDetail>(`/api/v1/emby/transcode-guard/streams/${encodeURIComponent(streamId)}`);
}
