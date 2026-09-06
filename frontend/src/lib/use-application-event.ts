import { useEffect, useRef } from "react";

const defaultRefreshDelayMs = 350;
const maxPendingEventTargets = 64;

type ApplicationEvent = {
  MessageType?: unknown;
  Data?: unknown;
  server_id?: unknown;
};

type ApplicationEventListener = (event: ApplicationEvent) => void;

const applicationEventListeners = new Set<ApplicationEventListener>();
let applicationEventSource: EventSource | undefined;

function ensureApplicationEventSource() {
  if (applicationEventSource) return;
  applicationEventSource = new EventSource("/api/emby/events-stream");
  applicationEventSource.onmessage = (message) => {
    if (document.visibilityState === "hidden") return;
    try {
      const event = JSON.parse(message.data) as ApplicationEvent;
      applicationEventListeners.forEach((listener) => listener(event));
    } catch {
      // Feature-specific polling remains the fallback for malformed events.
    }
  };
}

function subscribeApplicationEvents(listener: ApplicationEventListener) {
  applicationEventListeners.add(listener);
  ensureApplicationEventSource();
  return () => {
    applicationEventListeners.delete(listener);
    if (applicationEventListeners.size || !applicationEventSource) return;
    applicationEventSource.close();
    applicationEventSource = undefined;
  };
}

function applicationEventTargetKey(event: ApplicationEvent): string {
  const data = event.Data;
  const record = data && typeof data === "object"
    ? data as Record<string, unknown>
    : {};
  const serverIds = Array.isArray(record.server_ids)
    ? record.server_ids.map(String).sort().join(",")
    : "";
  return [
    String(event.MessageType || "event"),
    String(event.server_id || record.server_id || ""),
    String(record.scope || ""),
    String(record.reason || ""),
    String(record.operation_id || ""),
    serverIds,
  ].join("|");
}

function useApplicationEventRefresh(
  isRelevant: (event: ApplicationEvent) => boolean,
  onRefresh: (event: ApplicationEvent) => void,
  delayMs = defaultRefreshDelayMs,
) {
  const matchRef = useRef(isRelevant);
  const callbackRef = useRef(onRefresh);

  useEffect(() => {
    matchRef.current = isRelevant;
    callbackRef.current = onRefresh;
  }, [isRelevant, onRefresh]);

  useEffect(() => {
    let timer: number | undefined;
    const pendingEvents = new Map<string, ApplicationEvent>();

    const unsubscribe = subscribeApplicationEvents((event) => {
      if (!matchRef.current(event)) return;
      const targetKey = applicationEventTargetKey(event);
      if (!pendingEvents.has(targetKey) && pendingEvents.size >= maxPendingEventTargets) {
        const oldestKey = pendingEvents.keys().next().value;
        if (oldestKey !== undefined) pendingEvents.delete(oldestKey);
      }
      pendingEvents.set(targetKey, event);
      if (timer) return;
      timer = window.setTimeout(() => {
        timer = undefined;
        const events = [...pendingEvents.values()];
        pendingEvents.clear();
        events.forEach((pendingEvent) => callbackRef.current(pendingEvent));
      }, delayMs);
    });

    return () => {
      if (timer) window.clearTimeout(timer);
      pendingEvents.clear();
      unsubscribe();
    };
  }, [delayMs]);
}

export type { ApplicationEvent };
export { useApplicationEventRefresh };
