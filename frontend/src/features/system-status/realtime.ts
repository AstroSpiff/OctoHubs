import {
  configurationUpdateScope,
  isEventBridgeUpdate,
} from "@/lib/application-events";
import type { ApplicationEvent } from "@/lib/use-application-event";

const embyConnectionEvents = new Set([
  "ConnectionEstablished",
  "ConnectionClosed",
  "SessionsUpdate",
]);

const systemStatusSectionsByConfigurationScope = {
  servers: ["emby", "event-bridge", "transcode-guard"],
  services: ["database", "services"],
} as const;

function systemStatusRefreshDelayMs(refreshIntervalSeconds?: number): number | null {
  if (refreshIntervalSeconds === undefined) return 60_000;
  return Number.isFinite(refreshIntervalSeconds) && refreshIntervalSeconds > 0
    ? refreshIntervalSeconds * 1_000
    : null;
}

export function systemStatusSectionsForEvent(event: ApplicationEvent): string[] {
  if (isEventBridgeUpdate(event)) {
    return ["event-bridge", "transcode-guard"];
  }
  const configurationScope = configurationUpdateScope(event);
  if (configurationScope && configurationScope in systemStatusSectionsByConfigurationScope) {
    return [...systemStatusSectionsByConfigurationScope[
      configurationScope as keyof typeof systemStatusSectionsByConfigurationScope
    ]];
  }
  return embyConnectionEvents.has(String(event.MessageType || "")) ? ["emby"] : [];
}

export function isSystemStatusRealtimeEvent(event: ApplicationEvent): boolean {
  return systemStatusSectionsForEvent(event).length > 0;
}

export { systemStatusRefreshDelayMs };
