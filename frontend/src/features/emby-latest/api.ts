import { request } from "@/lib/http";
import type {
  LatestActionResult,
  LatestConfiguration,
  LatestEnrichResult,
  LatestItem,
  LatestPreview,
  LatestProgress,
  LatestRefreshResult,
  LatestRuleInput,
  LatestSnapshot,
} from "@/features/emby-latest/types";
import type { LatestFetchLimits } from "@/features/emby-latest/latest-fetch-limits";

export function getLatestSnapshot({
  limit,
  perServerLimit,
  cacheOnly = true,
}: LatestFetchLimits & {
  cacheOnly?: boolean;
}): Promise<LatestSnapshot> {
  const params = new URLSearchParams({
    limit: String(limit),
    per_server_limit: String(perServerLimit),
    view: "history",
  });
  if (cacheOnly) params.set("cache_only", "1");
  return request<LatestSnapshot>(`/api/v1/emby/latest?${params.toString()}`);
}

export function refreshLatest({
  limit,
  perServerLimit,
  full = false,
}: LatestFetchLimits & { full?: boolean }): Promise<LatestRefreshResult> {
  const params = new URLSearchParams({
    limit: String(limit),
    per_server_limit: String(perServerLimit),
    full: full ? "1" : "0",
  });
  return request<LatestRefreshResult>(
    `/api/v1/emby/latest/refresh?${params.toString()}`,
    { method: "POST" },
  );
}

export function getLatestProgress(): Promise<LatestProgress> {
  return request<LatestProgress>("/api/v1/emby/latest/progress");
}

export function notifyLatest(
  perServerLimit: number,
): Promise<LatestActionResult> {
  return request<LatestActionResult>("/api/v1/emby/latest/notify", {
    method: "POST",
    body: JSON.stringify({
      server_id: "all",
      per_server_limit: perServerLimit,
    }),
  });
}

export function startLatestWorkflow(): Promise<LatestActionResult> {
  return request<LatestActionResult>("/api/v1/workflow/start", {
    method: "POST",
    body: JSON.stringify({ type: "full" }),
  });
}

export function getLatestConfiguration(): Promise<LatestConfiguration> {
  return request<LatestConfiguration>("/api/v1/emby/latest/config");
}

export function saveLatestPreset(input: {
  id?: string;
  name: string;
  template: string;
}): Promise<LatestConfiguration> {
  return request<LatestConfiguration>("/api/v1/emby/latest/presets", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteLatestPreset(
  presetId: string,
): Promise<LatestConfiguration> {
  return request<LatestConfiguration>(
    `/api/v1/emby/latest/presets/${encodeURIComponent(presetId)}`,
    { method: "DELETE" },
  );
}

export function saveLatestRule(
  input: LatestRuleInput,
): Promise<LatestConfiguration> {
  return request<LatestConfiguration>("/api/v1/emby/latest/rules", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function setLatestRuleEnabled(
  ruleId: string,
  enabled: boolean,
): Promise<LatestConfiguration> {
  return request<LatestConfiguration>(
    `/api/v1/emby/latest/rules/${encodeURIComponent(ruleId)}/enabled`,
    { method: "POST", body: JSON.stringify({ enabled }) },
  );
}

export function deleteLatestRule(ruleId: string): Promise<LatestConfiguration> {
  return request<LatestConfiguration>(
    `/api/v1/emby/latest/rules/${encodeURIComponent(ruleId)}`,
    { method: "DELETE" },
  );
}

export function previewLatest(
  template: string,
  items: Partial<Record<"movie" | "series", LatestItem>>,
): Promise<LatestPreview> {
  return request<LatestPreview>("/api/v1/emby/latest/preview", {
    method: "POST",
    body: JSON.stringify({ template, items }),
  });
}

export function enrichLatest(item: LatestItem): Promise<LatestEnrichResult> {
  return request<LatestEnrichResult>("/api/v1/emby/latest/enrich", {
    method: "POST",
    body: JSON.stringify({ item, force_omdb: true }),
  });
}

export function clearLatestState(): Promise<LatestActionResult> {
  return request<LatestActionResult>("/api/v1/emby/latest/state/clear", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function resetLatest(): Promise<LatestActionResult> {
  return request<LatestActionResult>("/api/v1/emby/latest/reset", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function resetLatestScanTracking(): Promise<LatestActionResult> {
  return request<LatestActionResult>("/api/v1/emby/scan-jobs/reset", {
    method: "POST",
    body: JSON.stringify({}),
  });
}
