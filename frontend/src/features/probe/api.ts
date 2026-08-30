import { request } from "@/lib/http";
import type { ProbeActionResponse, ProbeBlacklistItem, ProbeConfig, ProbeHistoryItem, ProbeLibrariesPayload, ProbeQueueItem, ProbeScope } from "@/features/probe/types";

function query(path: string, values: Record<string, string | number | undefined>) {
  const parameters = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== "") parameters.set(key, String(value)); });
  return `${path}?${parameters.toString()}`;
}

export function getProbeLibraries(): Promise<ProbeLibrariesPayload> {
  return request<ProbeLibrariesPayload>("/api/v1/emby/probe/libraries");
}

export function getProbeConfig(serverId: string): Promise<{ success: boolean; config: ProbeConfig }> {
  return request<{ success: boolean; config: ProbeConfig }>(query("/api/v1/emby/probe/config", { server_id: serverId }));
}

export function saveProbeConfig(serverId: string, config: ProbeConfig): Promise<{ success: boolean; config: ProbeConfig }> {
  return request<{ success: boolean; config: ProbeConfig }>("/api/v1/emby/probe/config", { method: "POST", body: JSON.stringify({ server_id: serverId, config }) });
}

export function runProbeAction(path: string, body: Record<string, unknown> = {}): Promise<ProbeActionResponse> {
  return request<ProbeActionResponse>(path, { method: "POST", body: JSON.stringify(body) });
}

export function getProbeQueue(serverId: string, scope: ProbeScope): Promise<{ success: boolean; queue: ProbeQueueItem[] }> {
  return request<{ success: boolean; queue: ProbeQueueItem[] }>(query("/api/v1/emby/probe/queue", { server_id: serverId, scope }));
}

export function getProbeHistory(serverId: string, scope: ProbeScope): Promise<{ success: boolean; history: ProbeHistoryItem[] }> {
  return request<{ success: boolean; history: ProbeHistoryItem[] }>(query("/api/v1/emby/probe/history", { server_id: serverId, scope, limit: 100 }));
}

export function getProbeBlacklist(serverId: string, scope: ProbeScope, errorType: "error" | "incomplete"): Promise<{ success: boolean; blacklist: ProbeBlacklistItem[] }> {
  return request<{ success: boolean; blacklist: ProbeBlacklistItem[] }>(query("/api/v1/emby/probe/blacklist", { server_id: serverId, scope, min_retry: 3, type: errorType }));
}

export function deleteProbeQueue(input: { serverId: string; scope: ProbeScope; itemId?: string; mediaSourceId?: string }): Promise<ProbeActionResponse> {
  return request<ProbeActionResponse>("/api/v1/emby/probe/queue", { method: "DELETE", body: JSON.stringify({ server_id: input.serverId, scope: input.scope, item_id: input.itemId, media_source_id: input.mediaSourceId }) });
}

export function deleteProbeHistory(input: { serverId: string; scope: ProbeScope }): Promise<ProbeActionResponse> {
  return request<ProbeActionResponse>("/api/v1/emby/probe/history", { method: "DELETE", body: JSON.stringify({ server_id: input.serverId, scope: input.scope }) });
}

export function deleteProbeBlacklist(input: { serverId: string; scope: ProbeScope; type: "error" | "incomplete"; itemId?: string; mediaSourceId?: string }): Promise<ProbeActionResponse> {
  return request<ProbeActionResponse>("/api/v1/emby/probe/blacklist", { method: "DELETE", body: JSON.stringify({ server_id: input.serverId, scope: input.scope, type: input.type, item_id: input.itemId, media_source_id: input.mediaSourceId }) });
}

export function retryProbeItem(input: { serverId: string; scope: ProbeScope; itemId: string; mediaSourceId?: string }): Promise<ProbeActionResponse> {
  return runProbeAction("/api/v1/emby/probe/retry", { server_id: input.serverId, scope: input.scope, item_id: input.itemId, media_source_id: input.mediaSourceId });
}

export async function retryBlacklistedProbeItem(input: {
  serverId: string;
  scope: ProbeScope;
  type: "error" | "incomplete";
  itemId: string;
  mediaSourceId?: string;
}): Promise<ProbeActionResponse> {
  await deleteProbeBlacklist(input);
  return retryProbeItem(input);
}
