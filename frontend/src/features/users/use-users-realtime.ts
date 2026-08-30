import { useEffect, useRef } from "react";

const userEventPattern = /user|policy|configuration|permission/i;
const refreshDelayMs = 800;

type EmbyRealtimeEvent = {
  MessageType?: unknown;
  Data?: unknown;
};

function isUserRelatedEmbyEvent(event: EmbyRealtimeEvent) {
  const messageType = String(event.MessageType || "");
  if (userEventPattern.test(messageType)) return true;

  const data = event.Data;
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  if (userEventPattern.test(Object.keys(record).join(" "))) return true;
  return ["UserId", "UserIds", "Users", "Policy", "Configuration"].some((key) => key in record);
}

function useUsersRealtime(onRefresh: () => void) {
  const refreshRef = useRef(onRefresh);

  useEffect(() => {
    refreshRef.current = onRefresh;
  }, [onRefresh]);

  useEffect(() => {
    let timer: number | undefined;
    const source = new EventSource("/api/emby/events-stream");

    source.onmessage = (message) => {
      if (document.visibilityState === "hidden") return;
      try {
        const event = JSON.parse(message.data) as EmbyRealtimeEvent;
        if (!isUserRelatedEmbyEvent(event)) return;
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          timer = undefined;
          refreshRef.current();
        }, refreshDelayMs);
      } catch {
        // Keep the normal polling fallback when an external event is malformed.
      }
    };

    return () => {
      if (timer) window.clearTimeout(timer);
      source.close();
    };
  }, []);
}

export { isUserRelatedEmbyEvent, useUsersRealtime };
