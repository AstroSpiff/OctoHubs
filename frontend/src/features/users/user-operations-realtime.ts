import type { ApplicationEvent } from "@/lib/use-application-event";

function isUserOperationsRealtimeEvent(event: ApplicationEvent): boolean {
  if (event.MessageType !== "OctoHubsUsersUpdated") return false;
  const data = event.Data;
  return Boolean(
    data &&
      typeof data === "object" &&
      (data as Record<string, unknown>).scope === "operations",
  );
}

export { isUserOperationsRealtimeEvent };
