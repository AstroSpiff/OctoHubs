import { request } from "@/lib/http";
import type { EventBridgeCredentialResult, EventBridgeSaveResult, EventBridgeSettings, EventBridgeStatus } from "@/features/event-bridge/types";

export function getEventBridgeStatus(): Promise<EventBridgeStatus> {
  return request<EventBridgeStatus>("/api/v1/event-bridge/status");
}

export function saveEventBridgeSettings(serverId: string, settings: EventBridgeSettings): Promise<EventBridgeSaveResult> {
  return request<EventBridgeSaveResult>("/api/v1/event-bridge/settings", {
    method: "PUT",
    body: JSON.stringify({ servers: { [serverId]: settings } }),
  });
}

export function provisionEventBridgeCredential(serverId: string): Promise<EventBridgeCredentialResult> {
  return request<EventBridgeCredentialResult>(`/api/v1/event-bridge/servers/${encodeURIComponent(serverId)}/credential`, {
    method: "POST",
  });
}
