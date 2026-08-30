import { configurationUpdateScope } from "@/lib/application-events";
import type { ApplicationEvent } from "@/lib/use-application-event";

const latestUpdatedMessage = "OctoHubsLatestUpdated";

type LatestRealtimeTarget = "configuration" | "snapshot";

function latestRealtimeTargets(event: ApplicationEvent): LatestRealtimeTarget[] {
  if (event.MessageType === latestUpdatedMessage) {
    const data = event.Data;
    const scope =
      data && typeof data === "object"
        ? String((data as { scope?: unknown }).scope || "")
        : "";
    if (scope === "configuration") return ["configuration"];
    if (scope === "snapshot") return ["snapshot"];
    return ["configuration", "snapshot"];
  }

  const configurationScope = configurationUpdateScope(event);
  if (configurationScope === "servers") return ["configuration", "snapshot"];
  if (configurationScope === "telegram") return ["configuration"];
  return [];
}

function isLatestRealtimeEvent(event: ApplicationEvent): boolean {
  return latestRealtimeTargets(event).length > 0;
}

export {
  isLatestRealtimeEvent,
  latestRealtimeTargets,
  latestUpdatedMessage,
};
export type { LatestRealtimeTarget };
