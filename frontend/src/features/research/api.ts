import { request, requestBlob } from "@/lib/http";
import type {
  AvailabilityEntry,
  EmbyEpisode,
  EmbyItemDetails,
  EmbyMovieVersion,
  EmbySeason,
  ManualSearchHistoryEntry,
  ResearchOverview,
  ResearchRefreshStatus,
  RequestSearchRule,
  ScanTarget,
  SearchResult,
  TmdbSearchResult,
  TmdbTvDetails,
} from "@/features/research/types";

type ActionResult = {
  success: boolean;
  message: string;
  sent?: number;
  failed?: number;
  total?: number;
};

function getResearchOverview(): Promise<ResearchOverview> {
  return request<ResearchOverview>("/api/v1/research/overview");
}

function searchTmdb(query: string, page = 1): Promise<{ success: boolean; results: TmdbSearchResult[]; page: number; total_pages: number }> {
  const parameters = new URLSearchParams({ query, page: String(page) });
  return request(`/api/v1/research/tmdb/search?${parameters}`);
}

function getTmdbTvDetails(tmdbId: number): Promise<{ success: boolean; details: TmdbTvDetails }> {
  return request(`/api/v1/research/tmdb/tv/${encodeURIComponent(String(tmdbId))}`);
}

function checkTmdbAvailability(tmdbId: number, mediaType: string): Promise<{ success: boolean; available_on: AvailabilityEntry[] }> {
  return request("/api/v1/research/tmdb/check-availability", {
    method: "POST",
    body: JSON.stringify({ tmdb_id: tmdbId, media_type: mediaType }),
  });
}

function checkEmbyAvailability(tmdbId: number, mediaType: string): Promise<{ success: boolean; available_on: AvailabilityEntry[] }> {
  return request("/api/v1/emby/availability", {
    method: "POST",
    body: JSON.stringify({ tmdb_id: tmdbId, media_type: mediaType }),
  });
}

function getEmbyMovieVersions(serverId: string, tmdbId: number): Promise<{ success: boolean; versions: EmbyMovieVersion[] }> {
  const parameters = new URLSearchParams({ server_id: serverId, tmdb_id: String(tmdbId) });
  return request(`/api/v1/emby/movie-versions?${parameters}`);
}

function getEmbySeriesSeasons(serverId: string, seriesId: string): Promise<{ success: boolean; seasons: EmbySeason[] }> {
  const parameters = new URLSearchParams({ server_id: serverId, series_id: seriesId });
  return request(`/api/v1/emby/series-seasons?${parameters}`);
}

function getEmbySeasonEpisodes(serverId: string, seasonId: string): Promise<{ success: boolean; episodes: EmbyEpisode[] }> {
  const parameters = new URLSearchParams({ server_id: serverId, season_id: seasonId });
  return request(`/api/v1/emby/season-episodes?${parameters}`);
}

function getEmbyItemDetails(serverId: string, itemId: string): Promise<{ success: boolean; details: EmbyItemDetails }> {
  const parameters = new URLSearchParams({ server_id: serverId, item_id: itemId });
  return request(`/api/v1/emby/item-details?${parameters}`);
}

function lookupEmbyTitle(title: string, year?: string | number): Promise<{ success: boolean; found: boolean; message?: string; details?: EmbyItemDetails }> {
  const parameters = new URLSearchParams({ title });
  if (year !== undefined && year !== null && String(year).trim()) parameters.set("year", String(year));
  return request(`/api/v1/emby/lookup?${parameters}`);
}

function createStreamingSearch(signal?: AbortSignal): Promise<{ success: boolean; session_id: string; websocket_url: string }> {
  return request("/api/v1/research/stream", { method: "POST", signal });
}

function saveGlobalSearchRules(input: { search_rules: Record<string, unknown>; target_languages: string[]; exclude_tags: string[] }): Promise<{ success: boolean; message: string }> {
  return request("/api/v1/research/search-rules", { method: "PUT", body: JSON.stringify(input) });
}

function saveRequestSearchRules(rules: RequestSearchRule[]): Promise<ActionResult> {
  return request("/api/v1/research/request-rules", { method: "POST", body: JSON.stringify({ rules }) });
}

function refreshJellyseerrRequests(): Promise<ActionResult & { background?: boolean; operation_id?: string }> {
  return request("/api/v1/research/requests/refresh?background=1", { method: "POST" });
}

function getJellyseerrRefreshStatus(): Promise<ResearchRefreshStatus> {
  return request("/api/v1/research/requests/refresh-status");
}

function runScan(targets?: ScanTarget[]): Promise<ActionResult> {
  return request("/api/v1/research/scan/start", { method: "POST", body: JSON.stringify(targets?.length ? { targets } : {}) });
}

function stopScan(): Promise<ActionResult> {
  return request("/api/v1/research/scan/stop", { method: "POST" });
}

function cleanupScanResults(input: { mode: "single" | "resolved" | "all"; request_id?: string | number; season?: number | null }): Promise<ActionResult & { removed: number; remaining: number }> {
  return request("/api/v1/research/results/cleanup", { method: "POST", body: JSON.stringify(input) });
}

function sendToQbittorrent(link: string): Promise<ActionResult> {
  return request("/api/v1/research/torrents/send", { method: "POST", body: JSON.stringify({ link }) });
}

function sendBatchToQbittorrent(links: string[]): Promise<ActionResult> {
  return request("/api/v1/research/torrents/send-batch", { method: "POST", body: JSON.stringify({ links }) });
}

function downloadTorrentArchive(links: string[]): Promise<Blob> {
  return requestBlob("/api/v1/research/torrents/archive", { method: "POST", body: JSON.stringify({ links }) });
}

function resolveMagnetReferences(references: string[]): Promise<{ success: boolean; magnets: string[] }> {
  return request("/api/v1/research/torrents/magnets", {
    method: "POST",
    body: JSON.stringify({ references }),
  });
}

function requestFromJellyseerr(mediaId: number, mediaType: string, seasons: number[]): Promise<ActionResult> {
  return request("/api/v1/research/requests/create", {
    method: "POST",
    body: JSON.stringify({ mediaId, mediaType, ...(seasons.length ? { seasons } : {}) }),
  });
}

function getManualSearchHistory(): Promise<{ success: boolean; searches: ManualSearchHistoryEntry[]; warning?: string }> {
  return request("/api/v1/research/manual/history");
}

function deleteManualSearch(searchId: number): Promise<ActionResult> {
  return request(`/api/v1/research/manual/history/${encodeURIComponent(String(searchId))}`, { method: "DELETE" });
}

function resultLink(result: SearchResult): string | null {
  const candidate = result.magnet_ref || result.torrent_ref;
  return typeof candidate === "string" && candidate.trim() ? candidate : null;
}

export {
  checkEmbyAvailability,
  checkTmdbAvailability,
  createStreamingSearch,
  deleteManualSearch,
  downloadTorrentArchive,
  getEmbyItemDetails,
  getEmbyMovieVersions,
  getEmbySeasonEpisodes,
  getEmbySeriesSeasons,
  lookupEmbyTitle,
  getManualSearchHistory,
  getResearchOverview,
  getTmdbTvDetails,
  requestFromJellyseerr,
  resolveMagnetReferences,
  resultLink,
  refreshJellyseerrRequests,
  runScan,
  saveGlobalSearchRules,
  saveRequestSearchRules,
  searchTmdb,
  sendBatchToQbittorrent,
  sendToQbittorrent,
  stopScan,
  cleanupScanResults,
  getJellyseerrRefreshStatus,
};
