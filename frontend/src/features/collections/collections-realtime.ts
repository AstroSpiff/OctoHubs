import { configurationUpdateScope } from "@/lib/application-events";
import type { ApplicationEvent } from "@/lib/use-application-event";

const collectionsUpdatedMessage = "OctoHubsCollectionsUpdated";

type CollectionsRealtimeTarget =
  | "collections"
  | "options"
  | "source-inventory";

function collectionsUpdateScope(event: ApplicationEvent): string {
  if (event.MessageType !== collectionsUpdatedMessage) return "";
  const data = event.Data;
  if (!data || typeof data !== "object") return "";
  const scope = (data as { scope?: unknown }).scope;
  return typeof scope === "string" ? scope.trim() : "";
}

function collectionRealtimeTargets(
  event: ApplicationEvent,
): CollectionsRealtimeTarget[] {
  const scope = collectionsUpdateScope(event);
  if (scope === "definitions" || scope === "media" || scope === "sync") {
    return ["collections"];
  }
  if (scope === "sources") return ["source-inventory"];

  const configurationScope = configurationUpdateScope(event);
  if (configurationScope === "servers") return ["collections", "options"];
  if (configurationScope === "services") return ["options"];
  return [];
}

function isCollectionsRealtimeEvent(event: ApplicationEvent): boolean {
  return collectionRealtimeTargets(event).length > 0;
}

export {
  collectionRealtimeTargets,
  collectionsUpdatedMessage,
  collectionsUpdateScope,
  isCollectionsRealtimeEvent,
};
export type { CollectionsRealtimeTarget };
