import type { ApplicationEvent } from "@/lib/use-application-event";

const usersUpdatedMessage = "OctoHubsUsersUpdated";

function isUserIconsRealtimeEvent(event: ApplicationEvent): boolean {
  if (event.MessageType !== usersUpdatedMessage) return false;
  const data = event.Data;
  return Boolean(
    data &&
      typeof data === "object" &&
      (data as Record<string, unknown>).scope === "icons",
  );
}

export { isUserIconsRealtimeEvent };
