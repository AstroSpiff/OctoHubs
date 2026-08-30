import { useEffect, useRef } from "react";

const defaultRefreshDelayMs = 350;

type ApplicationEvent = {
  MessageType?: unknown;
  Data?: unknown;
  server_id?: unknown;
};

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
    const source = new EventSource("/api/emby/events-stream");

    source.onmessage = (message) => {
      if (document.visibilityState === "hidden") return;
      try {
        const event = JSON.parse(message.data) as ApplicationEvent;
        if (!matchRef.current(event))
          return;
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          timer = undefined;
          callbackRef.current(event);
        }, delayMs);
      } catch {
        // Feature-specific polling remains the fallback for malformed events.
      }
    };

    return () => {
      if (timer) window.clearTimeout(timer);
      source.close();
    };
  }, [delayMs]);
}

export type { ApplicationEvent };
export { useApplicationEventRefresh };
