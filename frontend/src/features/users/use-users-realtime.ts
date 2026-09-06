import {
  type ApplicationEvent,
  useApplicationEventRefresh,
} from "@/lib/use-application-event";

const userEventPattern = /user|policy|configuration|permission/i;
const refreshDelayMs = 800;

function isUserRelatedEmbyEvent(event: ApplicationEvent) {
  const messageType = String(event.MessageType || "");
  if (userEventPattern.test(messageType)) return true;

  const data = event.Data;
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  if (userEventPattern.test(Object.keys(record).join(" "))) return true;
  return ["UserId", "UserIds", "Users", "Policy", "Configuration"].some((key) => key in record);
}

function useUsersRealtime(onRefresh: () => void) {
  useApplicationEventRefresh(
    isUserRelatedEmbyEvent,
    () => onRefresh(),
    refreshDelayMs,
  );
}

export { isUserRelatedEmbyEvent, useUsersRealtime };
